import json
from unittest import mock

from click.testing import CliRunner

from aws_strataledger import __version__
from aws_strataledger.cli import main


def test_version():
    r = CliRunner().invoke(main, ["--version"])
    assert r.exit_code == 0
    assert __version__ in r.output and "aws-strataledger" in r.output


def test_help_lists_commands():
    r = CliRunner().invoke(main, ["--help"])
    assert r.exit_code == 0
    for cmd in ("scan", "profiles", "report"):
        assert cmd in r.output


def test_profiles_none_found(tmp_path, monkeypatch):
    monkeypatch.setattr("aws_strataledger.config.get_aws_config_path",
                        lambda: tmp_path / "missing-config")
    r = CliRunner().invoke(main, ["profiles"])
    assert r.exit_code == 0
    assert "No SSO profiles found" in r.output


def test_profiles_mocked_empty():
    with mock.patch("aws_strataledger.cli.discover_sso_profiles", return_value=[]):
        r = CliRunner().invoke(main, ["profiles"])
    assert r.exit_code == 0
    assert "No SSO profiles found" in r.output


def test_scan_requires_profiles_and_regions():
    runner = CliRunner()
    r = runner.invoke(main, ["scan"])
    assert r.exit_code != 0
    assert "Missing option" in r.output
    r = runner.invoke(main, ["scan", "--regions", "us-east-1"])
    assert r.exit_code != 0 and "--profiles" in r.output
    r = runner.invoke(main, ["scan", "--profiles", "p"])
    assert r.exit_code != 0 and "--regions" in r.output


def test_scan_no_valid_profiles_aborts():
    with mock.patch("aws_strataledger.cli.resolve_profiles", return_value=[]), \
         mock.patch("aws_strataledger.cli.run_scan") as run:
        r = CliRunner().invoke(main, ["scan", "-p", "x", "-r", "us-east-1"])
    assert r.exit_code == 1
    run.assert_not_called()


def test_scan_empty_result_exits_1():
    with mock.patch("aws_strataledger.cli.resolve_profiles", return_value=[object()]), \
         mock.patch("aws_strataledger.cli.resolve_regions", return_value=["us-east-1"]), \
         mock.patch("aws_strataledger.cli.run_scan", return_value={"accounts": {}}):
        r = CliRunner().invoke(main, ["scan", "-p", "x", "-r", "us-east-1"])
    assert r.exit_code == 1


def test_report_missing_input(tmp_path):
    r = CliRunner().invoke(main, ["report", "-i", str(tmp_path / "nope.json"),
                                  "-o", str(tmp_path / "o.html")])
    assert r.exit_code == 1


def test_report_command_generates(tmp_path, scan_data):
    inp = tmp_path / "scan.json"
    inp.write_text(json.dumps(scan_data))
    out = tmp_path / "o.html"
    r = CliRunner().invoke(main, ["report", "-i", str(inp), "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert out.exists()
