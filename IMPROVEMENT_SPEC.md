# AWS StrataLedger — Improvement Specification (v1.1.0)

**Status:** In progress · **Target release:** 1.1.0 · **Baseline:** 1.0.3 (`1842142`)
**Scope:** Close every gap found in the 1.0.3 code review against [SPEC.md](SPEC.md), and replace the
Cytoscape "cartography" graph with a deterministic **AWS reference-architecture diagram**.

Each requirement has an ID, the problem it fixes, the required behaviour, and an acceptance check.
The status column is updated as work lands (`☐` open · `☑` done · `◐` partial / deferred with note).

---

## 1. Goals

1. **Trustworthy data** — no silent gaps, no invented relationships, no values that are always wrong.
2. **A diagram an architect would draw** — AWS Cloud → Region → VPC → Availability Zone → Subnet,
   with official-style icons, multi-AZ group boxes, and left-to-right request flow.
3. **Safe, self-contained report** — opens offline, cannot be used to inject script.
4. **Spec-accurate CLI** — flags do what SPEC.md says; scans actually run in parallel.
5. **Verifiable** — automated tests and CI guard all of the above.

### Non-goals (1.1.0)
- Cross-account stitching into a single organisation-wide diagram (each account is drawn separately;
  cross-account links are shown as labelled stubs).
- Live/streaming refresh of the report, and editing the diagram by hand.
- Cost data.

---

## 2. Requirements

### 2.1 Report security & packaging (SEC)

| ID | Problem (1.0.3) | Requirement | Acceptance | Status |
|---|---|---|---|---|
| SEC-1 | Jinja autoescape off; JSON embedded raw in `<script>`; AWS strings written to `innerHTML` unescaped → stored XSS via resource tags | Enable autoescape. Embed data with a script-safe encoder (`<`, `>`, `&`, U+2028/9 escaped). Every dynamic string inserted into HTML goes through `esc()`; diagram text is XML-escaped server-side | A resource named `</script><img src=x onerror=alert(1)>` appears only in escaped form in the output | ☐ |
| SEC-2 | Cytoscape from unpkg and fonts from Google → blank diagram offline, contradicts SPEC §1.4 | No network fetches. Diagram is inline SVG rendered server-side; system font stack | Report contains no `http(s)://` URL other than XML namespaces | ☐ |

### 2.2 Scan engine & CLI (SCN / CLI)

