from __future__ import annotations

"""
Storage & Database collectors.

Covers: S3, EBS, EFS, FSx, RDS/Aurora (incl. DocumentDB/Neptune engines),
        DynamoDB, ElastiCache (incl. Serverless), MemoryDB, OpenSearch,
        Redshift, Backup
"""

from .base import BaseCollector, chunks

PUBLIC_ACL_GRANTEES = (
    "http://acs.amazonaws.com/groups/global/AllUsers",
    "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
)
PAB_FLAGS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")


def _subnet_for_az(subnets: list[dict], az: str | None) -> str | None:
    """Pick the subnet in ``az`` from a DB/cache subnet group's subnet list."""
    for s in subnets:
        if (s.get("SubnetAvailabilityZone") or {}).get("Name") == az:
            return s.get("SubnetIdentifier")
    return None


class StorageCollector(BaseCollector):
    """Collects regional storage and database resources."""

    SERVICE_NAME = "storage"

    def collect(self) -> dict:
        results = {}

        # Block & file
        results["ebs_volumes"] = self._collect_ebs_volumes()
        results["ebs_snapshots"] = self._collect_ebs_snapshots()
        results["efs_file_systems"] = self._collect_efs()
        results["fsx_file_systems"] = self._collect_fsx()

        # Relational
        results["rds_instances"] = self._collect_rds_instances()
        results["rds_clusters"] = self._collect_rds_clusters()
        results["rds_snapshots"] = self._collect_rds_snapshots()

        # NoSQL, caching, search, warehouse
        results["dynamodb_tables"] = self._collect_dynamodb()
        cache_groups, cache_clusters = self._collect_elasticache()
        results["elasticache_replication_groups"] = cache_groups
        results["elasticache_clusters"] = cache_clusters
        results["elasticache_serverless_caches"] = self._collect_elasticache_serverless()
        results["memorydb_clusters"] = self._collect_memorydb()
        results["opensearch_domains"] = self._collect_opensearch()
        results["redshift_clusters"] = self._collect_redshift()

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
        file_systems = self._safe_paginate(efs, "describe_file_systems", "FileSystems")

        def describe(fs: dict) -> dict:
            mount_targets = self._safe_paginate(
                efs, "describe_mount_targets", "MountTargets", FileSystemId=fs["FileSystemId"]
            )
            return {
                "resource_type": "efs_file_system",
                "resource_id": fs.get("FileSystemArn", fs["FileSystemId"]),
                "file_system_id": fs["FileSystemId"],
                "name": fs.get("Name") or self._get_name_tag(fs),
                "size_bytes": fs.get("SizeInBytes", {}).get("Value", 0),
                "performance_mode": fs.get("PerformanceMode"),
                "throughput_mode": fs.get("ThroughputMode"),
                "lifecycle_state": fs.get("LifeCycleState"),
                "encrypted": fs.get("Encrypted", False),
                "number_of_mount_targets": fs.get("NumberOfMountTargets", 0),
                "vpc_id": next((mt.get("VpcId") for mt in mount_targets if mt.get("VpcId")), None),
                "mount_targets": [
                    {
                        "mount_target_id": mt.get("MountTargetId"),
                        "subnet_id": mt.get("SubnetId"),
                        "availability_zone": mt.get("AvailabilityZoneName"),
                        "ip_address": mt.get("IpAddress"),
                        "state": mt.get("LifeCycleState"),
                    }
                    for mt in mount_targets
                ],
                "tags": self._extract_tags(fs),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, file_systems)

    def _collect_fsx(self) -> list[dict]:
        fsx = self._get_client("fsx")
        file_systems = self._safe_paginate(fsx, "describe_file_systems", "FileSystems")
        return [
            {
                "resource_type": "fsx_file_system",
                "resource_id": fs.get("ResourceARN") or fs.get("FileSystemId", ""),
                "file_system_id": fs.get("FileSystemId", ""),
                "name": self._get_name_tag(fs) or fs.get("FileSystemId", ""),
                "file_system_type": fs.get("FileSystemType"),
                "storage_capacity_gb": fs.get("StorageCapacity"),
                "storage_type": fs.get("StorageType"),
                "lifecycle": fs.get("Lifecycle"),
                "vpc_id": fs.get("VpcId"),
                "subnet_ids": fs.get("SubnetIds", []),
                "dns_name": (fs.get("DNSName") or "").lower(),
                "tags": self._extract_tags(fs),
                "region": self.region,
                "account_id": self.account_id,
            }
            for fs in file_systems
        ]

    # ── RDS / Aurora ─────────────────────────────────────────────────

    def _collect_rds_instances(self) -> list[dict]:
        rds = self._get_client("rds")
        instances = self._safe_paginate(rds, "describe_db_instances", "DBInstances")
        results = []
        for db in instances:
            subnet_group = db.get("DBSubnetGroup") or {}
            group_subnets = subnet_group.get("Subnets", [])
            az = db.get("AvailabilityZone")
            results.append({
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
                "vpc_id": subnet_group.get("VpcId"),
                "subnet_group": subnet_group.get("DBSubnetGroupName"),
                "subnet_ids": [s.get("SubnetIdentifier") for s in group_subnets],
                "subnet_id": _subnet_for_az(group_subnets, az),
                "availability_zone": az,
                "secondary_availability_zone": db.get("SecondaryAvailabilityZone"),
                "endpoint": (db.get("Endpoint") or {}).get("Address", ""),
                "port": (db.get("Endpoint") or {}).get("Port"),
                "cluster_identifier": db.get("DBClusterIdentifier"),
                "publicly_accessible": db.get("PubliclyAccessible", False),
                "security_groups": [
                    sg.get("VpcSecurityGroupId") for sg in db.get("VpcSecurityGroups", [])
                ],
                "backup_retention_period": db.get("BackupRetentionPeriod"),
                "create_time": str(db.get("InstanceCreateTime", "")),
                "tags": self._extract_tags(db),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_rds_clusters(self) -> list[dict]:
        rds = self._get_client("rds")
        clusters = self._safe_paginate(rds, "describe_db_clusters", "DBClusters")
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
                "subnet_group": c.get("DBSubnetGroup"),
                "security_groups": [
                    sg.get("VpcSecurityGroupId") for sg in c.get("VpcSecurityGroups", [])
                ],
                "global_cluster_identifier": c.get("GlobalClusterIdentifier"),
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

        def describe(name: str) -> dict | None:
            detail = self._safe_call(
                lambda: ddb.describe_table(TableName=name).get("Table", {}),
                default={},
            )
            if not detail:
                return None
            return {
                "resource_type": "dynamodb_table",
                "resource_id": detail.get("TableArn", name),
                "name": detail.get("TableName", name),
                "status": detail.get("TableStatus"),
                "item_count": detail.get("ItemCount", 0),
                "table_size_bytes": detail.get("TableSizeBytes", 0),
                "billing_mode": (detail.get("BillingModeSummary") or {}).get(
                    "BillingMode", "PROVISIONED"
                ),
                "read_capacity": (detail.get("ProvisionedThroughput") or {}).get("ReadCapacityUnits"),
                "write_capacity": (detail.get("ProvisionedThroughput") or {}).get("WriteCapacityUnits"),
                "gsi_count": len(detail.get("GlobalSecondaryIndexes", [])),
                "lsi_count": len(detail.get("LocalSecondaryIndexes", [])),
                "stream_enabled": (detail.get("StreamSpecification") or {}).get("StreamEnabled", False),
                "encryption": (detail.get("SSEDescription") or {}).get("Status"),
                "global_table_version": detail.get("GlobalTableVersion"),
                "replica_regions": [
                    r.get("RegionName") for r in detail.get("Replicas", []) if r.get("RegionName")
                ],
                # DescribeTable does not return tags; filled by tag enrichment.
                "tags": {},
                "region": self.region,
                "account_id": self.account_id,
            }

        return [t for t in self._parallel(describe, table_names) if t]

    # ── ElastiCache ──────────────────────────────────────────────────

    def _collect_elasticache(self) -> tuple[list[dict], list[dict]]:
        ec = self._get_client("elasticache")
        subnet_groups = {
            g.get("CacheSubnetGroupName"): g
            for g in self._safe_paginate(ec, "describe_cache_subnet_groups", "CacheSubnetGroups")
        }
        raw_clusters = self._safe_paginate(ec, "describe_cache_clusters", "CacheClusters")
        clusters = []
        for c in raw_clusters:
            group = subnet_groups.get(c.get("CacheSubnetGroupName")) or {}
            az = c.get("PreferredAvailabilityZone")
            clusters.append({
                "resource_type": "elasticache_cluster",
                "resource_id": c.get("ARN", c.get("CacheClusterId")),
                "name": c.get("CacheClusterId", ""),
                "engine": c.get("Engine"),
                "engine_version": c.get("EngineVersion"),
                "node_type": c.get("CacheNodeType"),
                "num_nodes": c.get("NumCacheNodes"),
                "status": c.get("CacheClusterStatus"),
                "replication_group_id": c.get("ReplicationGroupId"),
                "availability_zone": az,
                "vpc_id": group.get("VpcId"),
                "subnet_id": _subnet_for_az(group.get("Subnets", []), az),
                "security_groups": [sg.get("SecurityGroupId") for sg in c.get("SecurityGroups", [])],
                "region": self.region,
                "account_id": self.account_id,
            })

        raw_groups = self._safe_paginate(ec, "describe_replication_groups", "ReplicationGroups")
        groups = [
            {
                "resource_type": "elasticache_replication_group",
                "resource_id": g.get("ARN", g.get("ReplicationGroupId")),
                "name": g.get("ReplicationGroupId", ""),
                "description": g.get("Description", ""),
                "status": g.get("Status"),
                "engine": g.get("Engine"),
                "node_type": g.get("CacheNodeType"),
                "cluster_mode": g.get("ClusterEnabled", False),
                "multi_az": g.get("MultiAZ"),
                "automatic_failover": g.get("AutomaticFailover"),
                "member_clusters": g.get("MemberClusters", []),
                "region": self.region,
                "account_id": self.account_id,
            }
            for g in raw_groups
        ]
        return groups, clusters

    def _collect_elasticache_serverless(self) -> list[dict]:
        ec = self._get_client("elasticache")
        caches = self._safe_paginate(ec, "describe_serverless_caches", "ServerlessCaches")
        return [
            {
                "resource_type": "elasticache_serverless_cache",
                "resource_id": c.get("ARN") or c.get("ServerlessCacheName", ""),
                "name": c.get("ServerlessCacheName", ""),
                "engine": c.get("Engine"),
                "engine_version": c.get("FullEngineVersion") or c.get("MajorEngineVersion"),
                "status": c.get("Status"),
                "subnet_ids": c.get("SubnetIds", []),
                "security_groups": c.get("SecurityGroupIds", []),
                "endpoint": ((c.get("Endpoint") or {}).get("Address") or "").lower(),
                "region": self.region,
                "account_id": self.account_id,
            }
            for c in caches
        ]

    def _collect_memorydb(self) -> list[dict]:
        mdb = self._get_client("memorydb")
        clusters = self._safe_paginate(mdb, "describe_clusters", "Clusters")
        if not clusters:
            return []
        subnet_groups = {
            g.get("Name"): g
            for g in self._safe_paginate(mdb, "describe_subnet_groups", "SubnetGroups")
        }
        results = []
        for c in clusters:
            group = subnet_groups.get(c.get("SubnetGroupName")) or {}
            results.append({
                "resource_type": "memorydb_cluster",
                "resource_id": c.get("ARN") or c.get("Name", ""),
                "name": c.get("Name", ""),
                "status": c.get("Status"),
                "engine_version": c.get("EngineVersion"),
                "node_type": c.get("NodeType"),
                "shards": c.get("NumberOfShards"),
                "vpc_id": group.get("VpcId"),
                "subnet_ids": [s.get("Identifier") for s in group.get("Subnets", []) if s.get("Identifier")],
                "endpoint": ((c.get("ClusterEndpoint") or {}).get("Address") or "").lower(),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── OpenSearch ───────────────────────────────────────────────────

    def _collect_opensearch(self) -> list[dict]:
        client = self._get_client("opensearch")
        names = [
            d.get("DomainName") for d in (self._safe_call(
                lambda: client.list_domain_names().get("DomainNames", []), default=[]
            ) or [])
        ]
        results = []
        for batch in chunks(names, 5):
            statuses = self._safe_call(
                lambda b=batch: client.describe_domains(DomainNames=b).get("DomainStatusList", []),
                default=[],
            ) or []
            for d in statuses:
                vpc = d.get("VPCOptions") or {}
                cfg = d.get("ClusterConfig") or {}
                results.append({
                    "resource_type": "opensearch_domain",
                    "resource_id": d.get("ARN", d.get("DomainName")),
                    "name": d.get("DomainName", ""),
                    "engine_version": d.get("EngineVersion"),
                    "instance_type": cfg.get("InstanceType"),
                    "instance_count": cfg.get("InstanceCount"),
                    "zone_awareness": cfg.get("ZoneAwarenessEnabled", False),
                    "status": "processing" if d.get("Processing") else "active",
                    "vpc_id": vpc.get("VPCId"),
                    "subnet_ids": vpc.get("SubnetIds", []),
                    "security_groups": vpc.get("SecurityGroupIds", []),
                    "endpoint": d.get("Endpoint") or (d.get("Endpoints") or {}).get("vpc", ""),
                    "region": self.region,
                    "account_id": self.account_id,
                })
        return results

    # ── Redshift ─────────────────────────────────────────────────────

    def _collect_redshift(self) -> list[dict]:
        rs = self._get_client("redshift")
        clusters = self._safe_paginate(rs, "describe_clusters", "Clusters")
        if not clusters:
            return []
        subnet_groups = {
            g.get("ClusterSubnetGroupName"): g
            for g in self._safe_paginate(rs, "describe_cluster_subnet_groups", "ClusterSubnetGroups")
        }
        results = []
        for c in clusters:
            group = subnet_groups.get(c.get("ClusterSubnetGroupName")) or {}
            az = c.get("AvailabilityZone")
            results.append({
                "resource_type": "redshift_cluster",
                "resource_id": c.get("ClusterNamespaceArn") or c.get("ClusterIdentifier"),
                "name": c.get("ClusterIdentifier", ""),
                "node_type": c.get("NodeType"),
                "number_of_nodes": c.get("NumberOfNodes"),
                "status": c.get("ClusterStatus"),
                "vpc_id": c.get("VpcId"),
                "availability_zone": az,
                "subnet_id": _subnet_for_az(group.get("Subnets", []), az),
                "security_groups": [sg.get("VpcSecurityGroupId") for sg in c.get("VpcSecurityGroups", [])],
                "publicly_accessible": c.get("PubliclyAccessible", False),
                "encrypted": c.get("Encrypted", False),
                "tags": self._extract_tags(c),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── Backup ───────────────────────────────────────────────────────

    def _collect_backup_vaults(self) -> list[dict]:
        backup = self._get_client("backup")
        vaults = self._safe_paginate(backup, "list_backup_vaults", "BackupVaultList")
        return [
            {
                "resource_type": "backup_vault",
                "resource_id": v.get("BackupVaultArn", v["BackupVaultName"]),
                "name": v["BackupVaultName"],
                "recovery_point_count": v.get("NumberOfRecoveryPoints", 0),
                "locked": v.get("Locked", False),
                "encryption_key_arn": v.get("EncryptionKeyArn", ""),
                "creation_date": str(v.get("CreationDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for v in vaults
        ]

    def _collect_backup_plans(self) -> list[dict]:
        backup = self._get_client("backup")
        plans = self._safe_paginate(backup, "list_backup_plans", "BackupPlansList")
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
    S3 Collector — S3 bucket listing is global, so this runs once per account.
    Per-bucket detail calls go to each bucket's own region, in parallel.
    """

    SERVICE_NAME = "s3"

    def collect(self) -> dict:
        account_pab = self._collect_account_public_access_block()
        return {
            "s3_buckets": self._collect_s3_buckets(account_pab),
            "_account_public_access_block": [account_pab] if account_pab else [],
        }

    def _collect_account_public_access_block(self) -> dict:
        s3control = self._get_client("s3control")
        config = self._safe_call(
            lambda: s3control.get_public_access_block(AccountId=self.account_id).get(
                "PublicAccessBlockConfiguration", {}
            ),
            default={},
            ignore=("NoSuchPublicAccessBlockConfiguration",),
        )
        return config or {}

    def _collect_s3_buckets(self, account_pab: dict) -> list[dict]:
        s3 = self._get_client("s3")
        buckets = self._safe_paginate(s3, "list_buckets", "Buckets")

        def describe(bucket: dict) -> dict:
            name = bucket["Name"]
            region = bucket.get("BucketRegion") or self._safe_call(
                lambda: s3.get_bucket_location(Bucket=name).get("LocationConstraint"),
                default="unknown",
            )
            region = {None: "us-east-1", "": "us-east-1", "EU": "eu-west-1"}.get(region, region)
            client = self._get_client("s3", region if region != "unknown" else None)

            encryption = "None"
            enc = self._safe_call(
                lambda: client.get_bucket_encryption(Bucket=name),
                default=None,
                ignore=("ServerSideEncryptionConfigurationNotFoundError",),
            )
            rules = ((enc or {}).get("ServerSideEncryptionConfiguration") or {}).get("Rules", [])
            if rules:
                encryption = rules[0].get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm", "")

            versioning = self._safe_call(
                lambda: client.get_bucket_versioning(Bucket=name).get("Status", "Disabled"),
                default="Unknown",
            )

            bucket_pab = self._safe_call(
                lambda: client.get_public_access_block(Bucket=name).get(
                    "PublicAccessBlockConfiguration", {}
                ),
                default={},
                ignore=("NoSuchPublicAccessBlockConfiguration",),
            ) or {}
            effective_pab = {
                flag: bool(account_pab.get(flag)) or bool(bucket_pab.get(flag)) for flag in PAB_FLAGS
            }

            policy_public = bool(self._safe_call(
                lambda: client.get_bucket_policy_status(Bucket=name).get("PolicyStatus", {}).get("IsPublic", False),
                default=False,
                ignore=("NoSuchBucketPolicy",),
            ))

            grants = self._safe_call(
                lambda: client.get_bucket_acl(Bucket=name).get("Grants", []),
                default=[],
            ) or []
            acl_public = any(
                (g.get("Grantee") or {}).get("URI") in PUBLIC_ACL_GRANTEES for g in grants
            )

            is_public = (
                (policy_public and not effective_pab["RestrictPublicBuckets"])
                or (acl_public and not effective_pab["IgnorePublicAcls"])
            )

            repl = self._safe_call(
                lambda: client.get_bucket_replication(Bucket=name).get(
                    "ReplicationConfiguration", {}
                ).get("Rules", []),
                default=[],
                ignore=("ReplicationConfigurationNotFoundError",),
            ) or []
            replication_rules = [
                {
                    "id": r.get("ID", ""),
                    "status": r.get("Status"),
                    "destination_bucket": (r.get("Destination") or {}).get("Bucket", "").split(":::")[-1],
                    "destination_account": (r.get("Destination") or {}).get("Account"),
                }
                for r in repl
            ]

            return {
                "resource_type": "s3_bucket",
                "resource_id": f"arn:aws:s3:::{name}",
                "name": name,
                "location": region,
                "encryption": encryption,
                "versioning": versioning,
                "is_public": is_public,
                "policy_public": policy_public,
                "acl_public": acl_public,
                "public_access_block": effective_pab,
                "replication_rules": replication_rules,
                "creation_date": str(bucket.get("CreationDate", "")),
                "tags": {},
                "region": region if region != "unknown" else "us-east-1",
                "account_id": self.account_id,
            }

        return self._parallel(describe, buckets)
