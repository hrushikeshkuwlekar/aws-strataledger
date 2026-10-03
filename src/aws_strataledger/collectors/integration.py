from __future__ import annotations

"""
Application Integration collectors.

Covers: SQS, SNS (with subscriptions), Step Functions, Amazon MQ
"""

import json

from .base import BaseCollector

MAX_SNS_SUBSCRIPTIONS = 50


class IntegrationCollector(BaseCollector):
    """Collects queues, topics, state machines and message brokers."""

    SERVICE_NAME = "integration"

    def collect(self) -> dict:
        return {
            "sqs_queues": self._collect_sqs(),
            "sns_topics": self._collect_sns(),
            "step_functions": self._collect_step_functions(),
            "mq_brokers": self._collect_mq(),
        }

    def _collect_sqs(self) -> list[dict]:
        sqs = self._get_client("sqs")
        urls = self._safe_paginate(sqs, "list_queues", "QueueUrls")

        def describe(url: str) -> dict:
            attrs = self._safe_call(
                lambda: sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"]).get("Attributes", {}),
                default={},
            ) or {}
            redrive = {}
            if attrs.get("RedrivePolicy"):
                try:
                    redrive = json.loads(attrs["RedrivePolicy"])
                except ValueError:
                    redrive = {}
            return {
                "resource_type": "sqs_queue",
                "resource_id": attrs.get("QueueArn") or url,
                "name": url.rsplit("/", 1)[-1],
                "url": url,
                "fifo": attrs.get("FifoQueue") == "true",
                "approximate_messages": int(attrs.get("ApproximateNumberOfMessages", 0) or 0),
                "visibility_timeout": attrs.get("VisibilityTimeout"),
                "encrypted": bool(attrs.get("KmsMasterKeyId") or attrs.get("SqsManagedSseEnabled") == "true"),
                "dead_letter_target_arn": redrive.get("deadLetterTargetArn", ""),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, urls)

    def _collect_sns(self) -> list[dict]:
        sns = self._get_client("sns")
        topics = self._safe_paginate(sns, "list_topics", "Topics")

        def describe(topic: dict) -> dict:
            arn = topic.get("TopicArn", "")
            subs = self._safe_paginate(
                sns, "list_subscriptions_by_topic", "Subscriptions",
                max_items=MAX_SNS_SUBSCRIPTIONS, TopicArn=arn,
            )
            return {
                "resource_type": "sns_topic",
                "resource_id": arn,
                "name": arn.rsplit(":", 1)[-1],
                "fifo": arn.endswith(".fifo"),
                "subscriptions": [
                    {"protocol": s.get("Protocol"), "endpoint": s.get("Endpoint")} for s in subs
                ],
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, topics)

    def _collect_step_functions(self) -> list[dict]:
        sfn = self._get_client("stepfunctions")
        machines = self._safe_paginate(sfn, "list_state_machines", "stateMachines")
        return [
            {
                "resource_type": "step_function",
                "resource_id": m.get("stateMachineArn", ""),
                "name": m.get("name", ""),
                "type": m.get("type"),
                "create_time": str(m.get("creationDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for m in machines
        ]

    def _collect_mq(self) -> list[dict]:
        mq = self._get_client("mq")
        brokers = self._safe_paginate(mq, "list_brokers", "BrokerSummaries")

        def describe(summary: dict) -> dict:
            detail = self._safe_call(
                lambda: mq.describe_broker(BrokerId=summary["BrokerId"]), default={},
            ) or {}
            return {
                "resource_type": "mq_broker",
                "resource_id": summary.get("BrokerArn") or summary.get("BrokerId", ""),
                "name": summary.get("BrokerName", ""),
                "engine": summary.get("EngineType") or detail.get("EngineType"),
                "engine_version": detail.get("EngineVersion"),
                "deployment_mode": summary.get("DeploymentMode") or detail.get("DeploymentMode"),
                "instance_type": summary.get("HostInstanceType") or detail.get("HostInstanceType"),
                "state": summary.get("BrokerState"),
                "publicly_accessible": detail.get("PubliclyAccessible", False),
                "subnet_ids": detail.get("SubnetIds", []),
                "security_groups": detail.get("SecurityGroups", []),
                "tags": detail.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, brokers)
