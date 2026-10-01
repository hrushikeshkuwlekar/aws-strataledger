# 🛰️ AWS StrataLedger — Engineering Specification

**Version:** 1.0.2  
**Product Name:** AWS StrataLedger (`aws-strataledger`)  
**Package:** `src/aws_strataledger`  
**License:** MIT  

---

## 1. Executive Summary

**AWS StrataLedger** is an enterprise-grade, multi-account AWS inventory discovery and topology visualization utility designed for organizations operating complex multi-account environments orchestrated through **AWS IAM Identity Center (AWS SSO)**.

### Core Tenets
1. **Zero Static Credentials**: Authenticates strictly via temporary STS credentials generated from active AWS SSO sessions (`aws configure sso` / `aws sso login`).
2. **Comprehensive Discovery**: Collects metadata across 70+ AWS resource types in Compute, Networking, Storage, Database, Identity, Security, and Monitoring domains.
3. **AWS Reference Architecture Topology**: Generates deterministic, tiered architectural landscapes utilizing official AWS vector SVG icons and 90-degree orthogonal CAD-style routing—completely eliminating messy force-directed spiderwebs.
4. **Single-File Self-Contained Deliverable**: Produces standalone, air-gapped HTML reports containing all embedded assets (SVG icons, Cytoscape.js engine, responsive styles, and scan datasets) with zero runtime server requirements.
5. **Fault-Tolerant Concurrency**: Parallel execution across accounts and regions using `ThreadPoolExecutor`, comprehensive API pagination, and individual collector error isolation.

---

## 2. System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        AWS CLI / SSO PROFILES                          │
│                   (~/.aws/config - SSO Sessions)                       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        AWS STRATALEDGER CLI                            │
│                 (aws-strataledger scan / profiles)                     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
┌───────────────────────────┐             ┌───────────────────────────┐
│     SESSION MANAGER       │             │     SCAN ORCHESTRATOR     │
│  boto3 SSO token resolver │             │   ThreadPoolExecutor      │
│  Account & region mapping │             │   Rate-limiting & retries │
└─────────────┬─────────────┘             └─────────────┬─────────────┘
              │                                         │
              └────────────────────┬────────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          COLLECTOR SUITE                               │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌─────────────┐ │
│  │    Compute    │ │  Networking   │ │Storage & DB   │ │  Identity   │ │
│  │ (EC2/EKS/λ/ASG│ │(VPC/TGW/ELB/  │ │(S3/RDS/Aurora/│ │ (IAM/KMS/   │ │
│  │     ECR)      │ │   NAT/WAF)    │ │ DynamoDB/EFS) │ │   Secrets)  │ │
│  └───────────────┘ └───────────────┘ └───────────────┘ └─────────────┘ │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     TOPOLOGY ARCHITECTURE BUILDER                      │
│ - Route table analysis & subnet tier classification (Public/App/DB)    │
│ - Elimination of route table nodes & redundant mesh edges              │
│ - Direct architectural relationships (Ingress -> ALB -> Compute -> DB) │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
┌───────────────────────────┐             ┌───────────────────────────┐
│      JSON DATA STORE      │             │       REPORT ENGINE       │
│  Structured inventory dump│             │  Jinja2 Single-File HTML  │
│  Multi-account scan audit │             │  Official AWS SVG Icons   │
│  Exportable / scriptable  │             │  Dark/Light Theme Engine  │
└───────────────────────────┘             └───────────────────────────┘
```

---

## 3. Topology & Visual Architecture Engine

The topology visualizer adheres strictly to **AWS Architecture Center standards**.

### 3.1 Architectural Tiers
Subnets and resources are categorized into three distinct tiers based on routing inspection and resource associations:
1. **Ingress & Perimeter Tier**:
   - Central AWS Transit Gateway (TGW)
   - Internet Gateways (IGW)
   - AWS Network Firewalls & AWS WAF Web ACLs
   - Site-to-Site VPN Gateways & Direct Connect
2. **Public Subnet Tier**:
   - Application Load Balancers (ALB) and Network Load Balancers (NLB) with `internet-facing` schemes
   - NAT Gateways providing outbound internet translation
   - Bastion hosts
3. **Private Application / Compute Tier**:
   - Amazon EC2 Instances
   - EC2 Auto Scaling Groups (ASG)
   - Amazon EKS Clusters & Worker Node Groups
   - VPC-connected AWS Lambda Functions
   - AWS VPC Endpoints (PrivateLink)
4. **Private Database & Storage Tier**:
   - Amazon Aurora DB Clusters
   - Amazon RDS Instances (PostgreSQL, MySQL, MariaDB, Oracle, SQL Server)
   - Amazon EFS Mount Targets
5. **AWS Regional & Managed Services Panel**:
   - Amazon S3 Buckets
   - Amazon DynamoDB Tables
   - AWS KMS Customer Managed Keys
   - AWS Secrets Manager Secrets
   - Amazon CloudWatch Alarms

### 3.2 Elimination of Route Table Clutter
In raw network graphs, route tables (`rtb-*`) produce dozens of diagonal mesh edges that obscure architectural relationships. StrataLedger inspects route tables programmatically to classify subnets into their true architectural tiers (`public`, `app`, `db`) and suppresses standalone route table nodes from the visual canvas.

### 3.3 Vector SVG Iconography
Nodes on the canvas render crisp vector SVGs styled after the official AWS 2024 Architecture Icon palette:
- **Compute (AWS Orange `#FF9900`)**: EC2, EKS, Lambda, Auto Scaling
- **Networking & Content Delivery (AWS Purple `#8C4FFF`)**: Transit Gateway, Internet Gateway, NAT Gateway, Elastic Load Balancing, VPC Endpoints, VPN Gateway, VPC
- **Databases (AWS Blue `#2E73B8`)**: RDS Instances, Aurora Clusters, DynamoDB Tables
- **Storage (AWS Green `#3F8624`)**: S3 Buckets, EFS File Systems
- **Security & Identity (AWS Red `#DD344C`)**: WAF Web ACLs, Network Firewall, KMS Keys, Secrets Manager
- **Management & Monitoring (AWS Magenta `#E05243` / `#B00889`)**: CloudWatch Alarms, EventBridge Rules

