"""Parent → child relationships, fleets, new services and edges in the architecture diagram."""
import copy

from aws_strataledger.diagram.icons import has_icon
from aws_strataledger.diagram.layout import compute_layout
from aws_strataledger.diagram.model import MAX_GROUP_MEMBERS, build_diagram_model
from aws_strataledger.diagram.svg import render_svg, shared_defs_svg, used_icon_keys

ALB = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/web/111"
TG = "arn:aws:elasticloadbalancing:us-east-1:1:targetgroup/web-tg/222"
ALB_ID = "load_balancer_v2:us-east-1:111"
TG_ID = "target_group:us-east-1:222"


def _region(account_data):
    return account_data["regions"]["us-east-1"]


def _build(account_data):
    model = build_diagram_model("123456789012", "prod", account_data)
    return model, compute_layout(model)


def _group(layout, gid):
    return next(g for g in layout.groups if g.id == gid)


def _subnet_nodes(model, subnet_key="app", az="us-east-1a"):
    return model.regions["us-east-1"].vpcs["vpc-111"].azs[az].subnets[subnet_key].nodes


def _edges(layout):
    return {(e.source, e.target) for e in layout.edges}


def _inside(inner, outer):
    return outer.x <= inner.x and inner.right <= outer.right and outer.y <= inner.y and inner.bottom <= outer.bottom


# ── Attachments & fleets ────────────────────────────────────────────

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
    assert ("ebs_volume", "EBS 100 GiB gp3") in node.attachments
    assert ("elastic_ip", "Elastic IP 52.0.0.1") in node.attachments
    assert not model.all_nodes["ec2_instance:i-2"].attachments
    tiles = {t.service: t for t in model.regions["us-east-1"].tiles}
    assert tiles["EBS (unattached)"].count == 1 and tiles["EBS (unattached)"].category == "Storage"
    assert "/dev/xvda" in next(n for n in layout.nodes if n.id == "ec2_instance:i-1").tooltip


def test_fleet_instances_collapse_per_subnet(account_data):
    r = _region(account_data)
    r["compute"]["ec2_instances"] = [
        {"resource_id": f"i-n{i}", "state": "running", "subnet_id": "subnet-app", "instance_type": "m6i.large",
         "tags": {"eks:nodegroup-name": "general", "eks:cluster-name": "k"}} for i in range(20)
    ] + [
        {"resource_id": f"i-w{i}", "state": "running", "subnet_id": "subnet-app", "instance_type": "c6i.large",
         "tags": {"aws:autoscaling:groupName": "web-asg"}} for i in range(5)
    ]
    model, _ = _build(account_data)
    nodes = [model.all_nodes[n] for n in _subnet_nodes(model)]
    assert [(n.label, n.sublabel) for n in nodes] == [("general", "20 × m6i.large"), ("web-asg", "5 × c6i.large")]
    assert all(n.resource_type == "ec2_instances" for n in nodes)


