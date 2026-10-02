from __future__ import annotations

"""
AWS SSO profile and region configuration reader.

Reads ~/.aws/config to discover SSO profiles and resolves
region lists for scanning.
"""

import configparser
import os
from pathlib import Path
from dataclasses import dataclass, field

from rich.console import Console

console = Console()

# All commercially available AWS regions (as of 2026)
ALL_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "af-south-1",
    "ap-east-1", "ap-south-1", "ap-south-2", "ap-southeast-1",
    "ap-southeast-2", "ap-southeast-3", "ap-southeast-4", "ap-southeast-5",
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ca-central-1", "ca-west-1",
    "eu-central-1", "eu-central-2", "eu-west-1", "eu-west-2", "eu-west-3",
    "eu-south-1", "eu-south-2", "eu-north-1",
    "il-central-1",
    "me-south-1", "me-central-1",
    "sa-east-1",
]

# Global services should only be scanned once (from us-east-1 or first available region)
GLOBAL_SERVICES = {"iam", "s3", "route53", "organizations", "iam_identity_center", "shield", "waf_cloudfront"}


@dataclass
class ProfileConfig:
    """Represents a single AWS SSO profile configuration."""

    profile_name: str
    sso_start_url: str = ""
    sso_region: str = ""
    sso_account_id: str = ""
    sso_role_name: str = ""
    region: str = "us-east-1"


@dataclass
class ScanConfig:
    """Complete scan configuration."""

    profiles: list[ProfileConfig] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    output_dir: str = "./reports"
    max_workers_regions: int = 5
    max_workers_services: int = 10
    verbose: bool = False
    report_title: str = ""


def get_aws_config_path() -> Path:
    """Get the path to ~/.aws/config."""
    return Path(os.environ.get("AWS_CONFIG_FILE", Path.home() / ".aws" / "config"))


def discover_sso_profiles() -> list[ProfileConfig]:
    """
    Read ~/.aws/config and return all profiles that use SSO authentication.
    """
    config_path = get_aws_config_path()
    if not config_path.exists():
        console.print(f"[red]❌ AWS config file not found: {config_path}[/red]")
        return []

    parser = configparser.ConfigParser()
    parser.read(config_path)

    profiles = []
    for section in parser.sections():
        # Sections are named "profile <name>" or "default"
        if section.startswith("profile "):
            profile_name = section.replace("profile ", "", 1)
        elif section == "default":
            profile_name = "default"
        else:
            continue

        section_data = dict(parser[section])

        # Check if this is an SSO profile
        if "sso_start_url" in section_data or "sso_session" in section_data:
            profiles.append(ProfileConfig(
                profile_name=profile_name,
                sso_start_url=section_data.get("sso_start_url", ""),
                sso_region=section_data.get("sso_region", ""),
                sso_account_id=section_data.get("sso_account_id", ""),
                sso_role_name=section_data.get("sso_role_name", ""),
                region=section_data.get("region", "us-east-1"),
            ))

    return profiles


def resolve_profiles(profile_names: str) -> list[ProfileConfig]:
    """
    Resolve profile names to ProfileConfig objects.

    Args:
        profile_names: Comma-separated profile names, or 'all' for all SSO profiles.
    """
    all_profiles = discover_sso_profiles()

    if not all_profiles:
        console.print("[red]❌ No SSO profiles found in ~/.aws/config[/red]")
        console.print("[yellow]💡 Run: aws configure sso[/yellow]")
        return []

    if profile_names.strip().lower() == "all":
        return all_profiles

    requested = [p.strip() for p in profile_names.split(",") if p.strip()]
    available_names = {p.profile_name for p in all_profiles}

    resolved = []
    for name in requested:
        if name in available_names:
            resolved.append(next(p for p in all_profiles if p.profile_name == name))
        else:
            console.print(f"[yellow]⚠️  Profile '{name}' not found. Available: {', '.join(sorted(available_names))}[/yellow]")

    return resolved


def discover_enabled_regions(session) -> list[str]:
    """
    Discover enabled regions dynamically via ec2:DescribeRegions.

    Falls back to the static ALL_REGIONS list if the API call fails.
    """
    try:
        ec2 = session.client("ec2", region_name="us-east-1")
        response = ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
        )
        regions = sorted(r["RegionName"] for r in response.get("Regions", []))
        if regions:
            return regions
    except Exception:
        pass
    return list(ALL_REGIONS)


def resolve_regions(region_input: str, session=None) -> list[str]:
    """
    Resolve region input to a list of region strings.

    Args:
        region_input: Comma-separated region names, or 'all' for all regions.
        session: Optional boto3 session for dynamic region discovery.
    """
    if region_input.strip().lower() == "all":
        if session is not None:
            return discover_enabled_regions(session)
        return ALL_REGIONS

    all_valid = set(ALL_REGIONS)
    regions = [r.strip() for r in region_input.split(",") if r.strip()]
    valid = []
    for r in regions:
        if r in all_valid:
            valid.append(r)
        else:
            console.print(f"[yellow]⚠️  Unknown region '{r}', skipping.[/yellow]")
    return valid


def resolve_services(service_input: str | None) -> list[str] | None:
    """
    Resolve service filter input. Returns None if all services should be scanned.
    """
    if not service_input:
        return None
    return [s.strip().lower() for s in service_input.split(",") if s.strip()]
