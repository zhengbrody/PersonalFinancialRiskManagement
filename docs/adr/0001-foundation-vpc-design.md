# ADR-0001 — Foundation VPC design

- **Status:** Accepted
- **Date:** 2026-04-26
- **Phase:** 1 (Lift-and-shift to EC2)

## Context

The first AWS stack (`FoundationStack`) needs to provide the network and
base storage primitives that every subsequent stack will reference. Once
this is deployed, ~80 % of follow-up stacks will not modify it. So design
choices here have *long* half-lives and an outsized cost impact.

Two constraints frame everything:

1. **AWS Free Plan budget: ~$33/mo total** (over 6 months, $200 credits).
   Any standing-charge component over $5/mo competes with every other
   stack we'll add.
2. **Phase 1 runs a single EC2.** No multi-AZ HA in scope yet. A "real"
   prod design would look different — call this out so future-me doesn't
   misread it as a finished architecture.

## Decision

### 1. VPC sizing — `10.0.0.0/16` with 2 AZs

- Single VPC, four subnets total: 2 public + 2 private, one of each per
  AZ. Two AZs (`us-east-1a`, `us-east-1b`).
- CDK `Vpc` default is **3 AZs**. We override `max_azs=2`.

**Why 2 AZs, not 3.** AZs themselves are free; what costs money is what
you replicate across them:

| Per-AZ resource | Cost | We have |
|---|---|---|
| NAT gateway | $32/mo each | **0** |
| ALB target | (proportional) | 0 (Phase 1 = direct EC2) |
| Cross-AZ data transfer | $0.01/GB | minimal |

3 AZs only pays off when you have HA workloads. We have one EC2.

**Why 2 AZs, not 1.** Standard AWS hygiene: subnets are an AZ-level
construct, and even a single-EC2 design benefits from having the *option*
to fail over. Costs nothing extra to provision the second AZ's subnets
empty.

**Why `/16`, not `/24`.** Cheap; any future ECS / EKS task burst would
exhaust a `/24` of private IPs quickly. `/16` gives headroom without cost.

### 2. **Zero NAT gateways**

Outbound from `PRIVATE_WITH_EGRESS` subnets normally requires NAT
gateways at $32/mo each. Our entire monthly budget is $33. Hard no.

We use `PRIVATE_ISOLATED` subnets (no internet egress at all) for the
private tier. Phase 1 doesn't put anything in private subnets anyway —
EC2 lives in the public subnet with an Elastic IP. The private tier is
provisioned-but-empty so future stacks (RDS, ECS internal services)
don't refactor the VPC.

If we ever need outbound from private subnets:
- For AWS API access (S3, DynamoDB, Secrets Manager, etc.):
  use **VPC Endpoints** — gateway endpoints (S3, DynamoDB) are free;
  interface endpoints are ~$7.20/mo each but cheaper than NAT past 1 endpoint.
- For arbitrary internet egress: revisit the ADR. Likely answer is still
  not NAT — instead, run that workload in the public subnet behind a
  more restrictive SG, or move it to Lambda (no VPC).

### 3. Security group ingress

| Port | Source | Reason |
|---|---|---|
| 443/tcp | 0.0.0.0/0 | HTTPS, Caddy terminates TLS |
| 80/tcp | 0.0.0.0/0 | Let's Encrypt HTTP-01 ACME challenge for Caddy |
| 22/tcp | `<operator_ip>/32` | SSH for emergency access |

Operator IP is **not committed to the repo** — it's passed via
`--context operator_ip=$(curl -s -4 ifconfig.me)` at deploy time. Lives
in `.gitignored` `cdk.context.json` if the user runs `cdk context --set`.

**Future hardening (Phase 2 or 3):** replace SSH with **AWS Systems
Manager Session Manager**. SSM gives shell access without any inbound
port — better security posture, audit logs in CloudTrail, no IP allow-
list to maintain when residential IPs change. The reason we don't start
there: Phase 1's spec was explicit about SSH SG, and SSM via CDK
requires the EC2 to also have the SSM agent + IAM role + (if private)
VPC endpoints. Will tackle in ComputeStack revisit.

