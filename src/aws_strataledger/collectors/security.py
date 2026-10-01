"""
Security & Compliance collectors.

Covers: GuardDuty, Security Hub, Inspector, Macie, Config,
        CloudTrail, Organizations, Route 53 (global)
"""

from .base import BaseCollector


class SecurityCollector(BaseCollector):
    """Collects security and compliance service configurations."""

    SERVICE_NAME = "security"

    def collect(self) -> dict:
        results = {}
        results["guardduty_detectors"] = self._collect_guardduty()
        results["security_hub"] = self._collect_security_hub()
        results["inspector_coverage"] = self._collect_inspector()
        results["macie_status"] = self._collect_macie()
        results["config_recorders"] = self._collect_config_recorders()
        results["config_rules"] = self._collect_config_rules()
        results["cloudtrail_trails"] = self._collect_cloudtrail()
        return results

    def _collect_guardduty(self) -> list[dict]:
        gd = self._get_client("guardduty")
        detector_ids = self._safe_call(
            lambda: gd.list_detectors().get("DetectorIds", []),
            default=[],
        )
        results = []
        for did in (detector_ids or []):
            detail = self._safe_call(
                lambda d=did: gd.get_detector(DetectorId=d),
                default={},
            )
            if not detail:
                continue

            # Get finding statistics
            finding_stats = self._safe_call(
                lambda d=did: gd.get_findings_statistics(
                    DetectorId=d,
                    FindingStatisticTypes=["COUNT_BY_SEVERITY"],
                ).get("FindingStatistics", {}),
                default={},
            )

            results.append({
                "resource_type": "guardduty_detector",
                "resource_id": did,
                "name": f"GuardDuty-{did[:8]}",
                "status": detail.get("Status"),
                "finding_publishing_frequency": detail.get("FindingPublishingFrequency"),
                "service_role": detail.get("ServiceRole", ""),
                "finding_counts_by_severity": (finding_stats or {}).get(
                    "CountBySeverity", {}
                ),
                "created_at": str(detail.get("CreatedAt", "")),
                "updated_at": str(detail.get("UpdatedAt", "")),
                "tags": detail.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_security_hub(self) -> list[dict]:
        sh = self._get_client("securityhub")
        hub = self._safe_call(
            lambda: sh.describe_hub(),
            default=None,
        )
        if not hub:
            return []

        # Get enabled standards
        standards = self._safe_call(
            lambda: sh.get_enabled_standards().get(
                "StandardsSubscriptions", []
            ),
            default=[],
        )

        return [{
            "resource_type": "security_hub",
            "resource_id": hub.get("HubArn", ""),
            "name": "SecurityHub",
            "hub_arn": hub.get("HubArn", ""),
            "subscribed_at": hub.get("SubscribedAt", ""),
            "auto_enable_controls": hub.get("AutoEnableControls", False),
            "enabled_standards": [
                {
                    "standard_arn": s.get("StandardsArn", ""),
                    "subscription_arn": s.get("StandardsSubscriptionArn", ""),
                    "status": s.get("StandardsStatus", ""),
                }
                for s in (standards or [])
            ],
            "region": self.region,
            "account_id": self.account_id,
        }]

    def _collect_inspector(self) -> list[dict]:
        inspector = self._get_client("inspector2")

        # Get coverage statistics
        coverage = self._safe_call(
            lambda: inspector.list_coverage_statistics(
                filterCriteria={},
                groupBy="RESOURCE_TYPE",
            ).get("countsByGroup", []),
            default=[],
        )

        # Get finding counts by severity
        finding_counts = self._safe_call(
            lambda: inspector.list_finding_aggregations(
                aggregationType="SEVERITY",
            ).get("responses", []),
            default=[],
        )

        if not coverage and not finding_counts:
            return []

        return [{
            "resource_type": "inspector_coverage",
            "resource_id": f"inspector-{self.region}",
            "name": "Inspector",
            "coverage_by_type": [
                {"type": c.get("groupKey"), "count": c.get("count", 0)}
                for c in (coverage or [])
            ],
            "finding_counts_by_severity": [
                {
                    "severity": f.get("severityCounts", {}),
                }
                for f in (finding_counts or [])
            ],
            "region": self.region,
            "account_id": self.account_id,
        }]

    def _collect_macie(self) -> list[dict]:
        macie = self._get_client("macie2")
        session = self._safe_call(
            lambda: macie.get_macie_session(),
            default=None,
        )
        if not session:
            return []

        return [{
            "resource_type": "macie_status",
            "resource_id": f"macie-{self.region}",
            "name": "Macie",
            "status": session.get("status"),
            "finding_publishing_frequency": session.get("findingPublishingFrequency"),
            "service_role": session.get("serviceRole", ""),
            "created_at": str(session.get("createdAt", "")),
            "updated_at": str(session.get("updatedAt", "")),
            "region": self.region,
            "account_id": self.account_id,
        }]

    def _collect_config_recorders(self) -> list[dict]:
        config = self._get_client("config")
        recorders = self._safe_call(
            lambda: config.describe_configuration_recorders().get(
                "ConfigurationRecorders", []
            ),
            default=[],
        )
        # Get recorder status
        statuses = self._safe_call(
            lambda: config.describe_configuration_recorder_status().get(
                "ConfigurationRecordersStatus", []
            ),
            default=[],
        )
        status_map = {s.get("name"): s for s in (statuses or [])}

        # Delivery channels
        channels = self._safe_call(
            lambda: config.describe_delivery_channels().get("DeliveryChannels", []),
            default=[],
        )

        results = []
        for rec in (recorders or []):
            name = rec.get("name", "")
            st = status_map.get(name, {})
            results.append({
                "resource_type": "config_recorder",
                "resource_id": name,
                "name": name,
                "role_arn": rec.get("roleARN", ""),
                "recording": st.get("recording", False),
                "last_status": st.get("lastStatus", ""),
                "all_supported": rec.get("recordingGroup", {}).get(
                    "allSupported", False
                ),
                "include_global": rec.get("recordingGroup", {}).get(
                    "includeGlobalResourceTypes", False
                ),
                "delivery_channels": [
                    {
                        "name": ch.get("name"),
                        "s3_bucket": ch.get("s3BucketName"),
                    }
                    for ch in (channels or [])
                ],
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_config_rules(self) -> list[dict]:
        config = self._get_client("config")
        rules = self._safe_paginate(config, "describe_config_rules", "ConfigRules")
        return [
            {
                "resource_type": "config_rule",
                "resource_id": r.get("ConfigRuleArn", r.get("ConfigRuleName", "")),
                "name": r.get("ConfigRuleName", ""),
                "state": r.get("ConfigRuleState"),
                "source": r.get("Source", {}).get("Owner", ""),
                "source_identifier": r.get("Source", {}).get("SourceIdentifier", ""),
                "description": r.get("Description", ""),
                "region": self.region,
                "account_id": self.account_id,
            }
            for r in rules
        ]

    def _collect_cloudtrail(self) -> list[dict]:
        ct = self._get_client("cloudtrail")
        trails = self._safe_call(
            lambda: ct.describe_trails().get("trailList", []),
            default=[],
        )
        results = []
        for trail in (trails or []):
            # Only collect trails whose home region is this region
            if trail.get("HomeRegion") and trail["HomeRegion"] != self.region:
                continue

            # Get trail status
            status = self._safe_call(
                lambda name=trail["TrailARN"]: ct.get_trail_status(Name=name),
                default={},
            )

            results.append({
                "resource_type": "cloudtrail_trail",
                "resource_id": trail.get("TrailARN", trail.get("Name", "")),
                "name": trail.get("Name", ""),
                "is_multi_region": trail.get("IsMultiRegionTrail", False),
                "is_organization_trail": trail.get("IsOrganizationTrail", False),
                "is_logging": (status or {}).get("IsLogging", False),
                "s3_bucket": trail.get("S3BucketName", ""),
                "log_group": trail.get("CloudWatchLogsLogGroupArn", ""),
                "kms_key_id": trail.get("KmsKeyId", ""),
                "has_custom_event_selectors": trail.get("HasCustomEventSelectors", False),
                "has_insight_selectors": trail.get("HasInsightSelectors", False),
                "home_region": trail.get("HomeRegion", ""),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results


class Route53Collector(BaseCollector):
    """Route 53 Collector — global service, scan once per account."""

    SERVICE_NAME = "route53"

    def collect(self) -> dict:
        results = {}
        results["route53_hosted_zones"] = self._collect_hosted_zones()
        results["route53_health_checks"] = self._collect_health_checks()
        return results

    def _collect_hosted_zones(self) -> list[dict]:
        r53 = self._get_client("route53")
        zones = self._safe_paginate(r53, "list_hosted_zones", "HostedZones")
        results = []
        for zone in zones:
            zone_id = zone["Id"].replace("/hostedzone/", "")

            # Get record count
            record_count = zone.get("ResourceRecordSetCount", 0)

            results.append({
                "resource_type": "route53_hosted_zone",
                "resource_id": zone_id,
                "name": zone.get("Name", ""),
                "is_private": zone.get("Config", {}).get("PrivateZone", False),
                "record_count": record_count,
                "comment": zone.get("Config", {}).get("Comment", ""),
                "region": "global",
                "account_id": self.account_id,
            })
        return results

    def _collect_health_checks(self) -> list[dict]:
        r53 = self._get_client("route53")
        checks = self._safe_paginate(r53, "list_health_checks", "HealthChecks")
        return [
            {
                "resource_type": "route53_health_check",
                "resource_id": hc["Id"],
                "name": hc["Id"],
                "type": hc.get("HealthCheckConfig", {}).get("Type", ""),
                "fqdn": hc.get("HealthCheckConfig", {}).get(
                    "FullyQualifiedDomainName", ""
                ),
                "ip_address": hc.get("HealthCheckConfig", {}).get("IPAddress", ""),
                "port": hc.get("HealthCheckConfig", {}).get("Port"),
                "resource_path": hc.get("HealthCheckConfig", {}).get("ResourcePath", ""),
                "region": "global",
                "account_id": self.account_id,
            }
            for hc in checks
        ]


class OrganizationsCollector(BaseCollector):
    """Organizations Collector — global service, management account only."""

    SERVICE_NAME = "organizations"

    def collect(self) -> dict:
        results = {}
        results["organization"] = self._collect_organization()
        results["organization_accounts"] = self._collect_accounts()
        return results

    def _collect_organization(self) -> list[dict]:
        org = self._get_client("organizations")
        detail = self._safe_call(
            lambda: org.describe_organization().get("Organization", {}),
            default=None,
        )
        if not detail:
            return []
        return [{
            "resource_type": "organization",
            "resource_id": detail.get("Id", ""),
            "name": detail.get("Id", ""),
            "master_account_id": detail.get("MasterAccountId"),
            "master_account_email": detail.get("MasterAccountEmail"),
            "feature_set": detail.get("FeatureSet"),
            "region": "global",
            "account_id": self.account_id,
        }]

    def _collect_accounts(self) -> list[dict]:
        org = self._get_client("organizations")
        accounts = self._safe_paginate(org, "list_accounts", "Accounts")
        return [
            {
                "resource_type": "organization_account",
                "resource_id": a.get("Id", ""),
                "name": a.get("Name", ""),
                "email": a.get("Email", ""),
                "status": a.get("Status"),
                "joined_method": a.get("JoinedMethod"),
                "joined_timestamp": str(a.get("JoinedTimestamp", "")),
                "region": "global",
                "account_id": self.account_id,
            }
            for a in accounts
        ]
