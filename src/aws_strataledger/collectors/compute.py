"""
Compute & Container Platform collectors.

Covers: EC2, Auto Scaling, EKS, ECR, Lambda
"""

from .base import BaseCollector


class ComputeCollector(BaseCollector):
    """Collects EC2, Auto Scaling, EKS, ECR, and Lambda resources."""

    SERVICE_NAME = "compute"

    def collect(self) -> dict:
        results = {}

        # EC2 Instances
        results["ec2_instances"] = self._collect_ec2_instances()
        results["ec2_amis"] = self._collect_ec2_amis()
        results["ec2_key_pairs"] = self._collect_ec2_key_pairs()

        # Auto Scaling
        results["auto_scaling_groups"] = self._collect_asgs()
        results["launch_templates"] = self._collect_launch_templates()

        # EKS
        results["eks_clusters"] = self._collect_eks_clusters()

        # ECR
        results["ecr_repositories"] = self._collect_ecr_repositories()

        # Lambda
        results["lambda_functions"] = self._collect_lambda_functions()
        results["lambda_layers"] = self._collect_lambda_layers()

        return results

    # ── EC2 ──────────────────────────────────────────────────────────

    def _collect_ec2_instances(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        reservations = self._safe_paginate(ec2, "describe_instances", "Reservations")
        instances = []
        for res in reservations:
            for inst in res.get("Instances", []):
                instances.append({
                    "resource_type": "ec2_instance",
                    "resource_id": inst["InstanceId"],
                    "name": self._get_name_tag(inst),
                    "instance_type": inst.get("InstanceType"),
                    "state": inst.get("State", {}).get("Name"),
                    "vpc_id": inst.get("VpcId"),
                    "subnet_id": inst.get("SubnetId"),
                    "private_ip": inst.get("PrivateIpAddress"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "security_groups": [
                        {"id": sg["GroupId"], "name": sg.get("GroupName", "")}
                        for sg in inst.get("SecurityGroups", [])
                    ],
                    "iam_profile": (inst.get("IamInstanceProfile") or {}).get("Arn", ""),
                    "platform": inst.get("PlatformDetails", inst.get("Platform", "Linux")),
                    "launch_time": str(inst.get("LaunchTime", "")),
                    "architecture": inst.get("Architecture"),
                    "ebs_volumes": [
                        {
                            "device": bdm.get("DeviceName"),
                            "volume_id": bdm.get("Ebs", {}).get("VolumeId"),
                            "status": bdm.get("Ebs", {}).get("Status"),
                        }
                        for bdm in inst.get("BlockDeviceMappings", [])
                        if "Ebs" in bdm
                    ],
                    "tags": self._extract_tags(inst),
                    "region": self.region,
                    "account_id": self.account_id,
                })
        return instances

    def _collect_ec2_amis(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        images = self._safe_call(
            lambda: ec2.describe_images(Owners=["self"]).get("Images", []),
            default=[],
        )
        return [
            {
                "resource_type": "ec2_ami",
                "resource_id": img["ImageId"],
                "name": img.get("Name", ""),
                "state": img.get("State"),
                "creation_date": img.get("CreationDate", ""),
                "architecture": img.get("Architecture"),
                "platform": img.get("PlatformDetails", ""),
                "tags": self._extract_tags(img),
                "region": self.region,
                "account_id": self.account_id,
            }
            for img in images
        ]

    def _collect_ec2_key_pairs(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        key_pairs = self._safe_call(
            lambda: ec2.describe_key_pairs().get("KeyPairs", []),
            default=[],
        )
        return [
            {
                "resource_type": "ec2_key_pair",
                "resource_id": kp.get("KeyPairId", kp.get("KeyName")),
                "name": kp.get("KeyName", ""),
                "key_type": kp.get("KeyType", ""),
                "create_time": str(kp.get("CreateTime", "")),
                "tags": self._extract_tags(kp),
                "region": self.region,
                "account_id": self.account_id,
            }
            for kp in key_pairs
        ]

    # ── Auto Scaling ─────────────────────────────────────────────────

    def _collect_asgs(self) -> list[dict]:
        autoscaling = self._get_client("autoscaling")
        asgs = self._safe_paginate(
            autoscaling, "describe_auto_scaling_groups", "AutoScalingGroups"
        )
        return [
            {
                "resource_type": "auto_scaling_group",
                "resource_id": asg["AutoScalingGroupName"],
                "name": asg["AutoScalingGroupName"],
                "min_size": asg.get("MinSize"),
                "max_size": asg.get("MaxSize"),
                "desired_capacity": asg.get("DesiredCapacity"),
                "instances": [
                    {"id": i["InstanceId"], "state": i.get("LifecycleState")}
                    for i in asg.get("Instances", [])
                ],
                "launch_template": asg.get("LaunchTemplate", {}),
                "target_group_arns": asg.get("TargetGroupARNs", []),
                "availability_zones": asg.get("AvailabilityZones", []),
                "vpc_zone_identifier": asg.get("VPCZoneIdentifier", ""),
                "tags": {t["Key"]: t["Value"] for t in asg.get("Tags", [])},
                "region": self.region,
                "account_id": self.account_id,
            }
            for asg in asgs
        ]

    def _collect_launch_templates(self) -> list[dict]:
        ec2 = self._get_client("ec2")
        templates = self._safe_paginate(
            ec2, "describe_launch_templates", "LaunchTemplates"
        )
        return [
            {
                "resource_type": "launch_template",
                "resource_id": lt["LaunchTemplateId"],
                "name": lt.get("LaunchTemplateName", ""),
                "default_version": lt.get("DefaultVersionNumber"),
                "latest_version": lt.get("LatestVersionNumber"),
                "create_time": str(lt.get("CreateTime", "")),
                "tags": self._extract_tags(lt),
                "region": self.region,
                "account_id": self.account_id,
            }
            for lt in templates
        ]

    # ── EKS ──────────────────────────────────────────────────────────

    def _collect_eks_clusters(self) -> list[dict]:
        eks = self._get_client("eks")
        cluster_names = self._safe_call(
            lambda: eks.list_clusters().get("clusters", []),
            default=[],
        )
        clusters = []
        for name in cluster_names:
            detail = self._safe_call(
                lambda n=name: eks.describe_cluster(name=n).get("cluster", {}),
                default={},
            )
            if not detail:
                continue

            # Get node groups
            nodegroups = self._safe_call(
                lambda n=name: eks.list_nodegroups(clusterName=n).get("nodegroups", []),
                default=[],
            )
            ng_details = []
            for ng_name in (nodegroups or []):
                ng = self._safe_call(
                    lambda c=name, n=ng_name: eks.describe_nodegroup(
                        clusterName=c, nodegroupName=n
                    ).get("nodegroup", {}),
                    default={},
                )
                if ng:
                    ng_details.append({
                        "name": ng.get("nodegroupName"),
                        "status": ng.get("status"),
                        "instance_types": ng.get("instanceTypes", []),
                        "scaling": ng.get("scalingConfig", {}),
                        "capacity_type": ng.get("capacityType"),
                    })

            # Get fargate profiles
            fargate_profiles = self._safe_call(
                lambda n=name: eks.list_fargate_profiles(clusterName=n).get(
                    "fargateProfileNames", []
                ),
                default=[],
            )

            vpc_config = detail.get("resourcesVpcConfig", {})
            clusters.append({
                "resource_type": "eks_cluster",
                "resource_id": detail.get("arn", name),
                "name": detail.get("name", name),
                "status": detail.get("status"),
                "version": detail.get("version"),
                "endpoint": detail.get("endpoint", ""),
                "vpc_id": vpc_config.get("vpcId"),
                "subnet_ids": vpc_config.get("subnetIds", []),
                "security_group_ids": vpc_config.get("securityGroupIds", []),
                "node_groups": ng_details,
                "fargate_profile_count": len(fargate_profiles or []),
                "tags": detail.get("tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            })
        return clusters

    # ── ECR ──────────────────────────────────────────────────────────

    def _collect_ecr_repositories(self) -> list[dict]:
        ecr = self._get_client("ecr")
        repos = self._safe_paginate(ecr, "describe_repositories", "repositories")
        results = []
        for repo in repos:
            # Get image count
            image_count = 0
            images = self._safe_call(
                lambda r=repo["repositoryName"]: ecr.list_images(
                    repositoryName=r, filter={"tagStatus": "ANY"}
                ).get("imageIds", []),
                default=[],
            )
            if images:
                image_count = len(images)

            results.append({
                "resource_type": "ecr_repository",
                "resource_id": repo.get("repositoryArn", repo["repositoryName"]),
                "name": repo["repositoryName"],
                "uri": repo.get("repositoryUri", ""),
                "image_count": image_count,
                "scan_on_push": repo.get("imageScanningConfiguration", {}).get(
                    "scanOnPush", False
                ),
                "encryption": repo.get("encryptionConfiguration", {}),
                "image_tag_mutability": repo.get("imageTagMutability"),
                "created_at": str(repo.get("createdAt", "")),
                "region": self.region,
                "account_id": self.account_id,
            })
        return results

    # ── Lambda ───────────────────────────────────────────────────────

    def _collect_lambda_functions(self) -> list[dict]:
        lam = self._get_client("lambda")
        functions = self._safe_paginate(lam, "list_functions", "Functions")
        return [
            {
                "resource_type": "lambda_function",
                "resource_id": fn["FunctionArn"],
                "name": fn["FunctionName"],
                "runtime": fn.get("Runtime", ""),
                "handler": fn.get("Handler", ""),
                "memory_size": fn.get("MemorySize"),
                "timeout": fn.get("Timeout"),
                "code_size": fn.get("CodeSize"),
                "last_modified": fn.get("LastModified", ""),
                "vpc_config": fn.get("VpcConfig", {}),
                "layers": [l.get("Arn", "") for l in fn.get("Layers", [])],
                "architectures": fn.get("Architectures", []),
                "package_type": fn.get("PackageType"),
                "tags": fn.get("Tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            }
            for fn in functions
        ]

    def _collect_lambda_layers(self) -> list[dict]:
        lam = self._get_client("lambda")
        layers = self._safe_paginate(lam, "list_layers", "Layers")
        return [
            {
                "resource_type": "lambda_layer",
                "resource_id": layer.get("LayerArn", ""),
                "name": layer.get("LayerName", ""),
                "latest_version": layer.get("LatestMatchingVersion", {}).get(
                    "Version"
                ),
                "runtimes": layer.get("LatestMatchingVersion", {}).get(
                    "CompatibleRuntimes", []
                ),
                "region": self.region,
                "account_id": self.account_id,
            }
            for layer in layers
        ]