### 3.4 Orthogonal (Taxi) Routing & Flow Semantics
Edges utilize right-angled CAD-style connectors (`curve-style: 'taxi'` with `taxi-direction: 'vertical'`) to maintain clean architectural alignment:
- **`traffic` (Solid `#38BDF8`, width 2.2px)**: HTTP/HTTPS traffic flow from Ingress $\to$ ALB $\to$ Compute instances.
- **`egress` (Dashed `#10B981`, width 2.0px)**: Outbound NAT traffic from Private Subnets $\to$ NAT Gateway $\to$ Internet.
- **`tgw_attachment` (Solid `#8C4FFF`, width 2.5px)**: Transit Gateway cross-VPC backbone connectivity.
- **`database` (Solid `#3B82F6`, width 2.0px)**: SQL query and data access from compute instances $\to$ RDS / Aurora.
- **`peering` (Dashed `#F97316`, width 2.0px)**: Direct VPC Peering connections.

---

## 4. UI/UX & Dashboard Specification

The generated HTML dashboard includes:
1. **Interactive KPI Metric Tiles**:
   - Replaces static progress bars with interactive summary tiles.
   - Shows resource counts, category distributions, and percentage share.
2. **Per-Account Summary Table**:
   - Account Alias and Account ID
   - Scanned Regions
   - Total Discovered Resources
   - **EKS Clusters Count**
   - **Subnets Count**
   - **Active Firewalls Count** (Network Firewalls + WAF Web ACLs)
3. **Theme Engine**:
   - Dark Mode (sleek navy/slate `#0A0E1A`) and Light Mode (clean gray `#F8FAFC`).
   - One-click toggle in top navigation bar.
   - Persisted across browser sessions via `localStorage`.
   - Real-time Cytoscape canvas re-styling.
4. **Interactive Asset Inventory Table**:
   - Instant search and multi-column filtering (Account, Region, Category, Type, Status).
   - Client-side pagination and sorting.
   - CSV export for spreadsheets and auditing.

---

## 5. CLI Specification

```bash
aws-strataledger [COMMAND] [OPTIONS]
```

### 5.1 Commands
- `aws-strataledger profiles`: Enumerate SSO profiles configured in `~/.aws/config`.
- `aws-strataledger scan`: Execute multi-account, multi-region discovery.
- `aws-strataledger report`: Re-render or customize an HTML report from existing scan JSON.

### 5.2 Scan Options
| Flag | Short | Default | Description |
|---|---|---|---|
| `--profiles` | `-p` | *Required* | Comma-separated profile names or `all` |
| `--regions` | `-r` | *Required* | Comma-separated region names or `all` |
| `--services` | `-s` | `all` | Filter categories: `compute`, `networking`, `storage`, `identity`, `security`, `monitoring` |
| `--output` | `-o` | `./reports` | Destination directory for output files |
| `--verbose` | `-v` | `false` | Enable verbose debug logging |

---

## 6. Upgrade Instructions

To upgrade existing installations from version 1.0.0 to 1.1.0:

### Direct Pip User Upgrade
```bash
pip install --upgrade --no-cache-dir git+https://github.com/hrushikeshkuwlekar/aws-strataledger.git
```

### Editable Development Upgrade
```bash
cd aws-strataledger
git pull origin main
pip install -e . --upgrade
```

### Pipx Upgrade
```bash
pipx install --force git+https://github.com/hrushikeshkuwlekar/aws-strataledger.git
```
