"""
Identity, Secrets, & Encryption collectors.

Covers: IAM (Users, Roles, Policies, Groups, Access Analyzer),
        IAM Identity Center, KMS, CloudHSM, Secrets Manager,
        SSM Parameter Store, ACM
"""

from .base import BaseCollector


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
        results["iam_access_analyzers"] = self._collect_access_analyzers()
        return results

    def _collect_users(self) -> list[dict]:
        iam = self._get_client("iam")
        users = self._safe_paginate(iam, "list_users", "Users")
        results = []
        for user in users:
            username = user["UserName"]

            # MFA devices
            mfa_devices = self._safe_call(
                lambda u=username: iam.list_mfa_devices(UserName=u).get(
                    "MFADevices", []
                ),
                default=[],
            )

            # Access keys
            access_keys = self._safe_call(
                lambda u=username: iam.list_access_keys(UserName=u).get(
                    "AccessKeyMetadata", []
                ),
                default=[],
            )

            # Attached policies
            attached = self._safe_call(
                lambda u=username: iam.list_attached_user_policies(UserName=u).get(
                    "AttachedPolicies", []
                ),
                default=[],
            )

            # Groups
            groups = self._safe_call(
                lambda u=username: iam.list_groups_for_user(UserName=u).get(
                    "Groups", []
                ),
                default=[],
            )

            results.append({
                "resource_type": "iam_user",
                "resource_id": user.get("Arn", username),
                "name": username,
                "user_id": user.get("UserId"),
                "arn": user.get("Arn"),
                "create_date": str(user.get("CreateDate", "")),
                "password_last_used": str(user.get("PasswordLastUsed", "")),
                "mfa_enabled": len(mfa_devices or []) > 0,
                "mfa_device_count": len(mfa_devices or []),
                "access_keys": [
                    {
                        "key_id": k.get("AccessKeyId"),
                        "status": k.get("Status"),
                        "create_date": str(k.get("CreateDate", "")),
                    }
                    for k in (access_keys or [])
                ],
                "attached_policies": [
                    p.get("PolicyName") for p in (attached or [])
                ],
                "groups": [g.get("GroupName") for g in (groups or [])],
                "tags": self._extract_tags(user),
                "region": "global",
                "account_id": self.account_id,
            })
        return results

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
        policies = self._safe_paginate(
            iam, "list_policies", "Policies", Scope="Local"
        )
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

    def _collect_access_analyzers(self) -> list[dict]:
        aa = self._get_client("accessanalyzer")
        analyzers = self._safe_call(
            lambda: aa.list_analyzers().get("analyzers", []),
            default=[],
        )
        results = []
        for a in (analyzers or []):
            # Get finding counts
            finding_counts = {}
            for status in ["ACTIVE", "ARCHIVED", "RESOLVED"]:
                count = self._safe_call(
                    lambda arn=a["arn"], s=status: len(
                        aa.list_findings(
                            analyzerArn=arn,
                            filter={"status": {"eq": [s]}},
                            maxResults=1,
                        ).get("findings", [])
                    ),
                    default=0,
                )
                finding_counts[status.lower()] = count

            results.append({
                "resource_type": "iam_access_analyzer",
                "resource_id": a.get("arn", a.get("name", "")),
                "name": a.get("name", ""),
                "type": a.get("type"),
                "status": a.get("status"),
                "finding_counts": finding_counts,
                "created_at": str(a.get("createdAt", "")),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results


class IdentityCollector(BaseCollector):
    """
    Collects KMS, CloudHSM, Secrets Manager, SSM Parameter Store, and ACM.
    These are regional services.
    """

    SERVICE_NAME = "identity"

    def collect(self) -> dict:
        results = {}
        results["kms_keys"] = self._collect_kms_keys()
        results["cloudhsm_clusters"] = self._collect_cloudhsm()
        results["secrets"] = self._collect_secrets()
        results["ssm_parameters"] = self._collect_ssm_parameters()
        results["acm_certificates"] = self._collect_acm_certs()
        return results

    def _collect_kms_keys(self) -> list[dict]:
        kms = self._get_client("kms")
        keys = self._safe_paginate(kms, "list_keys", "Keys")
        results = []
        for key in keys:
            detail = self._safe_call(
                lambda kid=key["KeyId"]: kms.describe_key(KeyId=kid).get(
                    "KeyMetadata", {}
                ),
                default={},
            )
            if not detail:
                continue
            # Only include customer-managed keys
            if detail.get("KeyManager") == "AWS":
                continue

            # Get aliases
            aliases = self._safe_call(
                lambda kid=key["KeyId"]: kms.list_aliases(KeyId=kid).get(
                    "Aliases", []
                ),
                default=[],
            )
            alias_names = [a.get("AliasName", "") for a in (aliases or [])]

            results.append({
                "resource_type": "kms_key",
                "resource_id": detail.get("Arn", key["KeyId"]),
                "name": alias_names[0] if alias_names else key["KeyId"],
                "key_id": detail.get("KeyId"),
                "key_state": detail.get("KeyState"),
                "key_manager": detail.get("KeyManager"),
                "key_spec": detail.get("KeySpec"),
                "key_usage": detail.get("KeyUsage"),
                "creation_date": str(detail.get("CreationDate", "")),
                "description": detail.get("Description", ""),
                "aliases": alias_names,
                "rotation_enabled": detail.get("RotationEnabled", False) if detail.get("KeyManager") == "CUSTOMER" else None,
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    def _collect_cloudhsm(self) -> list[dict]:
        hsm = self._get_client("cloudhsmv2")
        clusters = self._safe_call(
            lambda: hsm.describe_clusters().get("Clusters", []),
            default=[],
        )
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
            for c in (clusters or [])
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
                "resource_id": p.get("Name", ""),
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
        certs = self._safe_paginate(
            acm, "list_certificates", "CertificateSummaryList"
        )
        results = []
        for cert in certs:
            detail = self._safe_call(
                lambda arn=cert["CertificateArn"]: acm.describe_certificate(
                    CertificateArn=arn
                ).get("Certificate", {}),
                default={},
            )
            if not detail:
                detail = cert
            results.append({
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
            })
        return results
