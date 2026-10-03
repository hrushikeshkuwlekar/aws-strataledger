from __future__ import annotations

"""
Analytics & streaming collectors.

Covers: Kinesis Data Streams, Data Firehose, Amazon MSK (provisioned +
serverless), EMR (active clusters)
"""

from .base import BaseCollector

EMR_ACTIVE_STATES = ["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING"]

FIREHOSE_DESTINATIONS = {
    "S3DestinationDescription": "S3",
    "ExtendedS3DestinationDescription": "S3",
    "RedshiftDestinationDescription": "Redshift",
    "ElasticsearchDestinationDescription": "OpenSearch",
    "AmazonopensearchserviceDestinationDescription": "OpenSearch",
    "AmazonOpenSearchServerlessDestinationDescription": "OpenSearch Serverless",
    "SplunkDestinationDescription": "Splunk",
    "HttpEndpointDestinationDescription": "HTTP endpoint",
    "SnowflakeDestinationDescription": "Snowflake",
    "IcebergDestinationDescription": "Iceberg",
}


class AnalyticsCollector(BaseCollector):
    """Collects streaming and big-data resources."""

    SERVICE_NAME = "analytics"

    def collect(self) -> dict:
        return {
            "kinesis_streams": self._collect_kinesis(),
            "firehose_streams": self._collect_firehose(),
            "msk_clusters": self._collect_msk(),
            "emr_clusters": self._collect_emr(),
        }

    def _collect_kinesis(self) -> list[dict]:
        kinesis = self._get_client("kinesis")
        names = self._safe_paginate(kinesis, "list_streams", "StreamNames")

        def describe(name: str) -> dict:
            s = self._safe_call(
                lambda: kinesis.describe_stream_summary(StreamName=name).get("StreamDescriptionSummary", {}),
                default={},
            ) or {}
            return {
                "resource_type": "kinesis_stream",
                "resource_id": s.get("StreamARN") or name,
                "name": name,
                "status": s.get("StreamStatus"),
                "mode": (s.get("StreamModeDetails") or {}).get("StreamMode"),
                "open_shards": s.get("OpenShardCount"),
                "retention_hours": s.get("RetentionPeriodHours"),
                "consumers": s.get("ConsumerCount"),
                "encryption": s.get("EncryptionType"),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, names)

    def _collect_firehose(self) -> list[dict]:
        firehose = self._get_client("firehose")
        names: list[str] = []

        def list_page(start: str | None) -> dict:
            kwargs = {"Limit": 100}
            if start:
                kwargs["ExclusiveStartDeliveryStreamName"] = start
            return firehose.list_delivery_streams(**kwargs)

        start = None
        for _ in range(50):
            page = self._safe_call(list_page, start, default=None)
            if not page:
                break
            names.extend(page.get("DeliveryStreamNames", []))
            if not page.get("HasMoreDeliveryStreams") or not names:
                break
            start = names[-1]

        def describe(name: str) -> dict:
            d = self._safe_call(
                lambda: firehose.describe_delivery_stream(DeliveryStreamName=name).get("DeliveryStreamDescription", {}),
                default={},
            ) or {}
            destinations = []
            dest_arns = []
            for dest in d.get("Destinations", []):
                for key, label in FIREHOSE_DESTINATIONS.items():
                    if key in dest:
                        destinations.append(label)
                        if dest[key].get("BucketARN"):
                            dest_arns.append(dest[key]["BucketARN"])
            source = (d.get("Source") or {})
            return {
                "resource_type": "firehose_stream",
                "resource_id": d.get("DeliveryStreamARN") or name,
                "name": name,
                "status": d.get("DeliveryStreamStatus"),
                "source_type": d.get("DeliveryStreamType"),
                "source_stream_arn": (source.get("KinesisStreamSourceDescription") or {}).get("KinesisStreamARN", ""),
                "source_msk_arn": (source.get("MSKSourceDescription") or {}).get("MSKClusterARN", ""),
                "destinations": sorted(set(destinations)),
                "destination_bucket_arns": dest_arns,
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, names)

    def _collect_msk(self) -> list[dict]:
        kafka = self._get_client("kafka")
        clusters = self._safe_paginate(kafka, "list_clusters_v2", "ClusterInfoList")
        results = []
        for c in clusters:
            provisioned = c.get("Provisioned") or {}
            serverless = c.get("Serverless") or {}
            broker_info = provisioned.get("BrokerNodeGroupInfo") or {}
            if provisioned:
                subnet_ids = broker_info.get("ClientSubnets", [])
                security_groups = broker_info.get("SecurityGroups", [])
            else:
                vpc_configs = serverless.get("VpcConfigs", [])
                subnet_ids = [s for v in vpc_configs for s in v.get("SubnetIds", [])]
                security_groups = [s for v in vpc_configs for s in v.get("SecurityGroupIds", [])]
            results.append({
                "resource_type": "msk_cluster",
                "resource_id": c.get("ClusterArn", ""),
                "name": c.get("ClusterName", ""),
                "cluster_type": c.get("ClusterType"),
                "state": c.get("State"),
                "kafka_version": (provisioned.get("CurrentBrokerSoftwareInfo") or {}).get("KafkaVersion"),
                "broker_count": provisioned.get("NumberOfBrokerNodes"),
                "instance_type": broker_info.get("InstanceType"),
                "subnet_ids": subnet_ids,
                "security_groups": security_groups,
                "tags": c.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_emr(self) -> list[dict]:
        emr = self._get_client("emr")
        clusters = self._safe_paginate(emr, "list_clusters", "Clusters", ClusterStates=EMR_ACTIVE_STATES)

        def describe(summary: dict) -> dict:
            c = self._safe_call(
                lambda: emr.describe_cluster(ClusterId=summary["Id"]).get("Cluster", {}), default={},
            ) or {}
            ec2 = c.get("Ec2InstanceAttributes") or {}
            subnets = ec2.get("RequestedEc2SubnetIds") or ([ec2["Ec2SubnetId"]] if ec2.get("Ec2SubnetId") else [])
            return {
                "resource_type": "emr_cluster",
                "resource_id": summary.get("ClusterArn") or summary.get("Id", ""),
                "cluster_id": summary.get("Id", ""),
                "name": summary.get("Name", ""),
                "state": (summary.get("Status") or {}).get("State"),
                "release_label": c.get("ReleaseLabel"),
                "applications": [a.get("Name") for a in c.get("Applications", [])],
                "subnet_ids": subnets,
                "tags": self._extract_tags(c),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, clusters, max_workers=4)
