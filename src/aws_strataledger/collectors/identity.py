from __future__ import annotations

"""
Identity, Secrets, & Encryption collectors.

Covers: IAM (Users, Roles, Policies, Groups) — global;
        Access Analyzer, KMS, CloudHSM, Secrets Manager,
        SSM Parameter Store, ACM — regional
"""

from collections import defaultdict

from .base import BaseCollector

ACCESS_ANALYZER_FINDINGS_CAP = 1000


class IAMCollector(BaseCollector):
    """
    IAM Collector — global service, scan once per account.
    """

    SERVICE_NAME = "iam"

    def collect(self) -> dict:
        results = {}
        results["iam_users"] = self._collect_users()
        results["iam_roles"] = self._collect_roles()
        results["iam_policies"] = self._collect_policies()
        results["iam_groups"] = self._collect_groups()
        return results

    def _collect_users(self) -> list[dict]:
        iam = self._get_client("iam")
        users = self._safe_paginate(iam, "list_users", "Users")

        def describe(user: dict) -> dict:
            username = user["UserName"]
            mfa_devices = self._safe_paginate(iam, "list_mfa_devices", "MFADevices", UserName=username)
            access_keys = self._safe_paginate(
                iam, "list_access_keys", "AccessKeyMetadata", UserName=username
            )
            attached = self._safe_paginate(
                iam, "list_attached_user_policies", "AttachedPolicies", UserName=username
            )
            groups = self._safe_paginate(iam, "list_groups_for_user", "Groups", UserName=username)
            return {
                "resource_type": "iam_user",
                "resource_id": user.get("Arn", username),
                "name": username,
                "user_id": user.get("UserId"),
                "arn": user.get("Arn"),
                "create_date": str(user.get("CreateDate", "")),
                "password_last_used": str(user.get("PasswordLastUsed", "")),
                "mfa_enabled": len(mfa_devices) > 0,
                "mfa_device_count": len(mfa_devices),
                "access_keys": [
                    {
                        "key_id": k.get("AccessKeyId"),
                        "status": k.get("Status"),
                        "create_date": str(k.get("CreateDate", "")),
                    }
                    for k in access_keys
                ],
                "attached_policies": [p.get("PolicyName") for p in attached],
                "groups": [g.get("GroupName") for g in groups],
                "tags": self._extract_tags(user),
                "region": "global",
                "account_id": self.account_id,
            }

        # IAM has low API rate limits; keep fan-out modest.
        return self._parallel(describe, users, max_workers=4)

    def _collect_roles(self) -> list[dict]:
        iam = self._get_client("iam")
        roles = self._safe_paginate(iam, "list_roles", "Roles")
        return [
            {
                "resource_type": "iam_role",
                "resource_id": r.get("Arn", r["RoleName"]),
                "name": r["RoleName"],
                "role_id": r.get("RoleId"),
                "arn": r.get("Arn"),
                "path": r.get("Path"),
                "create_date": str(r.get("CreateDate", "")),
                "max_session_duration": r.get("MaxSessionDuration"),
                "description": r.get("Description", ""),
                "tags": self._extract_tags(r),
                "region": "global",
                "account_id": self.account_id,
            }
            for r in roles
        ]

    def _collect_policies(self) -> list[dict]:
        iam = self._get_client("iam")
        policies = self._safe_paginate(iam, "list_policies", "Policies", Scope="Local")
        return [
            {
                "resource_type": "iam_policy",
                "resource_id": p.get("Arn", p.get("PolicyName", "")),
                "name": p.get("PolicyName", ""),
                "arn": p.get("Arn"),
                "path": p.get("Path"),
                "attachment_count": p.get("AttachmentCount", 0),
                "is_attachable": p.get("IsAttachable", True),
                "create_date": str(p.get("CreateDate", "")),
                "update_date": str(p.get("UpdateDate", "")),
                "tags": self._extract_tags(p),
                "region": "global",
                "account_id": self.account_id,
            }
            for p in policies
        ]

    def _collect_groups(self) -> list[dict]:
        iam = self._get_client("iam")
        groups = self._safe_paginate(iam, "list_groups", "Groups")
        return [
            {
                "resource_type": "iam_group",
                "resource_id": g.get("Arn", g["GroupName"]),
                "name": g["GroupName"],
                "group_id": g.get("GroupId"),
                "arn": g.get("Arn"),
                "path": g.get("Path"),
                "create_date": str(g.get("CreateDate", "")),
                "region": "global",
                "account_id": self.account_id,
            }
            for g in groups
        ]


