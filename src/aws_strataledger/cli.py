"""
AWS StrataLedger CLI — Entry point for the inventory scanner.

Usage:
    aws-strataledger scan --profiles prod,staging --regions us-east-1,eu-west-1
    aws-strataledger scan --profiles all --regions all
    aws-strataledger profiles
    aws-strataledger report --input scan-data.json --output report.html
"""

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import (
    resolve_profiles,
    resolve_regions,
    resolve_services,
    discover_sso_profiles,
    ScanConfig,
)
from .scanner import run_scan
from .report.generator import generate_report

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="aws-strataledger")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose/debug logging")
def main(verbose):
    """⚡ AWS StrataLedger — Multi-Account Inventory & Topology Discovery Tool"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@main.command()
@click.option(
    "--profiles", "-p",
    required=True,
    help="Comma-separated SSO profile names, or 'all' for all profiles.",
)
@click.option(
    "--regions", "-r",
    required=True,
    help="Comma-separated AWS regions, or 'all' for all regions.",
)
@click.option(
    "--services", "-s",
    default=None,
    help="Comma-separated service categories to scan (e.g., compute,networking,storage). Default: all.",
)
@click.option(
    "--output", "-o",
    default="./reports",
    help="Output directory for scan data and reports. Default: ./reports",
)
def scan(profiles, regions, services, output):
    """Run a multi-account, multi-region inventory scan."""
    resolved_profiles = resolve_profiles(profiles)
    if not resolved_profiles:
        console.print("[red]❌ No valid profiles to scan. Aborting.[/red]")
        sys.exit(1)

    resolved_regions = resolve_regions(regions)
    if not resolved_regions:
        console.print("[red]❌ No valid regions to scan. Aborting.[/red]")
        sys.exit(1)

    resolved_services = resolve_services(services)

    config = ScanConfig(
        profiles=resolved_profiles,
        regions=resolved_regions,
        services=resolved_services,
        output_dir=output,
    )

    # Run scan
    scan_data = run_scan(config)

    if not scan_data or not scan_data.get("accounts"):
        console.print("[red]❌ Scan produced no results.[/red]")
        sys.exit(1)

    # Generate report
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = str(Path(output) / f"report-{timestamp}.html")
    generate_report(scan_data, report_path)


@main.command()
def profiles():
    """List all available SSO profiles from ~/.aws/config."""
    sso_profiles = discover_sso_profiles()

    if not sso_profiles:
        console.print("[yellow]No SSO profiles found in ~/.aws/config[/yellow]")
        console.print("[dim]Run: aws configure sso[/dim]")
        return

    table = Table(title="Available SSO Profiles")
    table.add_column("Profile Name", style="cyan bold")
    table.add_column("SSO Account ID", style="white")
    table.add_column("SSO Role", style="white")
    table.add_column("Region", style="dim")
    table.add_column("SSO Start URL", style="dim")

    for p in sso_profiles:
        table.add_row(
            p.profile_name,
            p.sso_account_id or "—",
            p.sso_role_name or "—",
            p.region,
            p.sso_start_url[:50] + "…" if len(p.sso_start_url) > 50 else p.sso_start_url or "—",
        )

    console.print(table)


@main.command()
@click.option("--input", "-i", required=True, help="Path to scan JSON file.")
@click.option("--output", "-o", required=True, help="Path for output HTML report.")
def report(input, output):
    """Generate an HTML report from an existing scan JSON file."""
    input_path = Path(input)
    if not input_path.exists():
        console.print(f"[red]❌ File not found: {input}[/red]")
        sys.exit(1)

    console.print(f"[bold]📂 Loading scan data from:[/bold] {input}")

    with open(input_path) as f:
        scan_data = json.load(f)

    generate_report(scan_data, output)


if __name__ == "__main__":
    main()
