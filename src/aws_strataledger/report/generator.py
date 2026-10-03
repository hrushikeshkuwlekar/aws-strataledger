"""
Report generator.

Renders scan data into a self-contained HTML report using Jinja2.

Security notes:
- Jinja2 autoescape is ON (select_autoescape) to prevent XSS via resource names/tags.
- JSON data embedded in <script> tags is escaped with a custom filter to prevent
  script injection (``</script>`` inside a JSON string).
- The template must not use ``|safe`` on user-controlled values.
- _flatten_resources copies dicts so the caller's scan_data is not mutated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from rich.console import Console

from ..diagram import build_diagram_model, compute_layout, render_svg, shared_defs_svg, used_icon_keys

console = Console()

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _script_safe_json(value: object) -> Markup:
    """
    Serialize ``value`` to JSON that is safe to embed in an HTML ``<script>`` tag.

    Escapes ``</`` → ``<\\/`` and ``<!--`` → ``<\\!--`` so that a closing
    ``</script>`` or HTML comment inside a string cannot break out of the script block.
    """
    raw = json.dumps(value, default=str)
    safe = raw.replace("</", r"<\/").replace("<!--", r"<\!--")
    return Markup(safe)


def _flatten_resources(scan_data: dict) -> list[dict]:
    """
    Flatten all resources from all accounts/regions into a single list
    for the inventory table.

    Returns shallow copies — the caller's ``scan_data`` is never mutated.
    """
    resources: list[dict] = []
    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)

        def _add(category: str, category_data: dict) -> None:
            if not isinstance(category_data, dict):
                return
            for resource_type, resource_list in category_data.items():
                if isinstance(resource_type, str) and resource_type.startswith("_"):
                    continue  # metadata key
                if isinstance(resource_list, list):
                    for r in resource_list:
                        row = dict(r)  # shallow copy
                        row["_account_id"] = account_id
                        row["_account_alias"] = alias
                        row["_category"] = category
                        resources.append(row)

        # Global resources
        for category, category_data in account.get("global", {}).items():
            _add(category, category_data)

        # Regional resources
        for _region, region_data in account.get("regions", {}).items():
            for category, category_data in region_data.items():
                if category == "topology":
                    continue
                _add(category, category_data)

    return resources


def _build_summary(scan_data: dict) -> dict:
    """Build summary statistics from scan data."""
    summary: dict = {
        "total_accounts": len(scan_data.get("accounts", {})),
        "total_regions": scan_data.get("scan_metadata", {}).get("regions_scanned", 0),
        "total_resources": scan_data.get("scan_metadata", {}).get("total_resources", 0),
        "scan_time": scan_data.get("scan_metadata", {}).get("scan_timestamp", ""),
        "scan_duration": scan_data.get("scan_metadata", {}).get("scan_duration_seconds", 0),
        "accounts": [],
        "resource_counts_by_type": {},
        "resource_counts_by_category": {},
        "issue_summary": scan_data.get("scan_metadata", {}).get("issue_summary", {}),
    }

    for account_id, account in scan_data.get("accounts", {}).items():
        account_summary: dict = {
            "account_id": account_id,
            "account_alias": account.get("account_alias", account_id),
            "profile_name": account.get("profile_name", ""),
            "regions": list(account.get("regions", {}).keys()),
            "resource_counts": {},
        }

        def count_in(data: dict) -> None:
            for category, category_data in data.items():
                if category == "topology":
                    continue
                if isinstance(category_data, dict):
                    for resource_type, resource_list in category_data.items():
                        if isinstance(resource_type, str) and resource_type.startswith("_"):
                            continue
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

        # Pre-computed metrics for summary table
        rc = account_summary["resource_counts"]
        account_summary["eks_clusters"] = rc.get("eks_clusters", 0)
        account_summary["subnets"] = rc.get("subnets", 0)
        account_summary["network_firewalls"] = rc.get("network_firewalls", 0)
        account_summary["waf_web_acls"] = rc.get("waf_web_acls", 0)
        account_summary["active_firewalls"] = rc.get("network_firewalls", 0)
        account_summary["total_firewalls"] = (
            rc.get("network_firewalls", 0) + rc.get("waf_web_acls", 0)
        )

        summary["accounts"].append(account_summary)

    return summary


def _build_security_summary(scan_data: dict) -> list[dict]:
    """Build per-account security posture summary."""
    security_items: list[dict] = []

    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)
        item: dict = {
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
        for _region, region_data in account.get("regions", {}).items():
            sec = region_data.get("security", {})

            for detector in sec.get("guardduty_detectors", []):
                if detector.get("status") == "ENABLED":
                    item["guardduty_enabled"] = True

            for _hub in sec.get("security_hub", []):
                item["security_hub_enabled"] = True

            for trail in sec.get("cloudtrail_trails", []):
                if trail.get("is_logging"):
                    item["cloudtrail_logging"] = True
                if trail.get("is_multi_region"):
                    item["cloudtrail_multi_region"] = True

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


def _build_diagrams(scan_data: dict) -> tuple[dict[str, Markup], Markup]:
    """
    Build SVG architecture diagrams for each account.

    Returns ({account_label: Markup(svg)}, Markup(shared_defs_svg)). Icons and
    arrow markers are emitted once for the whole page instead of per account.
    SVG is wrapped in Markup so Jinja2 autoescape does not entity-escape it.
    """
    diagrams: dict[str, Markup] = {}
    keys: set[str] = set()
    for account_id, account in scan_data.get("accounts", {}).items():
        alias = account.get("account_alias", account_id)
        try:
            layout = compute_layout(build_diagram_model(account_id, alias, account))
            keys |= used_icon_keys(layout)
            diagrams[f"{alias} ({account_id})"] = Markup(render_svg(layout, embed_defs=False))
        except Exception as e:  # noqa: BLE001 — one bad account must not break the report
            logging.getLogger("aws_strataledger").debug("Diagram build failed for %s", account_id, exc_info=True)
            console.print(f"[yellow]⚠️  Architecture diagram skipped for {alias} ({account_id}): {e}[/yellow]")
    return diagrams, Markup(shared_defs_svg(keys)) if diagrams else Markup("")


def generate_report(scan_data: dict, output_path: str, *, title: str = "") -> str:
    """
    Generate a self-contained HTML report from scan data.

    Args:
        scan_data: Full scan result dict
        output_path: Path for the output HTML file
        title: Optional custom report title

    Returns:
        Path to the generated report
    """
    console.print("\n[bold]📊 Generating report...[/bold]")

    # Prepare template data — does not mutate scan_data
    resources = _flatten_resources(scan_data)
    summary = _build_summary(scan_data)
    security = _build_security_summary(scan_data)
    diagrams, diagram_defs = _build_diagrams(scan_data)

    # Load and render template — autoescape ON for HTML safety
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "htm", "xml"]),
    )
    env.filters["script_safe_json"] = _script_safe_json

    template = env.get_template("report.html")

    html = template.render(
        summary=summary,
        resources=resources,
        security=security,
        diagrams=diagrams,
        diagram_defs=diagram_defs,
        resources_json=_script_safe_json(resources),
        security_json=_script_safe_json(security),
        summary_json=_script_safe_json(summary),
        issues_json=_script_safe_json(
            scan_data.get("scan_metadata", {}).get("issues", [])
        ),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        report_title=title,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    console.print(f"[bold green]✅ Report generated:[/bold green] {output}")
    console.print(f"[dim]   Open in browser: file://{output.resolve()}[/dim]")

    return str(output)
