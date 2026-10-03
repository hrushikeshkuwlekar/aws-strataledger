"""
Regenerate src/aws_strataledger/diagram/aws_icons.py from the official AWS
Architecture Icons.

The PNGs are taken from the `diagrams` package (MIT, which redistributes the
AWS Architecture Icons) and downscaled to 96 px with macOS `sips` so reports
stay small. Usage:

    pip download --no-deps diagrams -d /tmp/d && cd /tmp/d && unzip -q diagrams-*.whl 'resources/aws/*'
    python3 scripts/build_aws_icons.py /tmp/d/resources/aws
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIZE = 96
OUT = Path(__file__).resolve().parent.parent / "src/aws_strataledger/diagram/aws_icons.py"

# diagram icon key → path under resources/aws (without .png)
ICON_FILES = {
    # general / groups
    "aws_logo": "aws",
    "users": "general/users",
    "internet": "general/internet-alt1",
    "client": "general/client",
    "corporate_dc": "general/office-building",
    "server": "general/traditional-server",
    "public_subnet": "network/public-subnet",
    "private_subnet": "network/private-subnet",
    # compute
    "ec2_instance": "compute/ec2-instance",
    "ec2_instances": "compute/ec2-instances",
    "ec2_spot": "compute/ec2-spot-instance",
    "ec2": "compute/ec2",
    "ec2_ami": "compute/ec2-ami",
    "elastic_ip": "compute/ec2-elastic-ip-address",
    "auto_scaling_group": "compute/ec2-auto-scaling",
    "lambda": "compute/lambda",
    "lambda_function": "compute/lambda-function",
    "eks_cluster": "compute/elastic-kubernetes-service",
    "ecs_cluster": "compute/elastic-container-service",
    "ecs_service": "compute/elastic-container-service-service",
    "fargate": "compute/fargate",
    "ecr": "compute/ec2-container-registry",
    "beanstalk": "compute/elastic-beanstalk",
    # networking
    "vpc": "network/vpc",
    "igw": "network/internet-gateway",
    "nat_gateway": "network/nat-gateway",
    "alb": "network/elb-application-load-balancer",
    "nlb": "network/elb-network-load-balancer",
    "clb": "network/elb-classic-load-balancer",
    "elb": "network/elastic-load-balancing",
    "vpc_endpoint": "network/endpoint",
    "transit_gateway": "network/transit-gateway",
    "tgw_attachment": "network/transit-gateway-attachment",
    "vpc_peering": "network/vpc-peering",
    "vpn_gateway": "network/vpn-gateway",
    "vpn_connection": "network/vpn-connection",
    "customer_gateway": "network/vpc-customer-gateway",
    "direct_connect": "network/direct-connect",
    "route53": "network/route-53",
    "cloudfront": "network/cloudfront",
    "global_accelerator": "network/global-accelerator",
    "network_firewall": "network/network-firewall",
    "api_gateway": "network/api-gateway",
    # database
    "rds": "database/rds",
    "rds_instance": "database/rds-instance",
    "rds_mysql": "database/rds-mysql-instance",
    "rds_postgres": "database/rds-postgresql-instance",
    "rds_mariadb": "database/rds-mariadb-instance",
    "rds_oracle": "database/rds-oracle-instance",
    "rds_sqlserver": "database/rds-sql-server-instance",
    "aurora": "database/aurora",
    "aurora_instance": "database/aurora-instance",
    "documentdb": "database/documentdb-mongodb-compatibility",
    "neptune": "database/neptune",
    "dynamodb": "database/dynamodb",
    "elasticache": "database/elasticache",
    "elasticache_redis": "database/elasticache-for-redis",
    "elasticache_memcached": "database/elasticache-for-memcached",
    "cache_node": "database/elasticache-cache-node",
    "redshift": "database/redshift",
    # storage
    "s3": "storage/simple-storage-service-s3",
    "ebs": "storage/elastic-block-store-ebs",
    "ebs_volume": "storage/elastic-block-store-ebs-volume",
    "ebs_snapshot": "storage/elastic-block-store-ebs-snapshot",
    "efs": "storage/elastic-file-system-efs",
    "fsx": "storage/fsx",
    "backup": "storage/backup",
    # integration
    "sqs": "integration/simple-queue-service-sqs",
    "sns": "integration/simple-notification-service-sns",
    "eventbridge": "integration/eventbridge",
    "step_functions": "integration/step-functions",
    "mq": "integration/mq",
    # analytics
    "kinesis": "analytics/kinesis-data-streams",
    "firehose": "analytics/kinesis-data-firehose",
    "msk": "analytics/managed-streaming-for-kafka",
    "opensearch": "analytics/amazon-opensearch-service",
    "emr": "analytics/emr",
    # security
    "waf": "security/waf",
    "kms": "security/key-management-service",
    "secrets_manager": "security/secrets-manager",
    "acm": "security/certificate-manager",
    "guardduty": "security/guardduty",
    "cloudhsm": "security/cloudhsm",
    "iam": "security/identity-and-access-management-iam",
    "cognito": "security/cognito",
    "security_hub": "security/security-hub",
    # management
    "cloudwatch": "management/cloudwatch",
    "cloudtrail": "management/cloudtrail",
    "config": "management/config",
    "ssm": "management/systems-manager",
    "organizations": "management/organizations",
}


def main(resources: Path) -> None:
    if not shutil.which("sips"):
        sys.exit("macOS `sips` is required to downscale icons")
    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        for key, rel in ICON_FILES.items():
            src = (resources / f"{rel}.png").resolve()
            if not src.is_file():
                sys.exit(f"missing icon {src}")
            dst = Path(tmp) / f"{key}.png"
            subprocess.run(["sips", "-Z", str(SIZE), str(src), "--out", str(dst)],
                           check=True, capture_output=True)
            entries.append((key, base64.b64encode(dst.read_bytes()).decode()))

    lines = [
        '"""',
        "Official AWS Architecture Icons, embedded as base64 PNG (96 px).",
        "",
        "Generated by scripts/build_aws_icons.py — do not edit by hand.",
        "Icons © Amazon Web Services, used under the AWS Architecture Icons terms",
        "(https://aws.amazon.com/architecture/icons/).",
        '"""',
        "",
        "ICON_PNG: dict[str, str] = {",
    ]
    lines += [f'    "{k}": "{v}",' for k, v in entries]
    lines += ["}", ""]
    OUT.write_text("from __future__ import annotations\n\n" + "\n".join(lines))
    print(f"wrote {len(entries)} icons to {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
