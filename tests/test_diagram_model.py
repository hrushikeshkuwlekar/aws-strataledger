from aws_strataledger.diagram.model import build_diagram_model, classify_subnet_tier

from tests.conftest import make_route_table, make_subnet


def test_public_subnet_igw(route_tables):
    s = make_subnet("subnet-pub", name="x")
    assert classify_subnet_tier(s, route_tables, set()) == "public"


def test_nat_subnet_is_app(route_tables):
    s = make_subnet("subnet-app", name="x")
    assert classify_subnet_tier(s, route_tables, set()) == "app"


def test_no_default_route_is_data(route_tables):
    s = make_subnet("subnet-data", name="x")
    assert classify_subnet_tier(s, route_tables, set()) == "data"


def test_no_route_table_is_data():
    assert classify_subnet_tier(make_subnet("subnet-z"), [], set()) == "data"


def test_main_route_table_fallback():
    rts = [make_route_table("rtb-main", [{"destination_cidr": "0.0.0.0/0", "gateway_id": "igw-1"}],
                            main=True)]
    assert classify_subnet_tier(make_subnet("subnet-unassoc"), rts, set()) == "public"


def test_blackhole_default_route_ignored():
    rts = [make_route_table("rtb", [{"destination_cidr": "0.0.0.0/0", "gateway_id": "igw-1",
                                     "state": "blackhole"}], subnet_ids=["subnet-1"])]
    assert classify_subnet_tier(make_subnet("subnet-1"), rts, set()) == "data"


def test_tag_override(route_tables):
    s = make_subnet("subnet-pub", tags={"strataledger:tier": "Data"})
    assert classify_subnet_tier(s, route_tables, set()) == "data"


def test_invalid_tag_ignored(route_tables):
    s = make_subnet("subnet-pub", tags={"strataledger:tier": "bogus"})
    assert classify_subnet_tier(s, route_tables, set()) == "public"


def test_nfw_subnet(route_tables):
    s = make_subnet("subnet-pub")
    assert classify_subnet_tier(s, route_tables, {"subnet-pub"}) == "firewall"


def test_tag_beats_nfw(route_tables):
    s = make_subnet("subnet-pub", tags={"strataledger:tier": "app"})
    assert classify_subnet_tier(s, route_tables, {"subnet-pub"}) == "app"


def test_app_with_db_name_becomes_data(route_tables):
    s = make_subnet("subnet-app", name="my-db-subnet-a")
    assert classify_subnet_tier(s, route_tables, set()) == "data"


def test_public_with_db_name_stays_public(route_tables):
    s = make_subnet("subnet-pub", name="db-public")
    assert classify_subnet_tier(s, route_tables, set()) == "public"


def test_name_token_must_be_whole_word(route_tables):
    s = make_subnet("subnet-app", name="dbx-subnet")
    assert classify_subnet_tier(s, route_tables, set()) == "app"


def test_build_model_structure(account_data):
    m = build_diagram_model("123456789012", "prod", account_data)
    assert m.account_id == "123456789012"
    assert "us-east-1" in m.regions
    vpc = m.regions["us-east-1"].vpcs["vpc-111"]
    assert vpc.igw_id == "igw-1"
    assert set(vpc.azs) == {"us-east-1a", "us-east-1b"}
    assert set(vpc.azs["us-east-1a"].subnets) == {"public", "app", "data"}
    assert vpc.azs["us-east-1a"].subnets["app"].nodes  # EC2 placed
    assert len(vpc.endpoints) == 1
    assert m.global_nodes and m.all_nodes


def test_build_model_places_nodes_in_subnets(account_data):
    m = build_diagram_model("1", "a", account_data)
    subnets = m.regions["us-east-1"].vpcs["vpc-111"].azs["us-east-1a"].subnets
    assert "nat_gateway:nat-1" in subnets["public"].nodes
    assert "ec2_instance:i-1" in subnets["app"].nodes
    assert "rds_instance:db-1" in subnets["data"].nodes


def test_node_ids_unique_and_consistent(account_data):
    m = build_diagram_model("1", "a", account_data)
    placed = []
    for r in m.regions.values():
        for v in r.vpcs.values():
            for az in v.azs.values():
                for sm in az.subnets.values():
                    placed.extend(sm.nodes)
            placed.extend(e.id for e in v.endpoints)
        placed.extend(g.id for g in r.gutter_nodes)
    placed.extend(g.id for g in m.global_nodes)
    assert len(placed) == len(set(placed))
    assert all(nid in m.all_nodes for nid in placed)
    for key, node in m.all_nodes.items():
        assert key == node.id


def test_terminated_instances_skipped(account_data):
    account_data["regions"]["us-east-1"]["compute"]["ec2_instances"][0]["state"] = "terminated"
    m = build_diagram_model("1", "a", account_data)
    assert "ec2_instance:i-1" not in m.all_nodes


def test_empty_default_vpc_hidden(account_data):
    net = account_data["regions"]["us-east-1"]["networking"]
    net["vpcs"].append({"resource_id": "vpc-default", "name": "", "cidr_block": "172.31.0.0/16",
                        "is_default": True})
    m = build_diagram_model("1", "a", account_data)
    assert "vpc-default" not in m.regions["us-east-1"].vpcs
    assert any("vpc-default" in h for h in m.hidden_default_vpcs)


def test_empty_region_skipped():
    m = build_diagram_model("1", "a", {"global": {}, "regions": {"eu-west-1": {}}})
    assert m.skipped_regions == ["eu-west-1"]
    assert not m.regions
