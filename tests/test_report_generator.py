import copy
import re

from markupsafe import Markup

from aws_strataledger.report.generator import (
    _build_summary, _flatten_resources, _script_safe_json, generate_report,
)

XSS = "<img src=x onerror=alert(1)>"


def test_script_safe_json_escapes():
    out = _script_safe_json({"a": "</script><script>x</script>", "b": "<!-- c"})
    assert isinstance(out, Markup)
    assert "</script" not in out and "<!--" not in out
    assert r"<\/script>" in out and r"<\!--" in out


def test_script_safe_json_roundtrip_non_serializable():
    import json
    from datetime import datetime
    out = _script_safe_json({"d": datetime(2020, 1, 1), "n": 1})
    assert json.loads(out)["n"] == 1


def test_flatten_does_not_mutate(scan_data):
    before = copy.deepcopy(scan_data)
    rows = _flatten_resources(scan_data)
    assert scan_data == before
    assert rows
    for r in rows:
        r["mutated"] = True
    assert scan_data == before


def test_flatten_adds_metadata_and_skips_topology(scan_data):
    scan_data["accounts"]["123456789012"]["regions"]["us-east-1"]["topology"] = {
        "nodes": [{"id": "x"}]}
    rows = _flatten_resources(scan_data)
    assert all(r["_account_id"] == "123456789012" and r["_account_alias"] == "prod" for r in rows)
    assert {r["_category"] for r in rows} >= {"iam", "s3", "compute", "networking"}
    assert not any(r.get("id") == "x" for r in rows)


def test_flatten_skips_underscore_keys(scan_data):
    scan_data["accounts"]["123456789012"]["regions"]["us-east-1"]["compute"]["_issues"] = [{"a": 1}]
    assert not any(r.get("a") == 1 for r in _flatten_resources(scan_data))


def test_build_summary_counts(scan_data):
    s = _build_summary(scan_data)
    assert s["total_accounts"] == 1
    assert s["total_regions"] == 1
    assert s["resource_counts_by_type"]["ec2_instances"] == 2
    assert s["resource_counts_by_type"]["subnets"] == 4
    assert s["resource_counts_by_type"]["s3_buckets"] == 1
    assert s["resource_counts_by_category"]["compute"] == 2
    acct = s["accounts"][0]
    assert acct["account_alias"] == "prod"
    assert acct["subnets"] == 4
    assert acct["regions"] == ["us-east-1"]


def test_build_summary_sums_across_regions(scan_data):
    acct = scan_data["accounts"]["123456789012"]
    acct["regions"]["eu-west-1"] = copy.deepcopy(acct["regions"]["us-east-1"])
    s = _build_summary(scan_data)
    assert s["resource_counts_by_type"]["ec2_instances"] == 4


def test_build_summary_empty():
    s = _build_summary({})
    assert s["total_accounts"] == 0 and s["accounts"] == []


def test_generate_report_creates_html(scan_data, tmp_path):
    out = tmp_path / "sub" / "r.html"
    path = generate_report(scan_data, str(out))
    assert path == str(out) and out.exists()
    html = out.read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html")
    assert html.rstrip().endswith("</html>")
    assert "const ALL_RESOURCES" in html
    assert "web-1" in html


def _script_blocks(html):
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I)


def test_xss_resource_name_escaped(scan_data, tmp_path):
    acct = scan_data["accounts"]["123456789012"]
    acct["regions"]["us-east-1"]["compute"]["ec2_instances"][0]["name"] = XSS
    acct["regions"]["us-east-1"]["networking"]["vpcs"][0]["name"] = XSS
    acct["account_alias"] = XSS
    out = tmp_path / "r.html"
    generate_report(scan_data, str(out))
    html = out.read_text(encoding="utf-8")
    # Outside <script> blocks (the HTML markup) the payload must be entity-escaped.
    markup = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    markup = re.sub(r"<style\b[^>]*>.*?</style>", "", markup, flags=re.S | re.I)
    assert "<img src=x onerror" not in markup
    assert "&lt;img src=x onerror=alert(1)&gt;" in markup
    # Inside script blocks the payload is only ever JSON string data (never a script breakout).
    for block in _script_blocks(html):
        assert "</script" not in block.lower()


def test_xss_script_breakout_in_json(scan_data, tmp_path):
    payload = "</script><script>alert(1)</script><!--"
    scan_data["accounts"]["123456789012"]["regions"]["us-east-1"]["compute"][
        "ec2_instances"][0]["name"] = payload
    out = tmp_path / "r.html"
    generate_report(scan_data, str(out))
    html = out.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    for block in _script_blocks(html):
        assert "alert(1)" not in block or "<\\/script>" in block
        assert "</script" not in block.lower()
    assert r"<\/script>" in html


def test_report_survives_empty_scan(tmp_path):
    out = tmp_path / "r.html"
    generate_report({"scan_metadata": {}, "accounts": {}}, str(out))
    assert out.read_text(encoding="utf-8").rstrip().endswith("</html>")