def test_target_group_points_at_owning_asg_not_each_instance(account_data):
    r = _region(account_data)
    r["compute"]["ec2_instances"] = [
        {"resource_id": f"i-w{i}", "state": "running", "subnet_id": "subnet-app",
         "tags": {"aws:autoscaling:groupName": "web-asg"}} for i in range(3)
    ]
    r["compute"]["auto_scaling_groups"] = [{"resource_id": "arn:aws:autoscaling:us-east-1:1:asg/web-asg",
                                            "name": "web-asg", "subnet_ids": ["subnet-app"]}]
    r["networking"]["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "subnet_ids": ["subnet-pub"]}]
    r["networking"]["target_groups"] = [{"resource_id": TG, "name": "web-tg", "load_balancer_arns": [ALB],
                                         "targets": [{"id": f"i-w{i}", "state": "healthy"} for i in range(3)]}]
    _, layout = _build(account_data)
    from_tg = [e for e in layout.edges if e.source == TG_ID]
    assert [e.target for e in from_tg] == ["auto_scaling_group:us-east-1:web-asg"]
    asg = _group(layout, "auto_scaling_group:us-east-1:web-asg")
    assert asg.dashed and not asg.members


# ── Groups and their children ───────────────────────────────────────

def test_alb_contains_target_groups_and_routes(account_data):
    net = _region(account_data)["networking"]
    net["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "type": "application",
                                 "dns_name": "web-1.elb.amazonaws.com", "subnet_ids": ["subnet-pub", "subnet-pub-b"]}]
    net["target_groups"] = [{"resource_id": TG, "name": "web-tg", "load_balancer_arns": [ALB],
                             "targets": [{"id": "i-1", "state": "healthy"}]}]
    account_data["global"]["route53"]["route53_hosted_zones"][0]["alias_targets"] = [
        {"name": "www.example.com", "dns_name": "dualstack.web-1.elb.amazonaws.com"}]
    _, layout = _build(account_data)

    alb = _group(layout, ALB_ID)
    assert alb.icon == "alb" and [m.id for m in alb.members] == [TG_ID]
    assert _inside(alb.members[0].rect, alb.rect)
    pub_a = next(c.rect for c in layout.containers if c.id == "subnet:subnet-pub")
    pub_b = next(c.rect for c in layout.containers if c.id == "subnet:subnet-pub-b")
    assert alb.rect.x <= pub_a.x and alb.rect.right >= pub_b.right  # spans both AZ columns
    assert {(TG_ID, "ec2_instance:i-1"), ("global:route53", ALB_ID), ("global:users", "global:route53")} <= _edges(layout)


def test_aurora_cluster_contains_its_instances_not_duplicated(account_data):
    st = _region(account_data)["storage"]
    st["rds_instances"] += [
        {"resource_id": "arn:aws:rds:us-east-1:1:db:w", "name": "w", "engine": "aurora-postgresql", "subnet_id": "subnet-data"},
        {"resource_id": "arn:aws:rds:us-east-1:1:db:r", "name": "r", "engine": "aurora-postgresql", "subnet_id": "subnet-data"},
    ]
    st["rds_clusters"] = [{"resource_id": "arn:aws:rds:us-east-1:1:cluster:orders", "name": "orders",
                           "engine": "aurora-postgresql",
                           "members": [{"instance_id": "w", "is_writer": True}, {"instance_id": "r", "is_writer": False}]}]
    model, layout = _build(account_data)
    cluster = _group(layout, "rds_cluster:us-east-1:orders")
    assert cluster.icon == "aurora"
    assert [m.label for m in cluster.members] == ["w", "r"]
    assert cluster.members[0].sublabel.startswith("writer")
    assert _subnet_nodes(model, "data") == ["rds_instance:db-1"]
    assert model.all_nodes["rds_instance:db-1"].resource_type == "rds_mysql"


def test_documentdb_cluster_uses_documentdb_icon(account_data):
    st = _region(account_data)["storage"]
    st["rds_instances"].append({"resource_id": "arn:aws:rds:us-east-1:1:db:d1", "name": "d1", "engine": "docdb",
                                "subnet_id": "subnet-data", "cluster_identifier": "catalog"})
    st["rds_clusters"] = [{"resource_id": "arn:aws:rds:us-east-1:1:cluster:catalog", "name": "catalog",
                           "engine": "docdb", "members": [{"instance_id": "d1", "is_writer": True}]}]
    _, layout = _build(account_data)
    g = _group(layout, "rds_cluster:us-east-1:catalog")
    assert g.icon == "documentdb" and g.members[0].resource_type == "documentdb"


