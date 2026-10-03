from __future__ import annotations

"""
Scan orchestrator.

Coordinates multi-account, multi-region scanning using
ThreadPoolExecutor for parallelism across regions and services.
Collectors receive a ClientFactory (thread-safe, cached clients)
and report structured issues instead of discarding errors.
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
from .config import ScanConfig, ProfileConfig
from .session import SessionManager, AccountInfo, ClientFactory
from .collectors.compute import ComputeCollector
from .collectors.networking import NetworkingCollector
from .collectors.storage import StorageCollector, S3Collector
from .collectors.identity import IAMCollector, IdentityCollector
from .collectors.security import SecurityCollector, Route53Collector, OrganizationsCollector
from .collectors.monitoring import MonitoringCollector
from .collectors.integration import IntegrationCollector
from .collectors.analytics import AnalyticsCollector
from .collectors.edge import EdgeCollector

logger = logging.getLogger("aws_strataledger")
console = Console()

# Collector registry: (key, collector_cls)
REGIONAL_COLLECTORS = [
    ("compute", ComputeCollector),
    ("networking", NetworkingCollector),
    ("storage", StorageCollector),
    ("identity", IdentityCollector),
    ("security", SecurityCollector),
    ("monitoring", MonitoringCollector),
    ("integration", IntegrationCollector),
    ("analytics", AnalyticsCollector),
]

GLOBAL_COLLECTORS = [
    ("s3", S3Collector),
    ("iam", IAMCollector),
    ("route53", Route53Collector),
    ("organizations", OrganizationsCollector),
    ("edge", EdgeCollector),
]

# Maps user-facing service aliases to collector keys so that
# ``--services s3,iam,ec2`` resolves correctly.
SERVICE_ALIAS_MAP: dict[str, str] = {
    "ec2": "compute",
    "lambda": "compute",
    "ecs": "compute",
    "eks": "compute",
    "ecr": "compute",
    "autoscaling": "compute",
    "beanstalk": "compute",
    "elasticbeanstalk": "compute",
    "vpc": "networking",
    "elb": "networking",
    "elbv2": "networking",
    "apigateway": "networking",
    "cloudfront": "edge",
    "globalaccelerator": "edge",
    "s3": "storage",
    "rds": "storage",
    "dynamodb": "storage",
    "elasticache": "storage",
    "memorydb": "storage",
    "fsx": "storage",
    "opensearch": "storage",
    "redshift": "storage",
    "efs": "storage",
    "backup": "storage",
    "iam": "identity",
    "kms": "identity",
    "secretsmanager": "identity",
    "ssm": "identity",
    "acm": "identity",
    "cognito": "identity",
    "guardduty": "security",
    "inspector": "security",
    "securityhub": "security",
    "config": "security",
    "cloudtrail": "security",
    "macie": "security",
    "cloudwatch": "monitoring",
    "eventbridge": "monitoring",
    "sns": "integration",
    "sqs": "integration",
    "stepfunctions": "integration",
    "sfn": "integration",
    "mq": "integration",
    "kinesis": "analytics",
    "firehose": "analytics",
    "msk": "analytics",
    "kafka": "analytics",
    "emr": "analytics",
}


def _resolve_service_filter(services: list[str] | None) -> set[str] | None:
    """Expand user-facing service names into collector keys."""
    if not services:
        return None
    keys: set[str] = set()
    for s in services:
        s_lower = s.lower()
        if s_lower in SERVICE_ALIAS_MAP:
            keys.add(SERVICE_ALIAS_MAP[s_lower])
        else:
            # Accept collector keys directly too (compute, networking, …)
            keys.add(s_lower)
    return keys


def _run_collector(
    collector_cls, clients: ClientFactory, region: str, account_id: str,
) -> tuple[str, dict, list[dict]]:
    """Run a single collector and return (name, results, issues)."""
    collector = collector_cls(clients, region, account_id)
    try:
        results = collector.collect()
    except Exception as e:
        logger.debug("Collector %s crashed: %s", collector_cls.__name__, e, exc_info=True)
        results = {}
    return (
        collector_cls.SERVICE_NAME,
        results,
        collector.get_issues(),
    )


def _count_resources(data: dict) -> int:
    """Count total resources in an inventory dict, skipping metadata keys (``_`` prefix)."""
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            if isinstance(value, list):
                count += len(value)
            elif isinstance(value, dict):
                count += _count_resources(value)
    return count


def scan_region(
    clients: ClientFactory,
    region: str,
    account_id: str,
    service_filter: set[str] | None = None,
) -> tuple[dict, list[dict]]:
    """
    Scan all regional services in a single region.

    Returns:
        (inventory dict, list of issues)
    """
    inventory: dict = {}
    all_issues: list[dict] = []

    collectors_to_run = []
    for key, cls in REGIONAL_COLLECTORS:
        if service_filter and key not in service_filter:
            continue
        collectors_to_run.append((key, cls))

    with ThreadPoolExecutor(max_workers=len(REGIONAL_COLLECTORS)) as executor:
        futures = {}
        for key, cls in collectors_to_run:
            future = executor.submit(_run_collector, cls, clients, region, account_id)
            futures[future] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                _name, results, issues = future.result(timeout=300)
                inventory[key] = results
                all_issues.extend(issues)
            except Exception as e:
                logger.debug("Collector %s failed in %s: %s", key, region, e)
                inventory[key] = {}

    return inventory, all_issues


def scan_global_services(
    clients: ClientFactory,
    account_id: str,
    region: str,
    service_filter: set[str] | None = None,
) -> tuple[dict, list[dict]]:
    """
    Scan global services (S3, IAM, Route 53, Organizations).
    Called once per account.
    """
    inventory: dict = {}
    all_issues: list[dict] = []

    for key, cls in GLOBAL_COLLECTORS:
        if service_filter and key not in service_filter:
            continue
        try:
            _name, results, issues = _run_collector(cls, clients, region, account_id)
            inventory[key] = results
            all_issues.extend(issues)
        except Exception as e:
            logger.debug("Global collector %s failed: %s", key, e)
            inventory[key] = {}

    return inventory, all_issues


def _deduplicate_trails(scan_result: dict) -> None:
    """
    De-duplicate CloudTrail trails across regions by ARN.

    Multi-region trails are reported in every region (``includeShadowTrails``);
    keep the home-region copy and drop shadows.
    """
    for account_data in scan_result.get("accounts", {}).values():
        seen_arns: set[str] = set()
        for _region, region_data in sorted(account_data.get("regions", {}).items()):
            sec = region_data.get("security", {})
            trails: list[dict] = sec.get("cloudtrail_trails", [])
            if not trails:
                continue
            deduped = []
            for t in trails:
                arn = t.get("resource_id", "")
                if arn in seen_arns:
                    continue
                seen_arns.add(arn)
                deduped.append(t)
            sec["cloudtrail_trails"] = deduped


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
    seen_accounts: set[str] = set()

    for profile in config.profiles:
        session = session_mgr.create_session(profile, verbose=config.verbose)
        if session:
            info = session_mgr.get_account_info(profile.profile_name)
            if info:
                if info.account_id in seen_accounts:
                    console.print(
                        f"  [yellow]⚠️[/yellow] Skipping [bold]{profile.profile_name}[/bold] "
                        f"(account {info.account_id} already queued via another profile)"
                    )
                    continue
                seen_accounts.add(info.account_id)
                valid_profiles.append((profile, info))

    if not valid_profiles:
        console.print("[red]❌ No valid profiles. Aborting scan.[/red]")
        return {}

    if not config.verbose:
        console.print(
            f"  [green]✅[/green] Validated {len(valid_profiles)} profile(s): "
            f"{', '.join(p[0].profile_name for p in valid_profiles)}"
        )

    service_filter = _resolve_service_filter(config.services)

    console.print()
    console.print(f"[bold]🌍 Regions:[/bold] {', '.join(config.regions)}")
    console.print(f"[bold]📦 Services:[/bold] {'ALL' if not service_filter else ', '.join(sorted(service_filter))}")
    console.print()

    # ── Scan each account ────────────────────────────────────────────
    scan_result: dict = {
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
    all_issues: list[dict] = []

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
            clients = session_mgr.get_factory(profile.profile_name)
            if clients is None:
                progress.advance(overall, advance=len(config.regions) + 1)
                continue

            account_data: dict = {
                "account_id": account_id,
                "account_alias": alias,
                "profile_name": profile.profile_name,
                "regions": {},
            }

            # Scan global services first
            progress.update(overall, description=f"[cyan]{alias}[/cyan] / [yellow]global services[/yellow]")
            global_region = config.regions[0] if config.regions else "us-east-1"
            global_inventory, global_issues = scan_global_services(
                clients, account_id,
                region=global_region,
                service_filter=service_filter,
            )
            account_data["global"] = global_inventory
            all_issues.extend(global_issues)
            progress.advance(overall)

            # Scan each region in parallel
            with ThreadPoolExecutor(max_workers=config.max_workers_regions) as region_pool:
                region_futures = {}
                for region in config.regions:
                    future = region_pool.submit(
                        scan_region, clients, region, account_id, service_filter,
                    )
                    region_futures[future] = region

                for future in as_completed(region_futures):
                    region = region_futures[future]
                    progress.update(
                        overall,
                        description=f"[cyan]{alias}[/cyan] / [yellow]{region}[/yellow]",
                    )
                    try:
                        region_inventory, region_issues = future.result(timeout=600)
                        account_data["regions"][region] = region_inventory
                        all_issues.extend(region_issues)
                        total_resources += _count_resources(region_inventory)
                    except Exception as e:
                        logger.debug("Region %s failed for %s: %s", region, alias, e)
                        account_data["regions"][region] = {}
                    progress.advance(overall)

            # Count global resources
            total_resources += _count_resources(global_inventory)
            scan_result["accounts"][account_id] = account_data

    # ── Post-processing ─────────────────────────────────────────────
    _deduplicate_trails(scan_result)

    elapsed = time.time() - start_time
    scan_result["scan_metadata"]["scan_duration_seconds"] = round(elapsed, 1)
    scan_result["scan_metadata"]["total_resources"] = total_resources
    scan_result["scan_metadata"]["issues"] = all_issues
    scan_result["scan_metadata"]["issue_summary"] = {
        "total": len(all_issues),
        "errors": sum(1 for i in all_issues if i.get("level") == "error"),
        "denied": sum(1 for i in all_issues if i.get("level") == "denied"),
        "unavailable": sum(1 for i in all_issues if i.get("level") == "unavailable"),
    }

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

    issue_summary = scan_result["scan_metadata"]["issue_summary"]
    if issue_summary["total"]:
        summary_table.add_row(
            "Collection Issues",
            f"{issue_summary['total']} "
            f"({issue_summary['errors']} errors, "
            f"{issue_summary['denied']} denied, "
            f"{issue_summary['unavailable']} unavailable)",
        )
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
