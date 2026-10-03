"""Parent → child relationships rendered in the architecture diagram."""
from aws_strataledger.diagram.layout import compute_layout
from aws_strataledger.diagram.model import build_diagram_model
from aws_strataledger.diagram.svg import render_svg

ALB = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/web/111"
TG = "arn:aws:elasticloadbalancing:us-east-1:1:targetgroup/web-tg/222"


def _region(account_data):
    return account_data["regions"]["us-east-1"]


def _build(account_data):
    model = build_diagram_model("123456789012", "prod", account_data)
    return model, compute_layout(model)


def _group(layout, gid):
    return next(g for g in layout.groups if g.id == gid)


def test_ec2_has_ebs_and_eip_attachments(account_data):
    r = _region(account_data)
    r["storage"]["ebs_volumes"] = [
        {"resource_id": "vol-1", "size_gb": 100, "volume_type": "gp3",
         "attachments": [{"instance_id": "i-1", "device": "/dev/xvda"}]},
        {"resource_id": "vol-2", "size_gb": 20, "volume_type": "gp2", "attachments": []},
    ]
    r["networking"]["elastic_ips"] = [{"public_ip": "52.0.0.1", "instance_id": "i-1", "association_id": "a"}]
    model, layout = _build(account_data)

    node = model.all_nodes["ec2_instance:i-1"]
    assert ("ebs_volume", "100G gp3") in node.attachments
    assert ("elastic_ip", "52.0.0.1") in node.attachments
    assert not model.all_nodes["ec2_instance:i-2"].attachments
    tiles = {t.service: t.count for t in model.regions["us-east-1"].tiles}
    assert tiles["EBS unattached"] == 1
    assert "/dev/xvda" in next(n for n in layout.nodes if n.id == "ec2_instance:i-1").tooltip


def test_alb_contains_target_groups_and_routes_to_targets(account_data):
    net = _region(account_data)["networking"]
    net["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "type": "application",
                                 "dns_name": "web-1.elb.amazonaws.com",
                                 "subnet_ids": ["subnet-pub", "subnet-pub-b"]}]
    net["target_groups"] = [{"resource_id": TG, "name": "web-tg", "load_balancer_arns": [ALB],
                             "targets": [{"id": "i-1", "state": "healthy"}]}]
    account_data["global"]["route53"]["route53_hosted_zones"][0]["alias_targets"] = [
        {"name": "www.example.com", "dns_name": "dualstack.web-1.elb.amazonaws.com"}]
    _model, layout = _build(account_data)

    alb = _group(layout, "load_balancer_v2:111")
    assert [m.id for m in alb.members] == ["target_group:222"]
    member = alb.members[0].rect
    assert alb.card.x <= member.x and member.right <= alb.card.right
    assert alb.card.y <= member.y and member.bottom <= alb.card.bottom
    pairs = {(e.source, e.target) for e in layout.edges}
    assert ("target_group:222", "ec2_instance:i-1") in pairs
    assert ("global:route53", "load_balancer_v2:111") in pairs


def test_aurora_cluster_contains_its_instances_not_duplicated(account_data):
    st = _region(account_data)["storage"]
    st["rds_instances"] += [
        {"resource_id": "arn:db:w", "name": "w", "subnet_id": "subnet-data"},
        {"resource_id": "arn:db:r", "name": "r", "subnet_id": "subnet-data"},
    ]
    st["rds_clusters"] = [{"resource_id": "arn:cluster:orders", "name": "orders",
                           "members": [{"instance_id": "w", "is_writer": True},
                                       {"instance_id": "r", "is_writer": False}]}]
    model, layout = _build(account_data)

    cluster = _group(layout, "rds_cluster:orders")
    assert [m.label for m in cluster.members] == ["w", "r"]
    assert cluster.members[0].sublabel.startswith("writer")
    data_subnet = model.regions["us-east-1"].vpcs["vpc-111"].azs["us-east-1a"].subnets["data"]
    assert data_subnet.nodes == ["rds_instance:db-1"]


def test_elasticache_replication_group_contains_member_clusters(account_data):
    st = _region(account_data)["storage"]
    st["elasticache_replication_groups"] = [{"resource_id": "arn:rg:s", "name": "s",
                                             "member_clusters": ["s-001", "s-002"]}]
    st["elasticache_clusters"] = [
        {"resource_id": "arn:cc:1", "name": "s-001", "subnet_id": "subnet-data", "replication_group_id": "s"},
        {"resource_id": "arn:cc:2", "name": "s-002", "subnet_id": "subnet-data", "replication_group_id": "s"},
        {"resource_id": "arn:cc:3", "name": "solo", "subnet_id": "subnet-data"},
    ]
    model, layout = _build(account_data)
    assert [m.label for m in _group(layout, "elasticache_replication_group:s").members] == ["s-001", "s-002"]
    assert "elasticache_cluster:3" in model.regions["us-east-1"].vpcs["vpc-111"].azs["us-east-1a"].subnets["data"].nodes


