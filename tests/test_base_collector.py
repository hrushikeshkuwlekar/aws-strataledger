import botocore.exceptions
import pytest

from aws_strataledger.collectors.base import BaseCollector, _extract, chunks


class Dummy(BaseCollector):
    SERVICE_NAME = "dummy"

    def collect(self):
        return {}


@pytest.fixture
def collector():
    return Dummy(clients=None, region="us-east-1", account_id="1")


def test_extract_simple():
    assert _extract({"A": [1, 2]}, "A") == [1, 2]


def test_extract_missing_and_none():
    assert _extract({}, "A") == []
    assert _extract({"A": None}, "A") == []


def test_extract_scalar_wrapped():
    assert _extract({"A": 5}, "A") == [5]


def test_extract_dotted_dicts():
    assert _extract({"A": {"B": [1, 2]}}, "A.B") == [1, 2]


def test_extract_nested_list_flattening():
    page = {"Reservations": [{"Instances": [{"id": 1}, {"id": 2}]},
                             {"Instances": [{"id": 3}]},
                             {}]}
    assert _extract(page, "Reservations.Instances") == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_chunks():
    assert list(chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunks([], 3)) == []
    assert list(chunks([1, 2], 5)) == [[1, 2]]


def test_tags_key_value(collector):
    r = {"Tags": [{"Key": "Name", "Value": "x"}, {"Key": "Env", "Value": "p"}]}
    assert collector._extract_tags(r) == {"Name": "x", "Env": "p"}


def test_tags_lowercase(collector):
    assert collector._extract_tags({"tags": [{"key": "a", "value": "b"}]}) == {"a": "b"}


def test_tags_dict(collector):
    assert collector._extract_tags({"Tags": {"a": "b"}}) == {"a": "b"}


def test_tags_taglist_and_empty(collector):
    assert collector._extract_tags({"TagList": [{"Key": "k", "Value": "v"}]}) == {"k": "v"}
    assert collector._extract_tags({}) == {}
    assert collector._extract_tags({"Tags": None}) == {}


def test_tags_ignores_non_dict_entries(collector):
    assert collector._extract_tags({"Tags": ["junk", {"Key": "a", "Value": "b"}]}) == {"a": "b"}


def test_get_name_tag(collector):
    assert collector._get_name_tag({"Tags": [{"Key": "Name", "Value": "n"}]}) == "n"
    assert collector._get_name_tag({}) == ""


def _client_error(code):
    return botocore.exceptions.ClientError({"Error": {"Code": code, "Message": "m"}}, "Op")


@pytest.mark.parametrize("code,level", [
    ("AccessDenied", "denied"), ("OptInRequired", "unavailable"), ("Boom", "error"),
    ("Throttling", "error"),
])
def test_safe_call_classifies(collector, code, level):
    def f():
        raise _client_error(code)
    assert collector._safe_call(f, default="d") == "d"
    assert collector.get_issues()[0]["level"] == level


def test_safe_call_ignore_code(collector):
    def f():
        raise _client_error("NoSuchBucketPolicy")
    assert collector._safe_call(f, default=None, ignore=["NoSuchBucketPolicy"]) is None
    assert collector.get_issues() == []


def test_parallel_preserves_order(collector):
    assert collector._parallel(lambda x: x * 2, [1, 2, 3, 4]) == [2, 4, 6, 8]
