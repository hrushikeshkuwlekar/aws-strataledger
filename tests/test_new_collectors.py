"""New service collectors against moto-mocked AWS APIs."""
import json

import boto3
import pytest

moto = pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

from aws_strataledger.collectors.analytics import AnalyticsCollector  # noqa: E402
from aws_strataledger.collectors.edge import EdgeCollector  # noqa: E402
from aws_strataledger.collectors.integration import IntegrationCollector  # noqa: E402
from aws_strataledger.session import ClientFactory  # noqa: E402

REGION = "us-east-1"


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        yield ClientFactory(boto3.Session(region_name=REGION))


def test_integration_collector(aws):
    sqs = boto3.client("sqs", region_name=REGION)
    dlq = sqs.create_queue(QueueName="orders-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sqs.create_queue(QueueName="orders", Attributes={
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "5"})})
    sns = boto3.client("sns", region_name=REGION)
    topic = sns.create_topic(Name="events")["TopicArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=dlq_arn)
    boto3.client("stepfunctions", region_name=REGION).create_state_machine(
        name="checkout", definition='{"StartAt":"A","States":{"A":{"Type":"Pass","End":true}}}',
        roleArn="arn:aws:iam::123456789012:role/sfn")

    c = IntegrationCollector(aws, REGION, "123456789012")
    out = c.collect()

    queues = {q["name"]: q for q in out["sqs_queues"]}
    assert queues["orders"]["dead_letter_target_arn"] == dlq_arn
    assert out["sns_topics"][0]["subscriptions"] == [{"protocol": "sqs", "endpoint": dlq_arn}]
    assert out["step_functions"][0]["name"] == "checkout"
    assert out["mq_brokers"] == []


def test_analytics_collector(aws):
    boto3.client("kinesis", region_name=REGION).create_stream(StreamName="clicks", ShardCount=2)
    out = AnalyticsCollector(aws, REGION, "123456789012").collect()
    stream = out["kinesis_streams"][0]
    assert stream["name"] == "clicks" and stream["resource_id"].startswith("arn:aws:kinesis")
    assert {"firehose_streams", "msk_clusters", "emr_clusters"} <= set(out)


def test_edge_collector(aws):
    boto3.client("cloudfront", region_name="us-east-1").create_distribution(DistributionConfig={
        "CallerReference": "r1", "Comment": "", "Enabled": True,
        "Origins": {"Quantity": 1, "Items": [{"Id": "o1", "DomainName": "assets.s3.amazonaws.com",
                                               "S3OriginConfig": {"OriginAccessIdentity": ""}}]},
        "DefaultCacheBehavior": {"TargetOriginId": "o1", "ViewerProtocolPolicy": "allow-all",
                                 "MinTTL": 0, "ForwardedValues": {"QueryString": False,
                                                                  "Cookies": {"Forward": "none"}}},
    })
    out = EdgeCollector(aws, REGION, "123456789012").collect()
    dist = out["cloudfront_distributions"][0]
    assert dist["domain_name"].endswith("cloudfront.net")
    assert dist["origins"][0]["domain_name"] == "assets.s3.amazonaws.com"
