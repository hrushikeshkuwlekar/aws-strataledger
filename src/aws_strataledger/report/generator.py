"""
Report generator.

Renders scan data into a self-contained HTML report using Jinja2.
"""

import json
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from rich.console import Console

console = Console()

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _flatten_resources(scan_data: dict) -> list[dict]:
    """
    Flatten all resources from all accounts/regions into a single list
    for the inventory table.
    """
    resources = []
    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)

        # Global resources
        global_data = account.get("global", {})
        for category, category_data in global_data.items():
            if isinstance(category_data, dict):
                for resource_type, resource_list in category_data.items():
                    if isinstance(resource_list, list):
                        for r in resource_list:
                            r["_account_id"] = account_id
                            r["_account_alias"] = alias
                            r["_category"] = category
                            resources.append(r)

        # Regional resources
        for region, region_data in account.get("regions", {}).items():
            for category, category_data in region_data.items():
                if category == "topology":
                    continue
                if isinstance(category_data, dict):
                    for resource_type, resource_list in category_data.items():
                        if isinstance(resource_list, list):
                            for r in resource_list:
                                r["_account_id"] = account_id
                                r["_account_alias"] = alias
                                r["_category"] = category
                                resources.append(r)

    return resources


def _build_summary(scan_data: dict) -> dict:
    """Build summary statistics from scan data."""
    summary = {
        "total_accounts": len(scan_data.get("accounts", {})),
        "total_regions": scan_data.get("scan_metadata", {}).get("regions_scanned", 0),
        "total_resources": scan_data.get("scan_metadata", {}).get("total_resources", 0),
        "scan_time": scan_data.get("scan_metadata", {}).get("scan_timestamp", ""),
        "scan_duration": scan_data.get("scan_metadata", {}).get("scan_duration_seconds", 0),
        "accounts": [],
        "resource_counts_by_type": {},
        "resource_counts_by_category": {},
    }

    for account_id, account in scan_data.get("accounts", {}).items():
        account_summary = {
            "account_id": account_id,
            "account_alias": account.get("account_alias", account_id),
            "profile_name": account.get("profile_name", ""),
            "regions": list(account.get("regions", {}).keys()),
            "resource_counts": {},
        }

        # Count resources per type
        def count_in(data):
            for category, category_data in data.items():
                if category == "topology":
                    continue
                if isinstance(category_data, dict):
                    for resource_type, resource_list in category_data.items():
                        if isinstance(resource_list, list):
                            count = len(resource_list)
                            account_summary["resource_counts"][resource_type] = (
                                account_summary["resource_counts"].get(resource_type, 0) + count
                            )
                            summary["resource_counts_by_type"][resource_type] = (
                                summary["resource_counts_by_type"].get(resource_type, 0) + count
                            )
                            summary["resource_counts_by_category"][category] = (
                                summary["resource_counts_by_category"].get(category, 0) + count
                            )

        count_in(account.get("global", {}))
        for region_data in account.get("regions", {}).values():
            count_in(region_data)

        summary["accounts"].append(account_summary)

    return summary


def _build_security_summary(scan_data: dict) -> list[dict]:
    """Build per-account security posture summary."""
    security_items = []

    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)
        item = {
            "account_id": account_id,
            "account_alias": alias,
            "guardduty_enabled": False,
            "security_hub_enabled": False,
            "cloudtrail_logging": False,
            "cloudtrail_multi_region": False,
            "config_recording": False,
            "iam_users_without_mfa": 0,
            "public_s3_buckets": 0,
            "findings": [],
        }

        # Check all regions for security services
        for region, region_data in account.get("regions", {}).items():
            sec = region_data.get("security", {})

            # GuardDuty
            for detector in sec.get("guardduty_detectors", []):
                if detector.get("status") == "ENABLED":
                    item["guardduty_enabled"] = True

            # Security Hub
            for hub in sec.get("security_hub", []):
                item["security_hub_enabled"] = True

            # CloudTrail
            for trail in sec.get("cloudtrail_trails", []):
                if trail.get("is_logging"):
                    item["cloudtrail_logging"] = True
                if trail.get("is_multi_region"):
                    item["cloudtrail_multi_region"] = True

            # Config
            for recorder in sec.get("config_recorders", []):
                if recorder.get("recording"):
                    item["config_recording"] = True

        # IAM (global)
        global_data = account.get("global", {})
        iam = global_data.get("iam", {})
        for user in iam.get("iam_users", []):
            if not user.get("mfa_enabled"):
                item["iam_users_without_mfa"] += 1

        # S3 (global)
        s3 = global_data.get("s3", {})
        for bucket in s3.get("s3_buckets", []):
            if bucket.get("is_public"):
                item["public_s3_buckets"] += 1

        security_items.append(item)

    return security_items


def _collect_topologies(scan_data: dict) -> dict:
    """Collect topology data per account-region."""
    topologies = {}
    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)
        for region, region_data in account.get("regions", {}).items():
            topo = region_data.get("topology", {})
            if topo and (topo.get("nodes") or topo.get("edges")):
                key = f"{alias} ({account_id}) — {region}"
                topologies[key] = topo
    return topologies


def generate_report(scan_data: dict, output_path: str) -> str:
    """
    Generate a self-contained HTML report from scan data.

    Args:
        scan_data: Full scan result dict
        output_path: Path for the output HTML file

    Returns:
        Path to the generated report
    """
    console.print("\n[bold]📊 Generating report...[/bold]")

    # Prepare template data
    resources = _flatten_resources(scan_data)
    summary = _build_summary(scan_data)
    security = _build_security_summary(scan_data)
    topologies = _collect_topologies(scan_data)

    # Load and render template
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    template = env.get_template("report.html")

    html = template.render(
        summary=summary,
        resources=resources,
        security=security,
        topologies=topologies,
        resources_json=json.dumps(resources, default=str),
        topologies_json=json.dumps(topologies, default=str),
        security_json=json.dumps(security, default=str),
        summary_json=json.dumps(summary, default=str),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    console.print(f"[bold green]✅ Report generated:[/bold green] {output}")
    console.print(f"[dim]   Open in browser: file://{output.resolve()}[/dim]")

    return str(output)
