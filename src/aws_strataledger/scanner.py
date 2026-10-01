from __future__ import annotations

"""
Scan orchestrator.

Coordinates multi-account, multi-region scanning using
ThreadPoolExecutor for parallelism across regions and services.
"""

import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from . import __version__
from .config import ScanConfig, ProfileConfig, GLOBAL_SERVICES
from .session import SessionManager, AccountInfo
from .topology import build_topology
from .collectors.compute import ComputeCollector
from .collectors.networking import NetworkingCollector
from .collectors.storage import StorageCollector, S3Collector
from .collectors.identity import IAMCollector, IdentityCollector
from .collectors.security import SecurityCollector, Route53Collector, OrganizationsCollector
from .collectors.monitoring import MonitoringCollector

logger = logging.getLogger("aws_strataledger")
console = Console()

# Collector registry: (key, collector_cls, is_global)
REGIONAL_COLLECTORS = [
    ("compute", ComputeCollector),
    ("networking", NetworkingCollector),
    ("storage", StorageCollector),
    ("identity", IdentityCollector),
    ("security", SecurityCollector),
    ("monitoring", MonitoringCollector),
]

GLOBAL_COLLECTORS = [
    ("s3", S3Collector),
    ("iam", IAMCollector),
    ("route53", Route53Collector),
    ("organizations", OrganizationsCollector),
]


def _run_collector(collector_cls, session, region, account_id) -> tuple[str, dict, list, list]:
    """Run a single collector and return (name, results, errors, warnings)."""
    collector = collector_cls(session, region, account_id)
    try:
        results = collector.collect()
    except Exception as e:
        logger.debug(f"Collector {collector_cls.__name__} crashed: {e}", exc_info=True)
        results = {}
    return (
        collector_cls.SERVICE_NAME if hasattr(collector_cls, 'SERVICE_NAME') else collector_cls.__name__,
        results,
        collector.get_errors(),
        collector.get_warnings(),
    )


def _count_resources(data: dict) -> int:
    """Count total resources in an inventory dict."""
    count = 0
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                count += len(value)
            elif isinstance(value, dict):
                count += _count_resources(value)
    return count


def scan_region(session, region: str, account_id: str, service_filter: list[str] | None = None) -> dict:
    """
    Scan all regional services in a single region.

    Args:
        session: boto3.Session
        region: AWS region name
        account_id: AWS account ID
        service_filter: Optional list of service names to scan

    Returns:
        dict of category -> {resource_type -> [resources]}
    """
    inventory = {}
    all_errors = []
    all_warnings = []

    collectors_to_run = []
    for key, cls in REGIONAL_COLLECTORS:
        if service_filter and key not in service_filter:
            continue
        collectors_to_run.append((key, cls))

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        for key, cls in collectors_to_run:
            future = executor.submit(_run_collector, cls, session, region, account_id)
            futures[future] = key
            # Small delay to avoid burst throttling
            time.sleep(0.1)

        for future in as_completed(futures):
            key = futures[future]
            try:
                name, results, errors, warnings = future.result(timeout=300)
                inventory[key] = results
                all_errors.extend(errors)
                all_warnings.extend(warnings)
            except Exception as e:
                logger.debug(f"Collector {key} failed in {region}: {e}")
                inventory[key] = {}

    # Build topology
    inventory["topology"] = build_topology(inventory)

    return inventory


def scan_global_services(session, account_id: str, region: str, service_filter: list[str] | None = None) -> dict:
    """
    Scan global services (S3, IAM, Route 53, Organizations).
    Called once per account.
    """
    inventory = {}

    for key, cls in GLOBAL_COLLECTORS:
        if service_filter and key not in service_filter:
            continue
        try:
            _, results, errors, warnings = _run_collector(cls, session, region, account_id)
            inventory[key] = results
            for e in errors:
                logger.debug(e)
            for w in warnings:
                logger.debug(w)
        except Exception as e:
            logger.debug(f"Global collector {key} failed: {e}")
            inventory[key] = {}

    return inventory


