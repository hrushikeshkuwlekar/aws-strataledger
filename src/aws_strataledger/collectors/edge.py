from __future__ import annotations

"""
Edge / global networking collectors (called once per account).

Covers: CloudFront distributions, Global Accelerator
"""

from .base import BaseCollector

# Global Accelerator's control-plane API only exists in us-west-2.
GLOBAL_ACCELERATOR_REGION = "us-west-2"


class EdgeCollector(BaseCollector):
    """Collects CloudFront and Global Accelerator."""

    SERVICE_NAME = "edge"

    def collect(self) -> dict:
        return {
            "cloudfront_distributions": self._collect_cloudfront(),
            "global_accelerators": self._collect_global_accelerators(),
        }

    def _collect_cloudfront(self) -> list[dict]:
        cf = self._get_client("cloudfront", region="us-east-1")
        dists = self._safe_paginate(cf, "list_distributions", "DistributionList.Items")
        return [
            {
                "resource_type": "cloudfront_distribution",
                "resource_id": d.get("ARN") or d.get("Id", ""),
                "distribution_id": d.get("Id", ""),
                "name": ((d.get("Aliases") or {}).get("Items") or [d.get("DomainName", "")])[0],
                "domain_name": (d.get("DomainName") or "").lower(),
                "aliases": (d.get("Aliases") or {}).get("Items", []),
                "status": d.get("Status"),
                "enabled": d.get("Enabled", False),
                "price_class": d.get("PriceClass"),
                "web_acl_id": d.get("WebACLId", ""),
                "origins": [
                    {"id": o.get("Id"), "domain_name": (o.get("DomainName") or "").lower()}
                    for o in (d.get("Origins") or {}).get("Items", [])
                ],
                "region": "global",
                "account_id": self.account_id,
            }
            for d in dists
        ]

    def _collect_global_accelerators(self) -> list[dict]:
        ga = self._get_client("globalaccelerator", region=GLOBAL_ACCELERATOR_REGION)
        accelerators = self._safe_paginate(ga, "list_accelerators", "Accelerators")
        return [
            {
                "resource_type": "global_accelerator",
                "resource_id": a.get("AcceleratorArn", ""),
                "name": a.get("Name", ""),
                "status": a.get("Status"),
                "enabled": a.get("Enabled", False),
                "dns_name": (a.get("DnsName") or "").lower(),
                "ip_addresses": [ip for s in a.get("IpSets", []) for ip in s.get("IpAddresses", [])],
                "region": "global",
                "account_id": self.account_id,
            }
            for a in accelerators
        ]
