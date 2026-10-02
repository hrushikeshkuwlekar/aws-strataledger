from __future__ import annotations

"""
Compute & Container Platform collectors.

Covers: EC2, Auto Scaling, EKS, ECS, ECR, Lambda
"""

from .base import BaseCollector, chunks

ECR_IMAGE_COUNT_CAP = 1000


class ComputeCollector(BaseCollector):
    """Collects EC2, Auto Scaling, EKS, ECS, ECR, and Lambda resources."""

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

        # Containers
        results["eks_clusters"] = self._collect_eks_clusters()
        ecs_clusters, ecs_services = self._collect_ecs()
        results["ecs_clusters"] = ecs_clusters
        results["ecs_services"] = ecs_services

        # ECR
        results["ecr_repositories"] = self._collect_ecr_repositories()
        results["_ecr_replication"] = self._collect_ecr_replication()

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
                    "lifecycle": inst.get("InstanceLifecycle", "on-demand"),
                    "availability_zone": (inst.get("Placement") or {}).get("AvailabilityZone"),
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
        images = self._safe_paginate(ec2, "describe_images", "Images", Owners=["self"])
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
            for kp in (key_pairs or [])
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
                "resource_id": asg.get("AutoScalingGroupARN", asg["AutoScalingGroupName"]),
                "name": asg["AutoScalingGroupName"],
                "min_size": asg.get("MinSize"),
                "max_size": asg.get("MaxSize"),
                "desired_capacity": asg.get("DesiredCapacity"),
                "instances": [
                    {
                        "id": i["InstanceId"],
                        "state": i.get("LifecycleState"),
                        "availability_zone": i.get("AvailabilityZone"),
                    }
                    for i in asg.get("Instances", [])
                ],
                "launch_template": asg.get("LaunchTemplate", {}),
                "target_group_arns": asg.get("TargetGroupARNs", []),
                "load_balancer_names": asg.get("LoadBalancerNames", []),
                "availability_zones": asg.get("AvailabilityZones", []),
                "vpc_zone_identifier": asg.get("VPCZoneIdentifier", ""),
                "subnet_ids": [s for s in (asg.get("VPCZoneIdentifier") or "").split(",") if s],
                "tags": self._extract_tags(asg),
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
        cluster_names = self._safe_paginate(eks, "list_clusters", "clusters")

        def describe(name: str) -> dict | None:
            detail = self._safe_call(
                lambda: eks.describe_cluster(name=name).get("cluster", {}),
                default={},
            )
            if not detail:
                return None

            nodegroups = self._safe_paginate(eks, "list_nodegroups", "nodegroups", clusterName=name)
            ng_details = []
            for ng_name in nodegroups:
                ng = self._safe_call(
                    lambda n=ng_name: eks.describe_nodegroup(
                        clusterName=name, nodegroupName=n
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
                        "subnet_ids": ng.get("subnets", []),
                    })

            fargate_profiles = self._safe_paginate(
                eks, "list_fargate_profiles", "fargateProfileNames", clusterName=name
            )

            vpc_config = detail.get("resourcesVpcConfig", {})
            return {
                "resource_type": "eks_cluster",
                "resource_id": detail.get("arn", name),
                "name": detail.get("name", name),
                "status": detail.get("status"),
                "version": detail.get("version"),
                "endpoint": detail.get("endpoint", ""),
                "endpoint_public_access": vpc_config.get("endpointPublicAccess"),
                "vpc_id": vpc_config.get("vpcId"),
                "subnet_ids": vpc_config.get("subnetIds", []),
                "security_group_ids": vpc_config.get("securityGroupIds", []),
                "cluster_security_group_id": vpc_config.get("clusterSecurityGroupId"),
                "node_groups": ng_details,
                "fargate_profile_count": len(fargate_profiles),
                "tags": detail.get("tags", {}),
                "region": self.region,
                "account_id": self.account_id,
            }

        return [c for c in self._parallel(describe, cluster_names, max_workers=4) if c]

    # ── ECS ──────────────────────────────────────────────────────────

    def _collect_ecs(self) -> tuple[list[dict], list[dict]]:
        ecs = self._get_client("ecs")
        cluster_arns = self._safe_paginate(ecs, "list_clusters", "clusterArns")
        clusters: list[dict] = []
        services: list[dict] = []

        raw_clusters = []
        for batch in chunks(cluster_arns, 100):
            raw_clusters.extend(self._safe_call(
                lambda b=batch: ecs.describe_clusters(clusters=b, include=["TAGS"]).get("clusters", []),
                default=[],
            ) or [])

        for c in raw_clusters:
            cluster_arn = c.get("clusterArn", "")
            cluster_name = c.get("clusterName", "")
            clusters.append({
                "resource_type": "ecs_cluster",
                "resource_id": cluster_arn,
                "name": cluster_name,
                "status": c.get("status"),
                "active_services": c.get("activeServicesCount", 0),
                "running_tasks": c.get("runningTasksCount", 0),
                "container_instances": c.get("registeredContainerInstancesCount", 0),
                "capacity_providers": c.get("capacityProviders", []),
                "tags": self._extract_tags(c),
                "region": self.region,
                "account_id": self.account_id,
            })

            service_arns = self._safe_paginate(ecs, "list_services", "serviceArns", cluster=cluster_arn)
            for batch in chunks(service_arns, 10):
                described = self._safe_call(
                    lambda b=batch: ecs.describe_services(
                        cluster=cluster_arn, services=b, include=["TAGS"]
                    ).get("services", []),
                    default=[],
                ) or []
                for s in described:
                    awsvpc = (s.get("networkConfiguration") or {}).get("awsvpcConfiguration") or {}
                    strategy = s.get("capacityProviderStrategy") or []
                    launch_type = s.get("launchType") or (
                        strategy[0].get("capacityProvider") if strategy else ""
                    )
                    services.append({
                        "resource_type": "ecs_service",
                        "resource_id": s.get("serviceArn", ""),
                        "name": s.get("serviceName", ""),
                        "cluster": cluster_name,
                        "cluster_arn": cluster_arn,
                        "status": s.get("status"),
                        "launch_type": launch_type,
                        "desired_count": s.get("desiredCount", 0),
                        "running_count": s.get("runningCount", 0),
                        "task_definition": (s.get("taskDefinition") or "").split("/")[-1],
                        "subnet_ids": awsvpc.get("subnets", []),
                        "security_group_ids": awsvpc.get("securityGroups", []),
                        "assign_public_ip": awsvpc.get("assignPublicIp"),
                        "load_balancers": [
                            {
                                "target_group_arn": lb.get("targetGroupArn"),
                                "load_balancer_name": lb.get("loadBalancerName"),
                                "container_name": lb.get("containerName"),
                                "container_port": lb.get("containerPort"),
                            }
                            for lb in s.get("loadBalancers", [])
                        ],
                        "tags": self._extract_tags(s),
                        "region": self.region,
                        "account_id": self.account_id,
                    })
        return clusters, services

    # ── ECR ──────────────────────────────────────────────────────────

    def _collect_ecr_repositories(self) -> list[dict]:
        ecr = self._get_client("ecr")
        repos = self._safe_paginate(ecr, "describe_repositories", "repositories")

        def describe(repo: dict) -> dict:
            images = self._safe_paginate(
                ecr, "list_images", "imageIds",
                max_items=ECR_IMAGE_COUNT_CAP,
                repositoryName=repo["repositoryName"], filter={"tagStatus": "ANY"},
            )
            return {
                "resource_type": "ecr_repository",
                "resource_id": repo.get("repositoryArn", repo["repositoryName"]),
                "name": repo["repositoryName"],
                "uri": repo.get("repositoryUri", ""),
                "image_count": len(images),
                "image_count_capped": len(images) >= ECR_IMAGE_COUNT_CAP,
                "scan_on_push": repo.get("imageScanningConfiguration", {}).get("scanOnPush", False),
                "encryption": repo.get("encryptionConfiguration", {}),
                "image_tag_mutability": repo.get("imageTagMutability"),
                "created_at": str(repo.get("createdAt", "")),
                "region": self.region,
                "account_id": self.account_id,
            }

        return self._parallel(describe, repos)

    def _collect_ecr_replication(self) -> list[dict]:
        """Registry-level replication rules (metadata, used for cross-region diagram links)."""
        ecr = self._get_client("ecr")
        registry = self._safe_call(lambda: ecr.describe_registry(), default={}) or {}
        destinations = []
        for rule in (registry.get("replicationConfiguration") or {}).get("rules", []):
            for dest in rule.get("destinations", []):
                destinations.append({
                    "region": dest.get("region"),
                    "registry_id": dest.get("registryId"),
                })
        return destinations

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
                "layers": [layer.get("Arn", "") for layer in fn.get("Layers", [])],
                "architectures": fn.get("Architectures", []),
                "package_type": fn.get("PackageType"),
                # ListFunctions does not return tags; filled by tag enrichment.
                "tags": {},
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
                "latest_version": layer.get("LatestMatchingVersion", {}).get("Version"),
                "runtimes": layer.get("LatestMatchingVersion", {}).get("CompatibleRuntimes", []),
                "region": self.region,
                "account_id": self.account_id,
            }
            for layer in layers
        ]
