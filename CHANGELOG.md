# Changelog

All notable changes to **AWS StrataLedger** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-10-02

### 🏛️ AWS Reference Architecture Topology & Official Icons
- **Official AWS Vector SVG Icon Library**: Embedded crisp vector SVG icons adhering to official AWS 2024 architecture specifications:
  - **Compute (`#FF9900`)**: Amazon EC2, Amazon EKS Cluster, AWS Lambda, EC2 Auto Scaling Groups.
  - **Networking & Content Delivery (`#8C4FFF`)**: AWS Transit Gateway, Internet Gateway, NAT Gateway, Elastic Load Balancing (ALB/NLB), VPC Endpoints, Site-to-Site VPN, AWS VPC.
  - **Database (`#2E73B8`)**: Amazon Aurora Clusters, Amazon RDS Instances, Amazon DynamoDB Tables.
  - **Storage (`#3F8624`)**: Amazon S3 Buckets, Amazon EFS File Systems.
  - **Security, Identity & Compliance (`#DD344C`)**: AWS WAF Web ACLs, AWS Network Firewall, AWS KMS Keys, AWS Secrets Manager.
  - **Management & Monitoring (`#E05243` / `#B00889`)**: Amazon CloudWatch Alarms, Amazon EventBridge Rules.
- **Deterministic 3-Tier Landscape Flow**: Replaced chaotic force-directed physics with an architectural tiered positioning engine:
  - **Ingress Tier (Top)**: Transit Gateway, Internet Gateway, and WAF Web ACLs.
  - **VPC Boundary Boxes**: Dashed `#8C4FFF` container boundaries labeled with VPC Name and CIDR block.
  - **Subnet Tier Boxes**: Color-coded container frames for Public Subnets (Teal `#10B981`), Private App Subnets (Blue `#3B82F6`), and Private Database Subnets (Purple `#A855F7`).
  - **AWS Regional & Managed Services Panel**: Dedicated cloud services panel for S3, DynamoDB, KMS, Secrets Manager, and CloudWatch alarms.
- **Orthogonal (Taxi) CAD-Style Flow Lines**: Implemented 90-degree orthogonal connectors (`curve-style: 'taxi'`) with color-coded relationships:
  - Sky Blue (`#38BDF8`): Ingress / HTTP Traffic Flow.
  - Emerald Green Dashed (`#10B981`): Outbound NAT Internet Egress.
  - AWS Purple Solid (`#8C4FFF`): Transit Gateway Attachment Backbone.
  - Royal Blue Solid (`#3B82F6`): Compute-to-Database SQL Access.
  - Amber Dashed (`#F97316`): VPC Peering Connections.
- **Eliminated Route Table Spiderwebs**: Route tables (`rtb-*`) are no longer rendered as noisy graph nodes with dozens of diagonal lines; route tables are analyzed programmatically to classify subnets into their true architectural tiers (`public`, `app`, `db`).
- **Interactive Architecture Toolbar**: Added dedicated controls for `🏛️ AWS Architecture` (Default), `📐 Hierarchical Flow`, `🌐 Force-Directed`, `🎯 Reset View`, `🔍 Fit`, `➕ Zoom In`, and `➖ Zoom Out`.

### 🌓 UI/UX & Dashboard Enhancements
- **Dark Mode & Light Mode Toggle**: Added a theme switcher in the top navigation bar with persistent preference storage via `localStorage` and real-time canvas re-styling.
- **Interactive Resource Metric Tiles**: Replaced static category progress bars on the Overview tab with rich, interactive KPI tiles showing counts, percentage share, and sub-resource breakdowns.
- **Per-Account Summary Metrics**: Added dedicated columns to the Account Summary table for:
  - **EKS Clusters**: Total active Kubernetes clusters per account.
  - **Subnets**: Total VPC subnets provisioned.
  - **Active Firewalls**: Combined count of AWS Network Firewalls and AWS WAF Web ACLs.

### 📦 Upgrades & Installation
- Added one-line upgrade commands for existing installations via `pip`, `pipx`, and editable development clones.

---

## [1.0.0] - 2026-10-01

### 🚀 Initial Release
- **AWS SSO / IAM Identity Center Authentication**: Zero-credential scanning using active AWS SSO profiles configured via `aws configure sso`.
- **70+ AWS Resource Collectors**:
  - **Compute**: EC2 Instances, AMIs, Key Pairs, Auto Scaling Groups, Launch Templates, EKS Clusters & Nodegroups, ECR Repositories, Lambda Functions.
  - **Networking**: VPCs, Subnets, Route Tables, Internet Gateways, NAT Gateways, Elastic IPs, VPC Endpoints, Security Groups, Network ACLs, Transit Gateways, VPC Peering, Site-to-Site VPN, Direct Connect, Load Balancers, API Gateway, Route 53, Network Firewall, WAF, Shield.
  - **Storage & Databases**: S3 Buckets, EBS Volumes, EFS File Systems, RDS / Aurora Clusters & Instances, DynamoDB Tables, AWS Backup.
  - **Identity & Security**: IAM Users, Roles, Policies, Access Analyzer, KMS Keys, Secrets Manager, CloudHSM, Certificate Manager.
  - **Monitoring**: CloudWatch Alarms, Log Groups, EventBridge Rules, Systems Manager Managed Instances.
- **Concurrent Scanner**: `ThreadPoolExecutor`-based multi-account, multi-region scanning engine with rate limiting and exponential backoff.
- **Single-File Self-Contained HTML Report**: Embedded CSS, JS, Tabulator-style inventory table, and Cytoscape.js graph with zero runtime server requirements.
- **JSON and CSV Export**: Complete raw data and table export capabilities.