def test_elasticache_replication_group_contains_member_clusters(account_data):
    st = _region(account_data)["storage"]
    st["elasticache_replication_groups"] = [{"resource_id": "arn:aws:elasticache:us-east-1:1:replicationgroup:s",
                                             "name": "s", "engine": "redis", "member_clusters": ["s-001", "s-002"]}]
    st["elasticache_clusters"] = [
        {"resource_id": "arn:aws:elasticache:us-east-1:1:cluster:s-001", "name": "s-001", "subnet_id": "subnet-data",
         "replication_group_id": "s"},
        {"resource_id": "arn:aws:elasticache:us-east-1:1:cluster:s-002", "name": "s-002", "subnet_id": "subnet-data",
         "replication_group_id": "s"},
        {"resource_id": "arn:aws:elasticache:us-east-1:1:cluster:solo", "name": "solo", "engine": "memcached",
         "subnet_id": "subnet-data"},
    ]
    model, layout = _build(account_data)
    g = _group(layout, "elasticache_replication_group:us-east-1:s")
    assert g.icon == "elasticache_redis" and [m.label for m in g.members] == ["s-001", "s-002"]
    solo = model.all_nodes["elasticache_cluster:us-east-1:solo"]
    assert solo.id in _subnet_nodes(model, "data") and solo.resource_type == "elasticache_memcached"


def test_eks_node_groups_and_fargate_inside_cluster(account_data):
    _region(account_data)["compute"]["eks_clusters"] = [{
        "resource_id": "arn:aws:eks:us-east-1:1:cluster/k", "name": "k", "version": "1.30",
        "fargate_profile_count": 2,
        "node_groups": [{"name": "ng", "subnet_ids": ["subnet-app"], "scaling": {"desiredSize": 3},
                         "capacity_type": "ON_DEMAND"}],
    }]
    _, layout = _build(account_data)
    g = _group(layout, "eks_cluster:us-east-1:k")
    assert [(m.label, m.sublabel) for m in g.members] == [("ng", "on-demand ×3"), ("Fargate", "2 profiles")]


def test_ecs_services_grouped_by_cluster(account_data):
    _region(account_data)["compute"]["ecs_services"] = [
        {"resource_id": f"arn:aws:ecs:us-east-1:1:service/pay/{n}", "name": n, "cluster": "pay",
         "launch_type": "FARGATE", "subnet_ids": ["subnet-app"], "desired_count": 2, "running_count": 2}
        for n in ("a", "b")
    ]
    _, layout = _build(account_data)
    g = _group(layout, "ecs_cluster:us-east-1:pay")
    assert [m.label for m in g.members] == ["a", "b"] and g.members[0].sublabel == "FARGATE 2/2"


def test_group_overflow_chip(account_data):
    _region(account_data)["compute"]["lambda_functions"] = [
        {"resource_id": f"arn:aws:lambda:us-east-1:1:function:f{i}", "name": f"f{i}",
         "vpc_config": {"SubnetIds": ["subnet-app"]}} for i in range(12)
    ]
    _, layout = _build(account_data)
    group = next(g for g in layout.groups if g.id.startswith("lambda_group:"))
    assert len(group.members) == MAX_GROUP_MEMBERS
    assert group.members[-1].label == f"+{12 - MAX_GROUP_MEMBERS + 1} more"


# ── New services ────────────────────────────────────────────────────

def test_new_vpc_services_become_groups(account_data):
    r = _region(account_data)
    r["analytics"] = {
        "msk_clusters": [{"resource_id": "arn:aws:kafka:us-east-1:1:cluster/events/x", "name": "events",
                          "broker_count": 2, "instance_type": "kafka.m5.large", "kafka_version": "3.6.0",
                          "subnet_ids": ["subnet-app"]}],
        "emr_clusters": [{"resource_id": "arn:aws:elasticmapreduce:us-east-1:1:cluster/j-1", "cluster_id": "j-1",
                          "name": "spark", "subnet_ids": ["subnet-app"], "release_label": "emr-7.1.0"}],
        "kinesis_streams": [{"name": "clicks"}],
    }
    r["integration"] = {
        "mq_brokers": [{"resource_id": "arn:aws:mq:us-east-1:1:broker:legacy:b-1", "name": "legacy",
                        "engine": "ActiveMQ", "subnet_ids": ["subnet-app"]}],
        "sqs_queues": [{"name": "q1"}, {"name": "q2"}],
        "sns_topics": [{"name": "t"}],
    }
    r["storage"]["fsx_file_systems"] = [{"resource_id": "arn:aws:fsx:us-east-1:1:file-system/fs-1",
                                          "name": "scratch", "file_system_type": "LUSTRE", "subnet_ids": ["subnet-data"]}]
    r["storage"]["memorydb_clusters"] = [{"resource_id": "arn:aws:memorydb:us-east-1:1:cluster/m", "name": "m",
                                          "subnet_ids": ["subnet-data"]}]
    r["storage"]["elasticache_serverless_caches"] = [{"resource_id": "arn:aws:elasticache:us-east-1:1:serverlesscache:sc",
                                                      "name": "sc", "engine": "valkey", "subnet_ids": ["subnet-data"]}]
    model, layout = _build(account_data)

    icons = {g.label: g.icon for g in layout.groups}
    assert icons == {"events": "msk", "legacy": "mq", "scratch": "fsx", "m": "elasticache_redis",
                     "sc": "elasticache_redis"}
    assert "emr_cluster:j-1" in _subnet_nodes(model)
    tiles = {t.service: (t.count, t.category) for t in model.regions["us-east-1"].tiles}
    assert tiles["SQS"] == (2, "Application Integration")
    assert tiles["SNS"] == (1, "Application Integration")
    assert tiles["Kinesis Data Streams"] == (1, "Analytics")


