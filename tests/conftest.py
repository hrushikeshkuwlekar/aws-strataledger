"""Shared fixtures: plain-dict mock scan data (no AWS calls)."""
from __future__ import annotations

import copy

import pytest

VPC_ID = "vpc-111"


def make_subnet(sid, az="us-east-1a", name="", cidr="10.0.0.0/24", vpc_id=VPC_ID, tags=None):
    return {
        "resource_id": sid, "name": name, "vpc_id": vpc_id,
        "availability_zone": az, "cidr_block": cidr, "tags": tags or {},
    }


def make_route_table(rt_id, routes, subnet_ids=(), main=False, vpc_id=VPC_ID):
    assoc = [{"subnet_id": s} for s in subnet_ids]
    if main:
        assoc.append({"main": True})
    return {"resource_id": rt_id, "vpc_id": vpc_id, "associations": assoc, "routes": routes}


@pytest.fixture
def route_tables():
    return [
        make_route_table("rtb-pub", [
            {"destination_cidr": "10.0.0.0/16", "gateway_id": "local"},
            {"destination_cidr": "0.0.0.0/0", "gateway_id": "igw-1"},
        ], subnet_ids=["subnet-pub"]),
        make_route_table("rtb-app", [
            {"destination_cidr": "0.0.0.0/0", "nat_gateway_id": "nat-1"},
        ], subnet_ids=["subnet-app"]),
        make_route_table("rtb-data", [
            {"destination_cidr": "10.0.0.0/16", "gateway_id": "local"},
        ], subnet_ids=["subnet-data"]),
    ]


@pytest.fixture
def account_data(route_tables):
    """One account with one region, one non-default VPC, 3 subnets and some resources."""
    return {
        "account_alias": "prod",
        "profile_name": "prod-profile",
        "global": {
            "iam": {"iam_users": [{"resource_id": "u1", "name": "alice", "mfa_enabled": False}],
                    "iam_roles": [{"resource_id": "r1", "name": "role"}]},
            "s3": {"s3_buckets": [{"resource_id": "b1", "name": "bucket-1", "is_public": True}]},
            "route53": {"route53_hosted_zones": [{"resource_id": "z1", "name": "example.com"}]},
        },
        "regions": {
            "us-east-1": {
                "networking": {
                    "vpcs": [{"resource_id": VPC_ID, "name": "main", "cidr_block": "10.0.0.0/16",
                              "is_default": False}],
                    "subnets": [
                        make_subnet("subnet-pub", "us-east-1a", "public-a", "10.0.1.0/24"),
                        make_subnet("subnet-app", "us-east-1a", "app-a", "10.0.2.0/24"),
                        make_subnet("subnet-data", "us-east-1a", "data-a", "10.0.3.0/24"),
                        make_subnet("subnet-pub-b", "us-east-1b", "public-b", "10.0.4.0/24"),
                    ],
                    "route_tables": route_tables + [
                        make_route_table("rtb-pub-b", [
                            {"destination_cidr": "0.0.0.0/0", "gateway_id": "igw-1"}],
                            subnet_ids=["subnet-pub-b"]),
                    ],
                    "internet_gateways": [{"resource_id": "igw-1",
                                           "attachments": [{"vpc_id": VPC_ID}]}],
                    "nat_gateways": [{"resource_id": "nat-1", "subnet_id": "subnet-pub"}],
                    "vpc_endpoints": [{"resource_id": "vpce-1", "vpc_id": VPC_ID,
                                       "service_name": "com.amazonaws.us-east-1.s3",
                                       "vpc_endpoint_type": "Gateway"}],
                },
                "compute": {
                    "ec2_instances": [
                        {"resource_id": "i-1", "name": "web-1", "state": "running",
                         "subnet_id": "subnet-app", "instance_type": "t3.micro"},
                        {"resource_id": "i-2", "name": "web-2", "state": "running",
                         "subnet_id": "subnet-app", "instance_type": "t3.micro"},
                    ],
                },
                "storage": {
                    "rds_instances": [{"resource_id": "db-1", "name": "db", "engine": "mysql",
                                       "subnet_id": "subnet-data"}],
                    "dynamodb_tables": [],
                },
                "security": {"cloudtrail_trails": [{"resource_id": "arn:t1", "is_logging": True}]},
            }
        },
    }


@pytest.fixture
def scan_data(account_data):
    return {
        "scan_metadata": {"regions_scanned": 1, "total_resources": 10,
                          "scan_timestamp": "2026-01-01T00:00:00Z", "issues": []},
        "accounts": {"123456789012": account_data},
    }


@pytest.fixture
def scan_data_copy(scan_data):
    return copy.deepcopy(scan_data)
