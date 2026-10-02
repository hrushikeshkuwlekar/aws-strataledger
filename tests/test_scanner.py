from aws_strataledger.scanner import (
    SERVICE_ALIAS_MAP, _count_resources, _deduplicate_trails, _resolve_service_filter,
)


def test_filter_none_and_empty():
    assert _resolve_service_filter(None) is None
    assert _resolve_service_filter([]) is None


def test_filter_aliases():
    assert _resolve_service_filter(["ec2"]) == {"compute"}
    assert _resolve_service_filter(["rds", "dynamodb"]) == {"storage"}
    assert _resolve_service_filter(["vpc", "lambda"]) == {"networking", "compute"}


def test_s3_alias_present_or_passthrough():
    # s3 is not in the alias map today; it must still resolve to something non-empty.
    result = _resolve_service_filter(["s3"])
    assert result == ({SERVICE_ALIAS_MAP["s3"]} if "s3" in SERVICE_ALIAS_MAP else {"s3"})


def test_filter_case_insensitive_and_passthrough():
    assert _resolve_service_filter(["EC2"]) == {"compute"}
    assert _resolve_service_filter(["Security"]) == {"security"}


def test_count_resources_skips_underscore_keys():
    data = {"a": [1, 2, 3], "_issues": [1, 2, 3, 4], "b": [1]}
    assert _count_resources(data) == 4


def test_count_resources_nested_and_non_dict():
    data = {"compute": {"x": [1, 2], "_meta": [9]}, "_skip": {"y": [1]}, "n": 5}
    assert _count_resources(data) == 2
    assert _count_resources([]) == 0
    assert _count_resources({}) == 0


def _result():
    t = lambda arn: {"resource_id": arn}
    return {"accounts": {"1": {"regions": {
        "us-east-1": {"security": {"cloudtrail_trails": [t("arn:a"), t("arn:b")]}},
        "eu-west-1": {"security": {"cloudtrail_trails": [t("arn:a"), t("arn:c")]}},
        "ap-south-1": {"security": {}},
    }}}}


def test_dedupe_trails_keeps_first_region_sorted():
    r = _result()
    _deduplicate_trails(r)
    regs = r["accounts"]["1"]["regions"]
    # eu-west-1 sorts first, so it keeps arn:a
    assert [t["resource_id"] for t in regs["eu-west-1"]["security"]["cloudtrail_trails"]] == ["arn:a", "arn:c"]
    assert [t["resource_id"] for t in regs["us-east-1"]["security"]["cloudtrail_trails"]] == ["arn:b"]
    assert "cloudtrail_trails" not in regs["ap-south-1"]["security"]


def test_dedupe_trails_per_account():
    r = _result()
    r["accounts"]["2"] = {"regions": {"us-east-1": {"security": {
        "cloudtrail_trails": [{"resource_id": "arn:a"}]}}}}
    _deduplicate_trails(r)
    assert len(r["accounts"]["2"]["regions"]["us-east-1"]["security"]["cloudtrail_trails"]) == 1