def test_cloudfront_origins_and_onprem(account_data):
    account_data["global"]["edge"] = {"cloudfront_distributions": [{
        "name": "www", "domain_name": "d1.cloudfront.net",
        "origins": [{"domain_name": "web-1.elb.amazonaws.com"}, {"domain_name": "bucket-1.s3.amazonaws.com"}],
    }]}
    net = _region(account_data)["networking"]
    net["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "dns_name": "web-1.elb.amazonaws.com",
                                 "subnet_ids": ["subnet-pub"]}]
    net["customer_gateways"] = [{"resource_id": "cgw-1", "name": "hq"}]
    model, layout = _build(account_data)
    assert [n.id for n in model.onprem_nodes] == ["customer_gateway:cgw-1"]
    assert any(c.kind == "onprem" for c in layout.containers)
    assert {("global:cloudfront", ALB_ID), ("global:cloudfront", "tile:us-east-1:S3")} <= _edges(layout)


def test_network_relationship_edges(account_data):
    net = _region(account_data)["networking"]
    net["vpn_gateways"] = [{"resource_id": "vgw-1", "vpc_attachments": [{"vpc_id": "vpc-111"}]}]
    net["customer_gateways"] = [{"resource_id": "cgw-1"}]
    net["vpn_connections"] = [{"resource_id": "vpn-1", "customer_gateway_id": "cgw-1", "vpn_gateway_id": "vgw-1"}]
    net["transit_gateways"] = [{"resource_id": "tgw-1"}]
    net["transit_gateway_attachments"] = [{"transit_gateway_id": "tgw-1", "resource_type_attached": "vpc",
                                           "resource_id_attached": "vpc-111"}]
    net["load_balancers_v2"] = [{"resource_id": ALB, "name": "web", "subnet_ids": ["subnet-pub"]}]
    net["waf_web_acls"] = [{"resource_id": "arn:aws:wafv2:us-east-1:1:regional/webacl/w/1", "name": "w",
                            "associated_resources": [ALB]}]
    _, layout = _build(account_data)
    assert {
        ("customer_gateway:cgw-1", "vpn_connection:vpn-1"),
        ("vpn_connection:vpn-1", "vgw:vgw-1"),
        ("transit_gateway:tgw-1", "vpc:vpc-111"),
        ("waf_web_acl:us-east-1:1", ALB_ID),
    } <= _edges(layout)


def test_nfw_endpoints_per_subnet_and_efs_spans(account_data):
    r = _region(account_data)
    r["networking"]["network_firewalls"] = [{"resource_id": "arn:aws:network-firewall:us-east-1:1:firewall/f",
                                             "name": "f", "subnet_mappings": ["subnet-pub"],
                                             "subnet_to_endpoint": {"subnet-pub": "vpce-fw"}}]
    r["storage"]["efs_file_systems"] = [{"resource_id": "arn:aws:elasticfilesystem:us-east-1:1:file-system/fs-1",
                                         "file_system_id": "fs-1", "mount_targets": [{"subnet_id": "subnet-app"}]}]
    model, layout = _build(account_data)
    vpc = model.regions["us-east-1"].vpcs["vpc-111"]
    placed = [n for az in vpc.azs.values() for sm in az.subnets.values() for n in sm.nodes]
    assert "nfw_endpoint:vpce-fw" in placed
    assert _group(layout, "efs_filesystem:us-east-1:fs-1").icon == "efs"