class IdentityCollector(BaseCollector):
    """
    Collects Access Analyzer, KMS, CloudHSM, Secrets Manager, SSM Parameter Store,
    and ACM. These are regional services.
    """

    SERVICE_NAME = "identity"

    def collect(self) -> dict:
        results = {}
        results["iam_access_analyzers"] = self._collect_access_analyzers()
        results["kms_keys"] = self._collect_kms_keys()
        results["cloudhsm_clusters"] = self._collect_cloudhsm()
        results["secrets"] = self._collect_secrets()
        results["ssm_parameters"] = self._collect_ssm_parameters()
        results["acm_certificates"] = self._collect_acm_certs()
        results["cognito_user_pools"] = self._collect_cognito()
        return results

    def _collect_cognito(self) -> list[dict]:
        idp = self._get_client("cognito-idp")
        pools = self._safe_paginate(idp, "list_user_pools", "UserPools", MaxResults=60)
        return [
            {
                "resource_type": "cognito_user_pool",
                "resource_id": p.get("Id", ""),
                "name": p.get("Name", ""),
                "status": p.get("Status"),
                "create_time": str(p.get("CreationDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for p in pools
        ]

    def _collect_access_analyzers(self) -> list[dict]:
        aa = self._get_client("accessanalyzer")
        analyzers = self._safe_paginate(aa, "list_analyzers", "analyzers")
        results = []
        for a in analyzers:
            active = self._safe_paginate(
                aa, "list_findings", "findings",
                max_items=ACCESS_ANALYZER_FINDINGS_CAP,
                analyzerArn=a["arn"],
                filter={"status": {"eq": ["ACTIVE"]}},
            )
            results.append({
                "resource_type": "iam_access_analyzer",
                "resource_id": a.get("arn", a.get("name", "")),
                "name": a.get("name", ""),
                "type": a.get("type"),
                "status": a.get("status"),
                "active_findings": len(active),
                "active_findings_capped": len(active) >= ACCESS_ANALYZER_FINDINGS_CAP,
                "created_at": str(a.get("createdAt", "")),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_kms_keys(self) -> list[dict]:
        kms = self._get_client("kms")

        # One ListAliases call per region instead of one per key; aliases under
        # alias/aws/ identify AWS-managed keys, which are skipped without DescribeKey.
        aliases_by_key: dict[str, list[str]] = defaultdict(list)
        aws_managed: set[str] = set()
        for alias in self._safe_paginate(kms, "list_aliases", "Aliases"):
            target = alias.get("TargetKeyId")
            if not target:
                continue
            name = alias.get("AliasName", "")
            aliases_by_key[target].append(name)
            if name.startswith("alias/aws/"):
                aws_managed.add(target)

        keys = [k for k in self._safe_paginate(kms, "list_keys", "Keys") if k["KeyId"] not in aws_managed]

        def describe(key: dict) -> dict | None:
            key_id = key["KeyId"]
            detail = self._safe_call(
                lambda: kms.describe_key(KeyId=key_id).get("KeyMetadata", {}),
                default={},
            )
            if not detail or detail.get("KeyManager") == "AWS":
                return None

            rotation_enabled = None
            if (
                detail.get("KeySpec") == "SYMMETRIC_DEFAULT"
                and detail.get("Origin") == "AWS_KMS"
                and detail.get("KeyState") == "Enabled"
            ):
                rotation_enabled = self._safe_call(
                    lambda: kms.get_key_rotation_status(KeyId=key_id).get("KeyRotationEnabled", False),
                    default=None,
                    ignore=("UnsupportedOperationException",),
                )

            mr = detail.get("MultiRegionConfiguration") or {}
            alias_names = sorted(aliases_by_key.get(key_id, []))
            return {
                "resource_type": "kms_key",
                "resource_id": detail.get("Arn", key_id),
                "name": alias_names[0] if alias_names else key_id,
                "key_id": detail.get("KeyId"),
                "key_state": detail.get("KeyState"),
                "key_manager": detail.get("KeyManager"),
                "key_spec": detail.get("KeySpec"),
                "key_usage": detail.get("KeyUsage"),
                "origin": detail.get("Origin"),
                "creation_date": str(detail.get("CreationDate", "")),
                "description": detail.get("Description", ""),
                "aliases": alias_names,
                "rotation_enabled": rotation_enabled,
                "multi_region": detail.get("MultiRegion", False),
                "multi_region_type": mr.get("MultiRegionKeyType"),
                "primary_region": (mr.get("PrimaryKey") or {}).get("Region"),
                "replica_regions": [r.get("Region") for r in mr.get("ReplicaKeys", [])],
                "region": self.region,
                "account_id": self.account_id,
            }

        return [k for k in self._parallel(describe, keys) if k]

    def _collect_cloudhsm(self) -> list[dict]:
        hsm = self._get_client("cloudhsmv2")
        clusters = self._safe_paginate(hsm, "describe_clusters", "Clusters")
        return [
            {
                "resource_type": "cloudhsm_cluster",
                "resource_id": c.get("ClusterId", ""),
                "name": c.get("ClusterId", ""),
                "state": c.get("State"),
                "hsm_type": c.get("HsmType"),
                "vpc_id": c.get("VpcId"),
                "subnet_mapping": c.get("SubnetMapping", {}),
                "hsm_count": len(c.get("Hsms", [])),
                "security_group": c.get("SecurityGroup"),
                "region": self.region,
                "account_id": self.account_id,
            }
            for c in clusters
        ]

    def _collect_secrets(self) -> list[dict]:
        sm = self._get_client("secretsmanager")
        secrets = self._safe_paginate(sm, "list_secrets", "SecretList")
        return [
            {
                "resource_type": "secret",
                "resource_id": s.get("ARN", s.get("Name", "")),
                "name": s.get("Name", ""),
                "description": s.get("Description", ""),
                "rotation_enabled": s.get("RotationEnabled", False),
                "primary_region": s.get("PrimaryRegion"),
                "last_changed_date": str(s.get("LastChangedDate", "")),
                "last_accessed_date": str(s.get("LastAccessedDate", "")),
                "last_rotated_date": str(s.get("LastRotatedDate", "")),
                "tags": self._extract_tags(s),
                "region": self.region,
                "account_id": self.account_id,
            }
            for s in secrets
        ]

    def _collect_ssm_parameters(self) -> list[dict]:
        ssm = self._get_client("ssm")
        params = self._safe_paginate(ssm, "describe_parameters", "Parameters")
        return [
            {
                "resource_type": "ssm_parameter",
                "resource_id": p.get("ARN") or p.get("Name", ""),
                "name": p.get("Name", ""),
                "type": p.get("Type"),
                "tier": p.get("Tier"),
                "version": p.get("Version"),
                "data_type": p.get("DataType"),
                "last_modified_date": str(p.get("LastModifiedDate", "")),
                "region": self.region,
                "account_id": self.account_id,
            }
            for p in params
        ]

    def _collect_acm_certs(self) -> list[dict]:
        acm = self._get_client("acm")
        certs = self._safe_paginate(acm, "list_certificates", "CertificateSummaryList")

        def describe(cert: dict) -> dict:
            detail = self._safe_call(
                lambda: acm.describe_certificate(
                    CertificateArn=cert["CertificateArn"]
                ).get("Certificate", {}),
                default={},
            ) or cert
            return {
                "resource_type": "acm_certificate",
                "resource_id": detail.get("CertificateArn", cert.get("CertificateArn", "")),
                "name": detail.get("DomainName", cert.get("DomainName", "")),
                "domain_name": detail.get("DomainName", ""),
                "status": detail.get("Status", cert.get("Status", "")),
                "type": detail.get("Type", cert.get("Type", "")),
                "issuer": detail.get("Issuer", ""),
                "not_after": str(detail.get("NotAfter", "")),
                "not_before": str(detail.get("NotBefore", "")),
                "key_algorithm": detail.get("KeyAlgorithm", cert.get("KeyAlgorithm", "")),
                "in_use_by": detail.get("InUseBy", []),
                "subject_alternative_names": detail.get("SubjectAlternativeNames", []),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, certs)