### 4. CloudFront logs bucket — provisioned but unused

Phase 1 doesn't deploy CloudFront. We provision the bucket now to avoid
a stack refactor in Phase 4. Empty bucket = $0; first-byte storage cost
kicks in only after CloudFront writes start.

- `block_public_access = BLOCK_ALL`
- `encryption = S3_MANAGED` (free; KMS would cost ~$1/mo)
- `enforce_ssl = True` (deny non-TLS requests via bucket policy)
- `object_ownership = OBJECT_WRITER` — required because CloudFront
  *standard* logging writes via canned ACL `log-delivery-write`.
  Switch to `BUCKET_OWNER_ENFORCED` once we move to CloudFront
  *real-time* logs (Phase 3).
- 30-day lifecycle expiration — CloudFront logs grow fast.
- `removal_policy = DESTROY` + `auto_delete_objects = True` —
  Phase 1 is a teardown-friendly env. Production would `RETAIN`.

### 5. Stack split: Foundation vs Compute

`VPC + SG + S3 logs` go in `FoundationStack`. `EC2 + EIP + IAM role`
go in `ComputeStack`. Cross-stack ref: `ComputeStack` consumes
`vpc` and `app_sg` from `FoundationStack`.

**Why separate stacks.** Iterating on EC2 user-data is the most-touched
operation in Phase 1 (debugging Docker, Caddy, CloudWatch agent
config). Each iteration is a stack update. If VPC + EC2 share a stack,
every EC2 change risks the VPC's drift detection / has slower deploy.
Splitting them: VPC is a "deploy once and forget" artifact;
ComputeStack iterates freely.

**Cost of split: zero.** Cross-stack `Fn::ImportValue` references are
free; only the mental overhead of remembering which stack owns what.

## Consequences

### Positive

- ~$0/mo standing charge for FoundationStack itself (free VPC, free SG,
  empty S3 with no KMS).
- 2 AZ headroom should we ever want HA — no migration to 3 AZs needed.
- Clean separation: someone reading the repo sees what's "boring infra"
  vs what's "the app."
- ADRs alongside code → strong interview signal ("Are Right, A Lot").

### Negative

- Operator must remember to pass `--context operator_ip=...` on every
  deploy. CDK will hard-error if missing. Mitigated by deploy script
  in `infra/scripts/deploy-phase-1.sh` (Phase 1 Step 7).
- SSH SG ingress depends on a residential IP that *will* change. When
  it does, redeploy `FoundationStack` with new IP — ~30 sec change,
  but nontrivial inconvenience. Phase 2 ADR will move us to SSM.
- `PRIVATE_ISOLATED` subnets are empty — wasted address space for
  Phase 1. Acceptable; we'd need a second VPC otherwise.

### Anticipated changes

- **Phase 2:** add VPC endpoints (S3 gateway free, DynamoDB gateway
  free, Secrets Manager interface endpoint $7.20/mo) IF we move
  Lambdas inside the VPC. Default Phase 2 plan keeps Lambdas outside.
- **Phase 3:** add SSM Session Manager IAM role to EC2; close port 22.
- **Phase 4:** turn on CloudFront standard logging → S3 bucket starts
  receiving objects.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| 1 AZ, single subnet | No future HA path; saves $0 vs 2 AZs |
| 3 AZs (CDK default) | Exposes us to per-AZ NAT bills if anyone enables NAT later by accident |
| `PRIVATE_WITH_EGRESS` for the private tier | $32/mo per NAT × 2 AZs = $64/mo, breaks budget |
| Separate VPC per stack | Cross-VPC peering is $0.01/GB and complex; no benefit |
| One mega-stack (VPC + EC2 + S3) | Slow iteration on EC2; one bad change risks the VPC |
| Hardcode SSH IP in code | Residential IP changes; would commit a private datum to git |

## References

- AWS pricing: https://aws.amazon.com/vpc/pricing/ (NAT $0.045/hr ≈ $32/mo)
- CDK `Vpc` defaults: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/Vpc.html
- Free Plan ceiling per session log: `docs/migration-log.md` 2026-04-26
