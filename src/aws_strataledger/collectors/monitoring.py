"""
Monitoring & Operational Automation collectors.

Covers: CloudWatch (Alarms, Log Groups), EventBridge, Systems Manager
"""

from .base import BaseCollector


class MonitoringCollector(BaseCollector):
    """Collects CloudWatch, EventBridge, and Systems Manager resources."""

    SERVICE_NAME = "monitoring"

    def collect(self) -> dict:
        results = {}
        results["cloudwatch_alarms"] = self._collect_alarms()
        results["cloudwatch_log_groups"] = self._collect_log_groups()
        results["eventbridge_rules"] = self._collect_eventbridge_rules()
        results["eventbridge_buses"] = self._collect_eventbridge_buses()
        results["ssm_managed_instances"] = self._collect_ssm_instances()
        results["ssm_documents"] = self._collect_ssm_documents()
        return results

    def _collect_alarms(self) -> list[dict]:
        cw = self._get_client("cloudwatch")
        alarms = self._safe_paginate(cw, "describe_alarms", "MetricAlarms")
        composite = self._safe_paginate(cw, "describe_alarms", "CompositeAlarms")
        results = []
        for alarm in alarms:
            results.append({
                "resource_type": "cloudwatch_alarm",
                "resource_id": alarm.get("AlarmArn", alarm.get("AlarmName", "")),
                "name": alarm.get("AlarmName", ""),
                "alarm_type": "metric",
                "state": alarm.get("StateValue"),
                "metric_name": alarm.get("MetricName", ""),
                "namespace": alarm.get("Namespace", ""),
                "statistic": alarm.get("Statistic", ""),
                "threshold": alarm.get("Threshold"),
                "comparison_operator": alarm.get("ComparisonOperator"),
                "evaluation_periods": alarm.get("EvaluationPeriods"),
                "period": alarm.get("Period"),
                "actions_enabled": alarm.get("ActionsEnabled", False),
                "alarm_actions": alarm.get("AlarmActions", []),
                "region": self.region,
                "account_id": self.account_id,
            })
        for alarm in composite:
            results.append({
                "resource_type": "cloudwatch_alarm",
                "resource_id": alarm.get("AlarmArn", alarm.get("AlarmName", "")),
                "name": alarm.get("AlarmName", ""),
                "alarm_type": "composite",
                "state": alarm.get("StateValue"),
                "alarm_rule": alarm.get("AlarmRule", ""),
                "actions_enabled": alarm.get("ActionsEnabled", False),
                "alarm_actions": alarm.get("AlarmActions", []),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_log_groups(self) -> list[dict]:
        logs = self._get_client("logs")
        groups = self._safe_paginate(logs, "describe_log_groups", "logGroups")
        return [
            {
                "resource_type": "cloudwatch_log_group",
                "resource_id": lg.get("arn", lg.get("logGroupName", "")),
                "name": lg.get("logGroupName", ""),
                "retention_days": lg.get("retentionInDays"),
                "stored_bytes": lg.get("storedBytes", 0),
                "kms_key_id": lg.get("kmsKeyId", ""),
                "metric_filter_count": lg.get("metricFilterCount", 0),
                "creation_time": lg.get("creationTime"),
                "region": self.region,
                "account_id": self.account_id,
            }
            for lg in groups
        ]

    def _collect_eventbridge_buses(self) -> list[dict]:
        eb = self._get_client("events")
        buses = self._safe_call(
            lambda: eb.list_event_buses().get("EventBuses", []),
            default=[],
        )
        return [
            {
                "resource_type": "eventbridge_bus",
                "resource_id": bus.get("Arn", bus.get("Name", "")),
                "name": bus.get("Name", ""),
                "arn": bus.get("Arn", ""),
                "policy": "present" if bus.get("Policy") else "none",
                "region": self.region,
                "account_id": self.account_id,
            }
            for bus in (buses or [])
        ]

    def _collect_eventbridge_rules(self) -> list[dict]:
        eb = self._get_client("events")
        rules = self._safe_paginate(eb, "list_rules", "Rules")
        return [
            {
                "resource_type": "eventbridge_rule",
                "resource_id": r.get("Arn", r.get("Name", "")),
                "name": r.get("Name", ""),
                "state": r.get("State"),
                "schedule_expression": r.get("ScheduleExpression", ""),
                "event_bus_name": r.get("EventBusName", "default"),
                "description": r.get("Description", ""),
                "region": self.region,
                "account_id": self.account_id,
            }
            for r in rules
        ]

    def _collect_ssm_instances(self) -> list[dict]:
        ssm = self._get_client("ssm")
        instances = self._safe_paginate(
            ssm, "describe_instance_information", "InstanceInformationList"
        )
        return [
            {
                "resource_type": "ssm_managed_instance",
                "resource_id": i.get("InstanceId", ""),
                "name": i.get("Name", i.get("ComputerName", "")),
                "instance_id": i.get("InstanceId"),
                "ping_status": i.get("PingStatus"),
                "platform_type": i.get("PlatformType"),
                "platform_name": i.get("PlatformName"),
                "platform_version": i.get("PlatformVersion"),
                "agent_version": i.get("AgentVersion"),
                "is_latest_version": i.get("IsLatestVersion", False),
                "last_ping_time": str(i.get("LastPingDateTime", "")),
                "ip_address": i.get("IPAddress", ""),
                "region": self.region,
                "account_id": self.account_id,
            }
            for i in instances
        ]

    def _collect_ssm_documents(self) -> list[dict]:
        ssm = self._get_client("ssm")
        docs = self._safe_paginate(
            ssm, "list_documents", "DocumentIdentifiers",
            Filters=[{"Key": "Owner", "Values": ["Self"]}],
        )
        return [
            {
                "resource_type": "ssm_document",
                "resource_id": d.get("Name", ""),
                "name": d.get("Name", ""),
                "document_type": d.get("DocumentType"),
                "document_format": d.get("DocumentFormat"),
                "schema_version": d.get("SchemaVersion"),
                "platform_types": d.get("PlatformTypes", []),
                "tags": self._extract_tags(d),
                "region": self.region,
                "account_id": self.account_id,
            }
            for d in docs
        ]