def run_scan(config: ScanConfig) -> dict:
    """
    Execute a complete multi-account, multi-region scan.

    Returns the full scan result dict ready for report generation.
    """
    start_time = time.time()
    session_mgr = SessionManager(verbose=config.verbose)

    console.print()
    console.print(f"[bold cyan]⚡ AWS StrataLedger v{__version__}[/bold cyan] — Multi-Account Inventory Scanner")
    console.print()

    # ── Validate profiles ────────────────────────────────────────────
    console.print("[bold]📋 Validating profiles...[/bold]")
    valid_profiles: list[tuple[ProfileConfig, AccountInfo]] = []

    for profile in config.profiles:
        session = session_mgr.create_session(profile, verbose=config.verbose)
        if session:
            info = session_mgr.get_account_info(profile.profile_name)
            if info:
                valid_profiles.append((profile, info))

    if not valid_profiles:
        console.print("[red]❌ No valid profiles. Aborting scan.[/red]")
        return {}

    if not config.verbose:
        console.print(
            f"  [green]✅[/green] Validated {len(valid_profiles)} profile(s): "
            f"{', '.join(p[0].profile_name for p in valid_profiles)}"
        )

    console.print()
    console.print(f"[bold]🌍 Regions:[/bold] {', '.join(config.regions)}")
    console.print(f"[bold]📦 Services:[/bold] {'ALL' if not config.services else ', '.join(config.services)}")
    console.print()

    # ── Scan each account ────────────────────────────────────────────
    scan_result = {
        "scan_metadata": {
            "tool": "aws-strataledger",
            "version": __version__,
            "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            "profiles_scanned": len(valid_profiles),
            "regions_scanned": len(config.regions),
        },
        "accounts": {},
    }

    total_tasks = len(valid_profiles) * (len(config.regions) + 1)  # +1 for global services
    total_resources = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        overall = progress.add_task("[cyan]Overall progress", total=total_tasks)

        for profile, account_info in valid_profiles:
            account_id = account_info.account_id
            alias = account_info.account_alias
            session = session_mgr.get_session(profile.profile_name)

            account_data = {
                "account_id": account_id,
                "account_alias": alias,
                "profile_name": profile.profile_name,
                "regions": {},
            }

            # Scan global services first
            progress.update(overall, description=f"[cyan]{alias}[/cyan] / [yellow]global services[/yellow]")
            global_inventory = scan_global_services(
                session, account_id,
                region=config.regions[0] if config.regions else "us-east-1",
                service_filter=config.services,
            )
            account_data["global"] = global_inventory
            progress.advance(overall)

            # Scan each region
            for region in config.regions:
                progress.update(
                    overall,
                    description=f"[cyan]{alias}[/cyan] / [yellow]{region}[/yellow]",
                )
                region_inventory = scan_region(
                    session, region, account_id,
                    service_filter=config.services,
                )
                account_data["regions"][region] = region_inventory

                rc = _count_resources(region_inventory)
                total_resources += rc
                progress.advance(overall)

            # Count global resources
            total_resources += _count_resources(global_inventory)
            scan_result["accounts"][account_id] = account_data

    elapsed = time.time() - start_time
    scan_result["scan_metadata"]["scan_duration_seconds"] = round(elapsed, 1)
    scan_result["scan_metadata"]["total_resources"] = total_resources

    # ── Summary ──────────────────────────────────────────────────────
    console.print()
    console.print("[bold green]✅ Scan complete![/bold green]")
    console.print()

    summary_table = Table(title="Scan Summary")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="white")
    summary_table.add_row("Accounts Scanned", str(len(valid_profiles)))
    summary_table.add_row("Regions Scanned", str(len(config.regions)))
    summary_table.add_row("Total Resources", f"{total_resources:,}")
    summary_table.add_row("Duration", f"{elapsed:.1f}s")
    console.print(summary_table)

    # ── Save JSON ────────────────────────────────────────────────────
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"scan-{timestamp}.json"

    with open(json_path, "w") as f:
        json.dump(scan_result, f, indent=2, default=str)

    console.print(f"\n[bold]📁 Scan data saved:[/bold] {json_path}")

    return scan_result
