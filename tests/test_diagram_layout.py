from aws_strataledger.diagram.layout import MAX_ICONS_PER_SUBNET, LayoutResult, compute_layout
from aws_strataledger.diagram.model import build_diagram_model
from aws_strataledger.diagram.svg import render_svg


def _layout(account_data):
    return compute_layout(build_diagram_model("123456789012", "prod", account_data))


def test_layout_result_dimensions(account_data):
    res = _layout(account_data)
    assert isinstance(res, LayoutResult)
    assert res.width > 0 and res.height > 0
    assert res.containers[0].kind == "aws_cloud"


def test_empty_model_layout():
    res = compute_layout(build_diagram_model("1", "a", {}))
    assert res.width > 0 and res.height > 0


def test_no_negative_dimensions(account_data):
    res = _layout(account_data)
    for c in res.containers:
        assert c.rect.w >= 0 and c.rect.h >= 0, c.id
    for n in res.nodes + res.global_nodes:
        assert n.rect.w >= 0 and n.rect.h >= 0, n.id


def test_container_kinds_present(account_data):
    kinds = {c.kind for c in _layout(account_data).containers}
    assert {"aws_cloud", "region", "vpc", "az", "subnet_public", "subnet_private",
            "subnet_data"} <= kinds


def test_subnet_nodes_inside_subnet(account_data):
    res = _layout(account_data)
    subnets = {c.id: c.rect for c in res.containers if c.id.startswith("subnet:")}
    app = subnets["subnet:subnet-app"]
    placed = [n for n in res.nodes if n.id.startswith("ec2_instance:")]
    assert len(placed) == 2
    for n in placed:
        r = n.rect
        assert app.x <= r.x and r.right <= app.right
        assert app.y <= r.y and r.bottom <= app.bottom


def test_nodes_inside_cloud_and_vpc(account_data):
    res = _layout(account_data)
    cloud = res.containers[0].rect
    vpc = next(c for c in res.containers if c.kind == "vpc").rect
    for n in res.nodes + res.global_nodes:
        assert 0 <= n.rect.x and n.rect.right <= cloud.right, n.id
        assert n.rect.bottom <= cloud.bottom, n.id
    for n in res.nodes:
        if n.id.startswith(("ec2_instance:", "nat_gateway:", "rds_instance:", "vpc_endpoint:")):
            assert vpc.x <= n.rect.x and n.rect.right <= vpc.right, n.id
            assert vpc.y <= n.rect.y and n.rect.bottom <= vpc.bottom, n.id


def test_overflow_chip(account_data):
    net_c = account_data["regions"]["us-east-1"]["compute"]
    net_c["ec2_instances"] = [
        {"resource_id": f"i-{i}", "name": f"n{i}", "state": "running", "subnet_id": "subnet-app"}
        for i in range(11)
    ]
    res = _layout(account_data)
    chips = [n for n in res.nodes if n.id.startswith("overflow:")]
    assert [c.label for c in chips] == [f"+{11 - MAX_ICONS_PER_SUBNET} more"]


def test_render_svg_smoke(account_data):
    svg = render_svg(_layout(account_data))
    assert svg.lstrip().startswith("<svg") and svg.rstrip().endswith("</svg>")


def _overlaps(rects, pad=0.5):
    out = []
    for i, (a_id, a) in enumerate(rects):
        for b_id, b in rects[i + 1:]:
            if a.x < b.right - pad and b.x < a.right - pad and a.y < b.bottom - pad and b.y < a.bottom - pad:
                out.append((a_id, b_id))
    return out


def test_nothing_overlaps_even_with_long_names(account_data):
    from aws_strataledger.diagram.layout import CELL_W, Rect
    from aws_strataledger.diagram.svg import CELL_LABEL_CHARS

    long = "-very-long-production-resource-name"
    r = account_data["regions"]["us-east-1"]
    r["compute"]["ec2_instances"] = [
        {"resource_id": f"i-{i}", "name": f"svc-{i}{long}", "state": "running", "subnet_id": "subnet-app",
         "instance_type": "m5.large"} for i in range(5)
    ]
    r["compute"]["lambda_functions"] = [
        {"resource_id": f"arn:aws:lambda:us-east-1:1:function:f{i}", "name": f"fn-{i}{long}",
         "vpc_config": {"SubnetIds": ["subnet-app", "subnet-data"]}} for i in range(4)
    ]
    r["networking"]["load_balancers_v2"] = [{"resource_id": "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/w/1",
                                             "name": f"web{long}", "subnet_ids": ["subnet-pub", "subnet-pub-b"]}]
    res = _layout(account_data)

    assert not _overlaps([(g.id, g.rect) for g in res.groups])
    subnets = [(c.id, c.rect) for c in res.containers if c.kind.startswith("subnet_")]
    assert not _overlaps(subnets)
    assert not [(g.id, s) for g in res.groups for s, rect in subnets if _overlaps([(g.id, g.rect), (s, rect)])]
    # icon cells (icon + its labels) never collide, and a label always fits its cell
    cells = [(n.id, Rect(n.rect.cx - CELL_W / 2, n.rect.y, CELL_W, n.rect.h + 26))
             for n in res.nodes + [m for g in res.groups for m in g.members]
             if not n.id.startswith(("igw:", "vgw:", "overflow:"))]
    assert not _overlaps(cells, pad=1)
    assert CELL_LABEL_CHARS * 6.4 < CELL_W
    for g in res.groups:
        for m in g.members:
            assert g.rect.x <= m.rect.x and m.rect.right <= g.rect.right and m.rect.bottom + 26 <= g.rect.bottom


def test_global_table_drawn_once_per_region_pair(account_data):
    import copy as _copy
    account_data["regions"]["eu-west-1"] = _copy.deepcopy(account_data["regions"]["us-east-1"])
    for region in ("us-east-1", "eu-west-1"):
        account_data["regions"][region]["storage"]["dynamodb_tables"] = [
            {"name": "t", "replica_regions": ["us-east-1", "eu-west-1"]}]
    res = _layout(account_data)
    replication = [(e.source, e.target) for e in res.edges if e.kind == "replication"]
    assert replication == [("tile:eu-west-1:DynamoDB", "tile:us-east-1:DynamoDB")]
