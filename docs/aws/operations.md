# AWS Operations Cookbook

> Day-to-day commands for deploying, observing, and tearing down the
> MindMarket AI AWS stacks. Pair with `docs/aws/phase-1-ec2.md` for the
> Phase 1 runbook and the troubleshooting recipes.

## Pre-flight (one time per machine)

```bash
# AWS CLI configured for the deploy IAM user
aws configure --profile mindmarket
aws sts get-caller-identity --profile mindmarket   # must return account 520622116862

# CDK toolchain
cd infra
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install -g aws-cdk@2

# Bootstrap once per account/region (creates CDKToolkit stack ~$0.02/mo)
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
cdk bootstrap aws://520622116862/us-east-1 --profile mindmarket \
  --context operator_ip=$(curl -s -4 ifconfig.me)
```

## Deploy

### Full stack (Phase 1 + Phase 2 together)

```bash
cd /Users/zhengdong/RiskManagement
./infra/scripts/deploy-phase-1.sh    # Foundation + Compute + EC2 bootstrap + app
cd infra && source .venv/bin/activate
cdk deploy MindMarket-Data MindMarket-Api \
  --profile mindmarket \
  --context operator_ip=$(curl -s -4 ifconfig.me) \
  --require-approval never \
  --outputs-file cdk.out/outputs-phase2.json
```

### Phase 1 only (EC2 + Streamlit)

```bash
./infra/scripts/deploy-phase-1.sh
# Prints: https://<eip-with-dashes>.nip.io
```

### Phase 2 only (Lambda APIs)

```bash
cd infra && source .venv/bin/activate
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
cdk deploy MindMarket-Data MindMarket-Api \
  --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me) \
  --require-approval never --outputs-file cdk.out/outputs-phase2.json
```

## Verify (after deploy)

```bash
# Show all stack outputs
cat infra/cdk.out/outputs-phase2.json | jq

# Phase 1: open in browser
EIP=$(jq -r '.["MindMarket-Compute"].PublicIp' infra/cdk.out/outputs.json)
echo "https://${EIP//./-}.nip.io"

# Phase 2: smoke test
API_URL=$(jq -r '.["MindMarket-Api"].ApiUrl' infra/cdk.out/outputs-phase2.json | sed 's:/$::')
KEY_ID=$(jq -r '.["MindMarket-Api"].ApiKeyId' infra/cdk.out/outputs-phase2.json)
API_KEY=$(aws apigateway get-api-key --api-key $KEY_ID --include-value \
          --profile mindmarket --query value --output text)

# Greeks (instant)
curl -sS -X POST "$API_URL/greeks" \
  -H "x-api-key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"spot":100,"strike":100,"time_to_expiry_years":1,
       "risk_free_rate":0.05,"volatility":0.2,"option_type":"call"}' | jq

# VaR (cold start ~9s, warm <1s)
curl -sS -X POST "$API_URL/var" \
  -H "x-api-key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"tickers":["A","B"],"weights":{"A":0.6,"B":0.4},
       "returns":[[0.01,0.02],[0.0,0.01],[-0.005,0.0]],
       "n_simulations":1000,"horizon_days":21,"confidence":0.95}' | jq

# Price cache (yfinance — may return empty due to upstream API drift)
curl -sS "$API_URL/price/AAPL?period=5d&interval=1d" -H "x-api-key: $API_KEY" | jq
```

## Observe

### Lambda logs

```bash
# Tail in real time
aws logs tail /aws/lambda/mindmarket-risk-calculator --profile mindmarket --since 30m --follow
aws logs tail /aws/lambda/mindmarket-options-pricer  --profile mindmarket --since 30m --follow
aws logs tail /aws/lambda/mindmarket-price-cache     --profile mindmarket --since 30m --follow

# Last error per function
for fn in risk-calculator options-pricer price-cache; do
  echo "=== $fn ==="
  aws logs filter-log-events --profile mindmarket \
    --log-group-name "/aws/lambda/mindmarket-$fn" \
    --filter-pattern '"ERROR"' \
    --start-time $(( ($(date +%s) - 3600) * 1000 )) \
    --query 'events[-3:].message' --output text 2>/dev/null
done
```

### CloudWatch metrics

```bash
# Lambda invocation count + errors per function (last 24h)
aws cloudwatch get-metric-statistics --profile mindmarket \
  --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=mindmarket-risk-calculator \
  --start-time $(date -u -v-1d +%Y-%m-%dT%H:%M:%S) \
  --end-time   $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 --statistics Sum

# API Gateway 4xx/5xx rate (last hour)
aws cloudwatch get-metric-statistics --profile mindmarket \
  --namespace AWS/ApiGateway --metric-name 5XXError \
  --dimensions Name=ApiName,Value=mindmarket-api \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
  --end-time   $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 --statistics Sum
```

### Spend so far this month

```bash
aws ce get-cost-and-usage --profile mindmarket \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity DAILY --metrics UnblendedCost \
  --query 'ResultsByTime[*].[TimePeriod.Start,Total.UnblendedCost.Amount]' \
  --output table
```

## Destroy (release credits)

```bash
# Tears down ALL MindMarket-* stacks; CDKToolkit stays
./infra/scripts/destroy.sh --force

# Verify zero residue
aws cloudformation list-stacks --profile mindmarket \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?contains(StackName,`MindMarket`)].StackName' --output text
# (empty = clean)

# Trap for the unwary: unattached EIPs cost $3.60/mo even with no EC2.
aws ec2 describe-addresses --profile mindmarket \
  --query 'Addresses[?AssociationId==null].PublicIp' --output text
# (empty = clean)
```

### Nuclear option (also drop CDKToolkit)

```bash
# Only if you're done with this account/region forever.
# Re-bootstrap takes ~40 sec next time.
aws cloudformation delete-stack --profile mindmarket --stack-name CDKToolkit
aws cloudformation wait stack-delete-complete --profile mindmarket --stack-name CDKToolkit
```

## Common slips

| Symptom | Most likely cause | Fix |
|---|---|---|
| `cdk deploy` says "current credentials could not assume role" | Bootstrap missing in this account/region | Run the bootstrap command in pre-flight |
| Lambda 502 on first call | Cold start + scipy import + container pull (~3-5 s) | Just retry; warm is < 1 s |
| `/price/*` returns empty bars | yfinance ↔ Yahoo API drift | Try a different ticker or accept until Phase 4 swaps to FMP/Polygon |
| `cdk deploy` Lambda asset push hangs | Docker Desktop not running or arm64/amd64 mismatch | Restart Docker Desktop; `platform=LINUX_AMD64` is set in code |
| `compose build requires buildx 0.17+` on EC2 | First-deploy bootstrap downloads buildx 0.18 — already fixed in code | Ensure `infra/infra/compute_stack.py` is current and re-run user-data via `cdk deploy --force MindMarket-Compute` |
| SSH timeout after a week | Residential IP changed | Re-run `deploy-phase-1.sh` (it grabs current IP) or use SSM: `aws ssm start-session --target <instance-id> --profile mindmarket` |