# ── Structure ───────────────────────────────────────────────────────

def test_same_names_in_two_regions_do_not_collide(account_data):
    account_data["regions"]["eu-west-1"] = eu = copy.deepcopy(_region(account_data))
    for region, data in (("us-east-1", _region(account_data)), ("eu-west-1", eu)):
        data["storage"]["rds_instances"] = [{"resource_id": f"arn:aws:rds:{region}:1:db:orders-0", "name": "orders-0",
                                             "subnet_id": "subnet-data", "availability_zone": f"{region}a"}]
    model, _ = _build(account_data)
    assert model.all_nodes["rds_instance:us-east-1:orders-0"].container_id == "subnet-data"
    assert "rds_instance:eu-west-1:orders-0" in model.all_nodes


def test_two_subnets_same_tier_same_az_both_kept(account_data):
    net = _region(account_data)["networking"]
    net["subnets"].append({"resource_id": "subnet-app2", "vpc_id": "vpc-111", "availability_zone": "us-east-1a",
                           "name": "app-a2", "cidr_block": "10.0.9.0/24"})
    net["route_tables"][1]["associations"].append({"subnet_id": "subnet-app2"})
    model, layout = _build(account_data)
    assert {"app", "app#2"} <= set(model.regions["us-east-1"].vpcs["vpc-111"].azs["us-east-1a"].subnets)
    assert any(c.id == "subnet:subnet-app2" for c in layout.containers)


def test_many_empty_subnets_merge_and_empty_vpcs_are_listed(account_data):
    net = _region(account_data)["networking"]
    for i in range(4):
        net["subnets"].append({"resource_id": f"subnet-pod{i}", "vpc_id": "vpc-111", "availability_zone": "us-east-1a",
                               "name": f"pods-{i}", "cidr_block": f"10.0.{50 + i}.0/24"})
        net["route_tables"][1]["associations"].append({"subnet_id": f"subnet-pod{i}"})
    net["vpcs"].append({"resource_id": "vpc-empty", "name": "sandbox", "cidr_block": "10.9.0.0/16"})
    model, layout = _build(account_data)
    merged = [c for c in layout.containers if c.id.startswith("subnets:")]
    assert len(merged) == 1 and merged[0].label == "4 more subnets"
    assert model.regions["us-east-1"].empty_vpcs == ["sandbox (10.9.0.0/16)"]
    assert any("sandbox" in lbl.text for lbl in layout.labels)


def test_every_resource_type_has_a_real_icon(account_data):
    test_new_vpc_services_become_groups(account_data)
    _, layout = _build(account_data)
    types = {n.resource_type for n in layout.nodes + layout.global_nodes + layout.external_nodes}
    types |= {m.resource_type for g in layout.groups for m in g.members} | {g.icon for g in layout.groups}
    types |= {t.icon for t in layout.tiles}
    missing = {t for t in types if not has_icon(t)}
    assert not missing


def test_shared_defs_and_escaping(account_data):
    _region(account_data)["compute"]["ec2_instances"][0]["name"] = '<script>alert("x")</script>'
    _, layout = _build(account_data)
    page_svg = render_svg(layout, embed_defs=False)
    assert "<symbol" not in page_svg and "<marker" not in page_svg
    defs = shared_defs_svg(used_icon_keys(layout))
    assert 'id="sl-defs"' in defs and "sl-arrow-traffic" in defs and 'id="awsi-ec2_instance"' in defs
    assert "<script>" not in page_svg and "&lt;script&gt;" in page_svg
    standalone = render_svg(layout)
    assert "<symbol" in standalone and "<marker" in standalone