def test_eks_node_groups_and_fargate_inside_cluster(account_data):
    _region(account_data)["compute"]["eks_clusters"] = [{
        "resource_id": "arn:aws:eks:us-east-1:1:cluster/k", "name": "k", "version": "1.30",
        "fargate_profile_count": 2,
        "node_groups": [{"name": "ng", "subnet_ids": ["subnet-app"], "scaling": {"desiredSize": 3}}],
    }]
    _model, layout = _build(account_data)
    labels = [m.label for m in _group(layout, "eks_cluster:k").members]
    assert labels == ["ng", "Fargate"]


def test_network_relationship_edges(account_data):
    net = _region(account_data)["networking"]
    net["vpn_gateways"] = [{"resource_id": "vgw-1", "vpc_attachments": [{"vpc_id": "vpc-111"}]}]
    net["customer_gateways"] = [{"resource_id": "cgw-1"}]
    net["vpn_connections"] = [{"resource_id": "vpn-1", "customer_gateway_id": "cgw-1",
                               "vpn_gateway_id": "vgw-1"}]
    net["transit_gateways"] = [{"resource_id": "tgw-1"}]
    net["transit_gateway_attachments"] = [{"transit_gateway_id": "tgw-1", "resource_type_attached": "vpc",
                                           "resource_id_attached": "vpc-111", "resource_id": "tgw-attach-1"}]
    net["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "subnet_ids": ["subnet-pub"]}]
    net["waf_web_acls"] = [{"resource_id": "arn:waf/acl/w", "name": "w", "associated_resources": [ALB]}]
    _model, layout = _build(account_data)

    pairs = {(e.source, e.target) for e in layout.edges}
    assert ("customer_gateway:cgw-1", "vpn_connection:vpn-1") in pairs
    assert ("vpn_connection:vpn-1", "vgw:vgw-1") in pairs
    assert ("transit_gateway:tgw-1", "vpc:vpc-111") in pairs
    assert ("waf_web_acl:w", "load_balancer_v2:111") in pairs
    assert ("vpc_endpoint:vpce-1", "tile:us-east-1:S3") in pairs
    assert ("nat_gateway:nat-1", "igw:igw-1") in pairs


def test_nfw_and_efs_place_children_in_each_subnet(account_data):
    r = _region(account_data)
    r["networking"]["network_firewalls"] = [{"resource_id": "arn:fw/f", "name": "f",
                                             "subnet_mappings": ["subnet-pub"],
                                             "subnet_to_endpoint": {"subnet-pub": "vpce-fw"}}]
    r["storage"]["efs_file_systems"] = [{"resource_id": "arn:efs/fs-1", "file_system_id": "fs-1",
                                         "mount_targets": [{"mount_target_id": "fsmt-1",
                                                            "subnet_id": "subnet-app"}]}]
    model, _layout = _build(account_data)
    vpc = model.regions["us-east-1"].vpcs["vpc-111"]
    all_nodes = [n for az in vpc.azs.values() for sm in az.subnets.values() for n in sm.nodes]
    assert "nfw_endpoint:vpce-fw" in all_nodes
    assert "efs_mount_target:fsmt-1" in all_nodes


def test_two_subnets_same_tier_same_az_both_kept(account_data):
    net = _region(account_data)["networking"]
    net["subnets"].append({"resource_id": "subnet-app2", "vpc_id": "vpc-111", "availability_zone": "us-east-1a",
                           "name": "app-a2", "cidr_block": "10.0.9.0/24"})
    net["route_tables"][1]["associations"].append({"subnet_id": "subnet-app2"})
    model, layout = _build(account_data)
    assert {"app", "app#2"} <= set(model.regions["us-east-1"].vpcs["vpc-111"].azs["us-east-1a"].subnets)
    assert any(c.id == "subnet:subnet-app2" for c in layout.containers)


def test_group_overflow_chip(account_data):
    _region(account_data)["compute"]["lambda_functions"] = [
        {"resource_id": f"arn:fn:{i}", "name": f"f{i}", "vpc_config": {"SubnetIds": ["subnet-app"]}}
        for i in range(12)
    ]
    _model, layout = _build(account_data)
    group = next(g for g in layout.groups if g.id.startswith("lambda_group:"))
    assert len(group.members) == 8
    assert group.members[-1].label == "+5 more"
    assert "+5 more" in render_svg(layout)