| ID | Problem | Requirement | Acceptance | Status |
|---|---|---|---|---|
| SCN-1 | Accounts and regions scanned serially | Thread pool over all (account, region) units plus one global unit per account; `--concurrency` flag (default 8) | Unit test: N regions run concurrently through the pool | ☐ |
| SCN-2 | One boto3 `Session` shared by worker threads (not thread-safe) | `ClientFactory` creates clients under a lock and caches them per (service, region); clients are shared (they are thread-safe) | No `session.client()` call outside the factory | ☐ |
| SCN-3 | Hand-rolled throttle retry restarts pagination from page 1 | botocore `Config(retries={"mode": "adaptive", "max_attempts": 10})`, connect/read timeouts, larger pool | `_safe_call` no longer sleeps/retries | ☐ |
| SCN-4 | Collector errors/warnings collected then discarded | Every failure is recorded as an issue `{account, region, collector, operation, code, message, level}` in the JSON (`collection_issues`) and shown in a **Coverage** tab; console prints a one-line count | AccessDenied in a collector shows in report Coverage tab | ☐ |
| SCN-5 | Two profiles for the same account silently overwrite each other | De-duplicate by account ID; warn and skip duplicates | Unit test | ☐ |
| SCN-6 | Expected "not configured" responses (e.g. `NoSuchBucketPolicy`) logged as errors | Per-call `ignore=` codes return the default silently | S3 bucket with no policy produces no issue | ☐ |
| SCN-7 | `future.result(timeout=300)` inside `as_completed` is a no-op | Remove; rely on botocore timeouts | — | ☐ |
| SCN-8 | Topology is computed at scan time, so `report` cannot improve old scans | Diagram is built at report time from inventory; JSON gets `schema_version: 2`; `report` accepts v1 files | `report` on a 1.0.x JSON renders | ☐ |
| SCN-9 | Tags missing for DynamoDB, Lambda and others (APIs don't return them) | Enrich tags per region from the Resource Groups Tagging API (`get_resources`) by ARN | DynamoDB table tags populated | ☐ |
| CLI-1 | `--services storage` skips S3, `identity` skips IAM; unknown names accepted | Global collectors map to categories (s3→storage, iam→identity, route53/cloudfront→networking, organizations→security). Unknown names are a usage error listing valid values | `--services storage` collects S3; `--services foo` exits 2 | ☐ |
| CLI-2 | Hard-coded region list misses new regions; `all` includes regions not enabled | `all` resolves per account via `ec2:DescribeRegions` (enabled regions only), falling back to the static list. Explicit names are validated against botocore's region list ∪ static list | `--regions all` on an account skips disabled opt-in regions | ☐ |
| CLI-3 | `logging.disable` runs at import time, muting logging for any importer | Configure logging only inside the CLI entry point | Importing the package doesn't change logging | ☐ |
| CLI-4 | `report` has no customisation (SPEC §5.1) | `report --title`, `--show-default-vpcs`, `--max-icons` | Flags change output | ☐ |
| CLI-5 | `pydantic` declared but unused | Remove dependency | — | ☐ |

### 2.3 Collector correctness & coverage (COL)

| ID | Problem | Requirement | Status |
|---|---|---|---|
| COL-1 | Inspector `aggregationType="SEVERITY"` is invalid; call always fails | Use `ACCOUNT` aggregation → `severityCounts` | ☐ |
| COL-2 | KMS `RotationEnabled` is not in `KeyMetadata` → always False | `get_key_rotation_status` for customer-managed symmetric keys; aliases listed once per region; AWS-managed keys skipped without `DescribeKey`; record multi-region key topology | ☐ |
| COL-3 | Access Analyzer counts capped at 1 (`maxResults=1`); analyzers are regional but scanned once | Move to regional identity collector; count ACTIVE findings via paginator (cap 1000 → "1000+") | ☐ |
| COL-4 | First-page-only APIs: ECR images, EKS clusters/nodegroups/Fargate, WAF ACLs, API GW v2, Backup, GuardDuty, EventBridge buses, AMIs, CloudHSM | Paginate all (manual `NextMarker`/`NextToken` loop where botocore has no paginator) | ☐ |
| COL-5 | S3 "public" only checks policy status | Effective public = (policy public ∧ ¬RestrictPublicBuckets) ∨ (ACL grants AllUsers/AuthenticatedUsers ∧ ¬IgnorePublicAcls), combining account- and bucket-level Block Public Access. Per-bucket calls in parallel against the bucket's own region | ☐ |
| COL-6 | CloudFront-scope WAF and Shield never collected; regional WAF has no associations | New global *edge* collector: CloudFront distributions (origins, aliases, WebACL), WAF `CLOUDFRONT` scope, Shield Advanced subscription. Regional WAF ACLs list associated ALBs / API Gateways | ☐ |
| COL-7 | CloudTrail posture: "logging" and "multi-region" evaluated on different trails; trails whose home region wasn't scanned are invisible | Collect shadow trails with status; de-duplicate by ARN after scan; posture check = some trail that is multi-region **and** logging | ☐ |
| COL-8 | Backup issues a wasted `ListRecoveryPoints` call per vault | Use `NumberOfRecoveryPoints` | ☐ |
| COL-9 | Missing services common in reference architectures | Add **ECS** (clusters, services with subnets/SGs/LB bindings), **ElastiCache**, **OpenSearch**, **Redshift**, **SQS**, **SNS**, **Step Functions**, **CloudFront**; new `integration` category | ☐ |
| COL-10 | Diagram-critical fields missing | EC2 lifecycle (spot), AZ; ASG instance AZs; ELB target health per target group; RDS subnet IDs + SGs; Aurora cluster SGs; DynamoDB replicas (global tables); ECR replication rules; Route 53 alias targets (capped); EKS nodegroup subnets | ☐ |
| COL-11 | Metadata lists counted as resources | Keys prefixed `_` in collector output are metadata and excluded from counts and inventory | ☐ |

### 2.4 AWS architecture diagram (ARC) — replaces Cytoscape topology

See §3 for the full design. Requirements summary:

| ID | Requirement | Status |
|---|---|---|
| ARC-1 | One diagram per account: **AWS Cloud** box → **Region** boxes stacked vertically, aligned to equal width | ☐ |
| ARC-2 | Inside each region: **VPC** boxes; inside each VPC a grid of **AZ rows × tier columns** (Firewall · Public · Private app · Private data); subnets drawn inside cells | ☐ |
| ARC-3 | Subnet tier comes from the subnet's **effective** route table (explicit association, else the VPC main table). Default route → IGW = public; → NAT/TGW/NFW/ENI/peering = app; local only = data. NFW subnets = firewall. Tag `strataledger:tier` overrides; name tokens are only a tie-breaker between app and data | ☐ |
| ARC-4 | Multi-AZ constructs (ALB/NLB, ASG, EKS node groups, ECS services, Aurora, ElastiCache, OpenSearch, EFS, NFW, VPC Lambda) are drawn as **dashed group boxes spanning AZ rows**, with member icons aligned in one lane per group — as in the reference image | ☐ |
| ARC-5 | Left global column: Internet/Users → CloudFront, WAF (CloudFront), Route 53, Shield; IAM/Organizations summary tiles | ☐ |
| ARC-6 | Right **regional services** panel per region: S3, DynamoDB, KMS, Secrets Manager, ECR, SQS, SNS, Step Functions, CloudWatch, EventBridge, non-VPC Lambda, API Gateway — **aggregated tiles** (icon, count, top names), never 50 loose icons | ☐ |
| ARC-7 | VPC endpoints on the VPC's right edge; gateway/interface endpoints link to the matching regional tile (image: ECS → VPC Endpoint → DynamoDB/S3) | ☐ |
| ARC-8 | Every edge comes from real data: CloudFront origins, Route 53 aliases, ELB target health / ECS & ASG target-group bindings, **security-group references** (compute → data, labelled with port), TGW attachments, VPC peering, endpoint → service, NAT → IGW of the **same VPC** | ☐ |
| ARC-9 | Cross-region replication arrows between regional tiles: S3 CRR, DynamoDB global tables, KMS multi-region keys, ECR replication, cross-region VPC/TGW peering | ☐ |
| ARC-10 | Node IDs are unique, type-prefixed resource IDs/ARNs — no collisions between same-named resources | ☐ |
| ARC-11 | Neatness rules: default VPCs with no workloads hidden (listed in a footnote); empty regions skipped (listed); per-cell icon cap with "+N more" chip linking to Inventory | ☐ |
| ARC-12 | Interactions: pan/zoom/fit, account selector, jump-to-region, search highlight, click → details panel, hover highlights connected edges, toggle edge layers (traffic, data, network, egress, replication), download **SVG** and **PNG** | ☐ |
| ARC-13 | Styling follows the AWS 2023 architecture-icon palette and group styles; works in light and dark theme; exported SVG uses light theme | ☐ |

### 2.5 Report & UI (RPT)

| ID | Requirement | Status |
|---|---|---|
| RPT-1 | Inventory: add **Status** filter (SPEC §4.4); CSV includes ARN-bearing ID and tags; row click opens detail drawer | ☐ |
| RPT-2 | New **Coverage** tab: collection issues grouped by account → region → collector, with counts on the Overview | ☐ |
| RPT-3 | Security tab: combined CloudTrail check (COL-7), S3 public check uses COL-5, account-level Block Public Access shown | ☐ |
| RPT-4 | `_flatten_resources` must not mutate the scan data | ☐ |

### 2.6 Quality (QA) & documentation (DOC)

| ID | Requirement | Status |
|---|---|---|
| QA-1 | `tests/` with pytest: tier classification, node-ID uniqueness, edge derivation, layout invariants (no overlapping siblings), report escaping/offline, CLI validation, moto-backed collector tests (S3 public access, KMS rotation, service mapping) | ☐ |
| QA-2 | GitHub Actions CI: ruff + pytest on Python 3.9 – 3.12 | ☐ |
| QA-3 | `dev` optional dependency group in `pyproject.toml` | ☐ |
| DOC-1 | SPEC.md updated to 1.1.0 (correct tier count, palette, CLI flags, upgrade section), CHANGELOG, README | ☐ |

---

## 3. Architecture diagram design

### 3.1 Visual hierarchy (matches the reference image)

```text
 ┌──────────────────────────────── AWS Cloud · <alias> (<account-id>) ────────────────────────────────┐
 │                ┌─ Region us-east-1 ───────────────────────────────────────────────────────────────┐ │
 │                │ ┌─ VPC prod 10.0.0.0/16 ─────────────────────────────────────────┐  ┌────────────┐│ │
 │  ┌──────────┐  │ │          Public        Private app        Private data     EPs │  │ S3   ×12   ││ │
 │  │CloudFront│  │IGW┌─ AZ a ─────────────────────────────────────────────────┐ (S3) │  │ DynamoDB×3 ││ │
 │Users→│ WAF │──┼─▶│ │[NAT]        ┊[ECS][Spot]┊          ┊[RDS]┊            │ (DDB)│─▶│ KMS  ×4    ││ │
 │  │ Route 53 │  │ │ └────────────────────────────────────────────────────────┘      │  │ ECR  ×7    ││ │
 │  └──────────┘  │ │ ┌─ AZ b ─────────────────────────────────────────────────┐      │  └─────┬──────┘│ │
 │                │ │ │[ALB]        ┊[ECS][Spot]┊          ┊[RDS]┊            │      │        │ CRR   │ │
 │                │ │ └──────────────┊ multi-AZ ┊──────────┊─────┊────────────┘      │        │       │ │
 │                │ └────────────────────────────────────────────────────────────────┘        │       │ │
 │                └───────────────────────────────────────────────────────────────────────────┼───────┘ │
 │                ┌─ Region eu-west-1 ────────────────────────────────────────────────── …    ▼          │
 └─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Request flow reads **left → right**: Users → edge services → IGW → public tier → app tier → data tier →
VPC endpoints → regional managed services. Replication reads **top ↕ bottom** between region panels.

### 3.2 Containers

| Container | Style | Contents |
|---|---|---|
| AWS Cloud | solid `#232F3E` border, "AWS Cloud" tab with account alias/ID | global column + regions |
| Region | dashed teal `#00A4A6`, flag glyph | left gutter (TGW, VPN/DX, regional WAF, API GW), VPCs, right services panel |
| VPC | solid green `#7AA116`, VPC glyph, name + CIDR | tier header row, AZ rows, endpoint column; IGW/VGW on left border |
| Availability Zone | dashed grey `#879196` row spanning all tiers | one cell per tier |
| Subnet | public: green `#7AA116` tint; private: teal `#00A4A6` tint; firewall: red `#DD344C` tint | resource icons; header = name · CIDR |
| Group (multi-AZ) | dashed, coloured by service category (compute orange `#ED7100`, database `#C925D1`, networking `#8C4FFF`, storage `#7AA116`, security `#DD344C`) | one lane, spans its AZ rows |

### 3.3 Tier classification algorithm (ARC-3)

```
effective_rt(subnet) = explicit association ?? main route table of subnet.vpc
if tag strataledger:tier ∈ {public, app, data, firewall}  → that tier
elif subnet ∈ any Network Firewall subnet mapping             → firewall
elif default route (0.0.0.0/0 or ::/0, not blackhole) → igw-* → public
elif default route → nat-* | tgw-* | vpce-* | eni-* | i-* | pcx-* → app
else                                                          → data   (isolated)
tie-break: an "app" subnet that contains only data stores, or whose name has a
token in {db, data, database, rds, cache, isolated} and no compute → data
```

Name tokens are split on `-`, `_`, `.`, and spaces, so `republish-svc` no longer matches `pub`.

### 3.4 Placement rules

| Resource | Placement |
|---|---|
| EC2 | its subnet; grouped into the EKS group (tag `eks:cluster-name`/`aws:eks:cluster-name`) or ASG group (tag `aws:autoscaling:groupName`) when tagged; spot instances get a "Spot" sublabel; terminated instances omitted |
| NAT gateway | its subnet (loose) |
| ALB/NLB/CLB | group spanning its subnets |
| ECS service (awsvpc) | group spanning its subnets, sublabel Fargate/EC2 and desired count; non-awsvpc services go to the regional panel |
| EKS cluster | group spanning node-group subnets (fallback: cluster subnets), members = tagged nodes |
| ASG | group spanning `VPCZoneIdentifier` subnets, members = its instances |
| Lambda (VPC) | functions sharing an identical subnet set merge into one group "Lambda ×N" |
| RDS instance | subnet in its subnet group whose AZ matches the instance AZ |
| Aurora / ElastiCache / OpenSearch / Redshift / EFS / NFW | group spanning the subnets of their members/mount targets/mappings |
| VPC endpoint | VPC endpoint column, one icon per service (gateway vs interface sublabel) |
| IGW / VGW | VPC left border |
| TGW, VPN, DX, regional WAF, API Gateway | region left gutter |
| S3, DynamoDB, KMS, Secrets, ECR, SQS, SNS, Step Functions, CloudWatch, EventBridge, non-VPC Lambda | region services panel (aggregated tiles) |
| CloudFront, CloudFront WAF, Route 53, Shield, IAM, Organizations | global column |

### 3.5 Edge sources (ARC-8 / ARC-9)

| Kind (layer) | Colour / style | Derived from |
|---|---|---|
| `traffic` | solid `#38BDF8` | Users→CloudFront/Route 53/IGW; CloudFront origin domain → ALB/S3/API GW; Route 53 alias → CloudFront/ALB; IGW → internet-facing LB; LB → target (target health, ECS/ASG target-group bindings) |
| `data` | solid `#C925D1` | security-group reference: data-store SG ingress rule references a compute SG → edge compute → data, label = port |
| `network` | solid `#8C4FFF` / dashed `#F97316` | TGW attachment → VPC; VPC peering |
| `endpoint` | solid `#7AA116` | VPC endpoint → regional tile |
| `egress` (hidden by default) | dashed `#10B981` | NAT → IGW in the same VPC |
| `replication` | dashed `#E7157B`, double arrow | S3 CRR, DynamoDB replicas, KMS multi-region replicas, ECR replication, cross-region peering |
| `security` | dotted `#DD344C` | WAF → CloudFront / ALB / API GW |

Edges are routed orthogonally (horizontal–vertical–horizontal; vertical–horizontal–vertical for
stacked regions), drawn above containers and below icons, with a per-edge lane offset to reduce overlap.

### 3.6 Rendering

- Pure Python, deterministic: `diagram/model.py` (inventory → model), `diagram/layout.py` (geometry),
  `diagram/svg.py` (SVG string), `diagram/icons.py` (symbol library). No JS layout engine.
- Icons are `<symbol>` definitions referenced with `<use>`; each SVG is self-contained.
- Colours use CSS custom properties so the same SVG follows the report theme; exports inline the light theme.

---

## 4. Delivery plan

| Phase | Contents |
|---|---|
| 1 | SEC-1/2, SCN-2/3/4/6/7, CLI-1/3/5, COL-11 — safety and plumbing |
| 2 | SCN-1/5/8/9, CLI-2/4 — parallel engine, region discovery, report-time diagram |
| 3 | COL-1 … COL-10 — collector fixes and new services |
| 4 | ARC-1 … ARC-13 — diagram model, layout, SVG, interactions |
| 5 | RPT-1 … RPT-4 — report tabs |
| 6 | QA-1/2/3, DOC-1 — tests, CI, docs, version 1.1.0 |
