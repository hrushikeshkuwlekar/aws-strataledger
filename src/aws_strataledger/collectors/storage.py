"""
Storage & Database collectors.

Covers: S3, EBS, EFS, RDS/Aurora, DynamoDB, Backup
"""

from .base import BaseCollector


class StorageCollector(BaseCollector):
    """Collects S3, EBS, EFS, RDS/Aurora, DynamoDB, and Backup resources."""

    SERVICE_NAME = "storage"

    def collect(self) -> dict:
        results = {}

        # EBS
        results["ebs_volumes"] = self._collect_ebs_volumes()
        results["ebs_snapshots"] = self._collect_ebs_snapshots()

        # EFS
        results["efs_file_systems"] = self._collect_efs()

        # RDS / Aurora
        results["rds_instances"] = self._collect_rds_instances()
        results["rds_clusters"] = self._collect_rds_clusters()
        results["rds_snapshots"] = self._collect_rds_snapshots()

        # DynamoDB
        results["dynamodb_tables"] = self._collect_dynamodb()

        # Backup
        results["backup_vaults"] = self._collect_backup_vaults()
        results["backup_plans"] = self._collect_backup_plans()

        return results

    # ── EBS ──────────────────────────────────────────────────────────

    def _collect_ebs_volumes(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        volumes = self._safe_paginate(ec2, "describe_volumes", "Volumes")
        return [
            {
                "resource_type": "ebs_volume",
                "resource_id": v["VolumeId"],
                "name": self._get_name_tag(v),
                "size_gb": v.get("Size"),
                "volume_type": v.get("VolumeType"),
                "state": v.get("State"),
                "encrypted": v.get("Encrypted", False),
                "iops": v.get("Iops"),
                "throughput": v.get("Throughput"),
                "availability_zone": v.get("AvailabilityZone"),
                "attachments": [
                    {
                        "instance_id": a.get("InstanceId"),
                        "device": a.get("Device"),
                        "state": a.get("State"),
                    }
                    for a in v.get("Attachments", [])
                ],
                "create_time": str(v.get("CreateTime", "")),
                "snapshot_id": v.get("SnapshotId", ""),
                "tags": self._extract_tags(v),
                "region": self.region,
                "account_id": self.account_id,
            }
            for v in volumes
        ]

    def _collect_ebs_snapshots(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        snapshots = self._safe_paginate(
            ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"]
        )
        return [
            {
                "resource_type": "ebs_snapshot",
                "resource_id": s["SnapshotId"],
                "name": self._get_name_tag(s),
                "volume_id": s.get("VolumeId"),
                "volume_size_gb": s.get("VolumeSize"),
                "state": s.get("State"),
                "encrypted": s.get("Encrypted", False),
                "start_time": str(s.get("StartTime", "")),
                "description": s.get("Description", ""),
                "tags": self._extract_tags(s),
                "region": self.region,
                "account_id": self.account_id,
            }
            for s in snapshots
        ]

    # ── EFS ──────────────────────────────────────────────────────────

    def _collect_efs(self) -> list[dict]:
        efs = self._get_client("efs")
        file_systems = self._safe_paginate(
            efs, "describe_file_systems", "FileSystems"
        )
        results = []
        for fs in file_systems:
            # Get mount targets
            mount_targets = self._safe_call(
                lambda fid=fs["FileSystemId"]: efs.describe_mount_targets(
                    FileSystemId=fid
                ).get("MountTargets", []),
                default=[],
            )
            results.append({
                "resource_type": "efs_file_system",
                "resource_id": fs["FileSystemId"],
                "name": fs.get("Name", self._get_name_tag(fs)),
                "size_bytes": fs.get("SizeInBytes", {}).get("Value", 0),
                "performance_mode": fs.get("PerformanceMode"),
                "throughput_mode": fs.get("ThroughputMode"),
                "lifecycle_state": fs.get("LifeCycleState"),
                "encrypted": fs.get("Encrypted", False),
                "number_of_mount_targets": fs.get("NumberOfMountTargets", 0),
                "mount_targets": [
                    {
                        "mount_target_id": mt.get("MountTargetId"),
                        "subnet_id": mt.get("SubnetId"),
                        "ip_address": mt.get("IpAddress"),
                        "state": mt.get("LifeCycleState"),
                    }
                    for mt in (mount_targets or [])
                ],
                "tags": self._extract_tags(fs),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── RDS / Aurora ─────────────────────────────────────────────────

    def _collect_rds_instances(self) -> list[dict]:
        rds = self._get_client("rds")
        instances = self._safe_paginate(
            rds, "describe_db_instances", "DBInstances"
        )
        return [
            {
                "resource_type": "rds_instance",
                "resource_id": db.get("DBInstanceArn", db["DBInstanceIdentifier"]),
                "name": db["DBInstanceIdentifier"],
                "engine": db.get("Engine"),
                "engine_version": db.get("EngineVersion"),
                "instance_class": db.get("DBInstanceClass"),
                "status": db.get("DBInstanceStatus"),
                "multi_az": db.get("MultiAZ", False),
                "storage_encrypted": db.get("StorageEncrypted", False),
                "storage_type": db.get("StorageType"),
                "allocated_storage_gb": db.get("AllocatedStorage"),
                "vpc_id": (db.get("DBSubnetGroup") or {}).get("VpcId"),
                "subnet_group": (db.get("DBSubnetGroup") or {}).get("DBSubnetGroupName"),
                "availability_zone": db.get("AvailabilityZone"),
                "endpoint": db.get("Endpoint", {}).get("Address", ""),
                "port": db.get("Endpoint", {}).get("Port"),
                "cluster_identifier": db.get("DBClusterIdentifier"),
                "publicly_accessible": db.get("PubliclyAccessible", False),
                "security_groups": [
                    sg.get("VpcSecurityGroupId")
                    for sg in db.get("VpcSecurityGroups", [])
                ],
                "backup_retention_period": db.get("BackupRetentionPeriod"),
                "create_time": str(db.get("InstanceCreateTime", "")),
                "tags": self._extract_tags(db),
                "region": self.region,
                "account_id": self.account_id,
            }
            for db in instances
        ]

    def _collect_rds_clusters(self) -> list[dict]:
        rds = self._get_client("rds")
        clusters = self._safe_paginate(
            rds, "describe_db_clusters", "DBClusters"
        )
        return [
            {
                "resource_type": "rds_cluster",
                "resource_id": c.get("DBClusterArn", c["DBClusterIdentifier"]),
                "name": c["DBClusterIdentifier"],
                "engine": c.get("Engine"),
                "engine_version": c.get("EngineVersion"),
                "engine_mode": c.get("EngineMode"),
                "status": c.get("Status"),
                "multi_az": c.get("MultiAZ", False),
                "storage_encrypted": c.get("StorageEncrypted", False),
                "endpoint": c.get("Endpoint", ""),
                "reader_endpoint": c.get("ReaderEndpoint", ""),
                "port": c.get("Port"),
                "members": [
                    {
                        "instance_id": m.get("DBInstanceIdentifier"),
                        "is_writer": m.get("IsClusterWriter", False),
                    }
                    for m in c.get("DBClusterMembers", [])
                ],
                "availability_zones": c.get("AvailabilityZones", []),
                "backup_retention_period": c.get("BackupRetentionPeriod"),
                "tags": self._extract_tags(c),
                "region": self.region,
                "account_id": self.account_id,
            }
            for c in clusters
        ]

    def _collect_rds_snapshots(self) -> list[dict]:
        rds = self._get_client("rds")
        snapshots = self._safe_paginate(
            rds, "describe_db_snapshots", "DBSnapshots",
            Filters=[{"Name": "snapshot-type", "Values": ["manual", "automated"]}],
        )
        # Limit to most recent 100 snapshots to avoid slow reports
        snapshots = sorted(
            snapshots,
            key=lambda s: str(s.get("SnapshotCreateTime", "")),
            reverse=True,
        )[:100]
        return [
            {
                "resource_type": "rds_snapshot",
                "resource_id": s.get("DBSnapshotArn", s.get("DBSnapshotIdentifier", "")),
                "name": s.get("DBSnapshotIdentifier", ""),
                "db_instance_identifier": s.get("DBInstanceIdentifier", ""),
                "engine": s.get("Engine"),
                "snapshot_type": s.get("SnapshotType"),
                "status": s.get("Status"),
                "encrypted": s.get("Encrypted", False),
                "allocated_storage_gb": s.get("AllocatedStorage"),
                "create_time": str(s.get("SnapshotCreateTime", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for s in snapshots
        ]

    # ── DynamoDB ─────────────────────────────────────────────────────

    def _collect_dynamodb(self) -> list[dict]:
        ddb = self._get_client("dynamodb")
        table_names = self._safe_paginate(ddb, "list_tables", "TableNames")
        results = []
        for name in table_names:
            detail = self._safe_call(
                lambda n=name: ddb.describe_table(TableName=n).get("Table", {}),
                default={},
            )
            if not detail:
                continue
            results.append({
                "resource_type": "dynamodb_table",
                "resource_id": detail.get("TableArn", name),
                "name": detail.get("TableName", name),
                "status": detail.get("TableStatus"),
                "item_count": detail.get("ItemCount", 0),
                "table_size_bytes": detail.get("TableSizeBytes", 0),
                "billing_mode": (detail.get("BillingModeSummary") or {}).get(
                    "BillingMode", "PROVISIONED"
                ),
                "read_capacity": (detail.get("ProvisionedThroughput") or {}).get(
                    "ReadCapacityUnits"
                ),
                "write_capacity": (detail.get("ProvisionedThroughput") or {}).get(
                    "WriteCapacityUnits"
                ),
                "gsi_count": len(detail.get("GlobalSecondaryIndexes", [])),
                "lsi_count": len(detail.get("LocalSecondaryIndexes", [])),
                "stream_enabled": (detail.get("StreamSpecification") or {}).get(
                    "StreamEnabled", False
                ),
                "encryption": (detail.get("SSEDescription") or {}).get("Status"),
                "tags": detail.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── Backup ───────────────────────────────────────────────────────

    def _collect_backup_vaults(self) -> list[dict]:
        backup = self._get_client("backup")
        vaults = self._safe_call(
            lambda: backup.list_backup_vaults().get("BackupVaultList", []),
            default=[],
        )
        results = []
        for v in vaults:
            # Get recovery point count
            rp_count = self._safe_call(
                lambda name=v["BackupVaultName"]: len(
                    backup.list_recovery_points_by_backup_vault(
                        BackupVaultName=name, MaxResults=1
                    ).get("RecoveryPoints", [])
                ),
                default=0,
            )
            results.append({
                "resource_type": "backup_vault",
                "resource_id": v.get("BackupVaultArn", v["BackupVaultName"]),
                "name": v["BackupVaultName"],
                "recovery_point_count": v.get("NumberOfRecoveryPoints", rp_count),
                "encryption_key_arn": v.get("EncryptionKeyArn", ""),
                "creation_date": str(v.get("CreationDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_backup_plans(self) -> list[dict]:
        backup = self._get_client("backup")
        plans = self._safe_call(
            lambda: backup.list_backup_plans().get("BackupPlansList", []),
            default=[],
        )
        return [
            {
                "resource_type": "backup_plan",
                "resource_id": p.get("BackupPlanArn", p.get("BackupPlanId", "")),
                "name": p.get("BackupPlanName", ""),
                "backup_plan_id": p.get("BackupPlanId"),
                "version_id": p.get("VersionId"),
                "creation_date": str(p.get("CreationDate", "")),
                "last_execution_date": str(p.get("LastExecutionDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for p in plans
        ]


class S3Collector(BaseCollector):
    """
    S3 Collector — separate because S3 is a global service.
    Should only be called once per account.
    """

    SERVICE_NAME = "s3"

    def collect(self) -> dict:
        results = {}
        results["s3_buckets"] = self._collect_s3_buckets()
        return results

    def _collect_s3_buckets(self) -> list[dict]:
        s3 = self._get_client("s3")
        buckets = self._safe_call(
            lambda: s3.list_buckets().get("Buckets", []),
            default=[],
        )
        results = []
        for bucket in buckets:
            name = bucket["Name"]

            # Get bucket location
            location = self._safe_call(
                lambda n=name: s3.get_bucket_location(Bucket=n).get(
                    "LocationConstraint"
                ) or "us-east-1",
                default="unknown",
            )

            # Get encryption
            encryption = "None"
            enc_resp = self._safe_call(
                lambda n=name: s3.get_bucket_encryption(Bucket=n),
                default=None,
            )
            if enc_resp:
                rules = enc_resp.get("ServerSideEncryptionConfiguration", {}).get(
                    "Rules", []
                )
                if rules:
                    algo = rules[0].get("ApplyServerSideEncryptionByDefault", {}).get(
                        "SSEAlgorithm", ""
                    )
                    encryption = algo

            # Get versioning
            versioning = self._safe_call(
                lambda n=name: s3.get_bucket_versioning(Bucket=n).get("Status", "Disabled"),
                default="Unknown",
            )

            # Check if public
            is_public = False
            policy_status = self._safe_call(
                lambda n=name: s3.get_bucket_policy_status(Bucket=n).get(
                    "PolicyStatus", {}
                ).get("IsPublic", False),
                default=False,
            )
            if policy_status:
                is_public = True

            # Check replication
            replication_rules = []
            repl = self._safe_call(
                lambda n=name: s3.get_bucket_replication(Bucket=n).get(
                    "ReplicationConfiguration", {}
                ).get("Rules", []),
                default=[],
            )
            if repl:
                replication_rules = [
                    {
                        "id": r.get("ID", ""),
                        "status": r.get("Status"),
                        "destination_bucket": r.get("Destination", {}).get("Bucket", ""),
                    }
                    for r in repl
                ]

            results.append({
                "resource_type": "s3_bucket",
                "resource_id": name,
                "name": name,
                "location": location,
                "encryption": encryption,
                "versioning": versioning,
                "is_public": is_public,
                "replication_rules": replication_rules,
                "creation_date": str(bucket.get("CreationDate", "")),
                "region": location if location != "unknown" else "us-east-1",
                "account_id": self.account_id,
            })
        return results
