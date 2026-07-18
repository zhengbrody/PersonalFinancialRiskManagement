#!/usr/bin/env bash
# scripts/cloudwatch-alarms.sh — alarms-as-code for the metrics the box ALREADY
# ships (CloudWatch Agent → namespace MindMarket/EC2, installed by the Phase-1
# bootstrap; see infra/infra/compute_stack.py). Creates the three alarms the
# hardening backlog specified:
#
#   1. disk_used_percent > 90                   (disk creep = this box's
#   2. mem_used_percent  > 90 for 15 minutes     signature failure mode)
#   3. StatusCheckFailed_System > 0             (+ EC2 auto-recover action)
#
# Idempotent: `put-metric-alarm` upserts by alarm name — safe to re-run after
# threshold tweaks. Run from an operator machine with the `mindmarket` AWS CLI
# profile (owner-side; the agent classifier blocks prod-infra mutation):
#
#   ./scripts/cloudwatch-alarms.sh you@example.com
#
# First run prints a "confirm subscription" note — click the link in the email
# SNS sends, or the alarms fire into the void.
set -euo pipefail

EMAIL="${1:-}"
PROFILE="${AWS_PROFILE:-mindmarket}"
REGION="${AWS_REGION:-us-east-1}"
INSTANCE_ID="${INSTANCE_ID:-i-027d42e3eb0338b9d}"
NAMESPACE="MindMarket/EC2"
TOPIC_NAME="mindmarket-alarms"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }

echo "== SNS topic (idempotent) =="
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query TopicArn --output text)
echo "topic: $TOPIC_ARN"
if [ -n "$EMAIL" ]; then
  aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email \
    --notification-endpoint "$EMAIL" >/dev/null
  echo "subscribed $EMAIL — CONFIRM via the email SNS just sent (once)."
fi

# The CW agent publishes host-level dimensions (host / path / device / fstype
# — it has NO append_dimensions:{InstanceId} in the bootstrap config), and the
# hostname changes if the instance is ever rebuilt. DISCOVER the live
# dimension sets instead of hardcoding them, so the alarms always bind to the
# series that actually exists.
make_alarm_from_live_metric() {
  local metric="$1" alarm_name="$2" threshold="$3" periods="$4" description="$5"
  local dims
  dims=$(aws cloudwatch list-metrics --namespace "$NAMESPACE" --metric-name "$metric" \
    --query 'Metrics[0].Dimensions' --output json)
  if [ "$dims" = "null" ] || [ -z "$dims" ]; then
    echo "WARN: no live series for $NAMESPACE/$metric — is the CW agent running? Skipping $alarm_name."
    return 0
  fi
  aws cloudwatch put-metric-alarm \
    --alarm-name "$alarm_name" \
    --alarm-description "$description" \
    --namespace "$NAMESPACE" \
    --metric-name "$metric" \
    --dimensions "$dims" \
    --statistic Average \
    --period 300 \
    --evaluation-periods "$periods" \
    --threshold "$threshold" \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data breaching \
    --alarm-actions "$TOPIC_ARN" \
    --ok-actions "$TOPIC_ARN"
  echo "alarm: $alarm_name ($metric > $threshold, ${periods}x5m)"
}

echo "== disk > 90% (any 5-min average) =="
make_alarm_from_live_metric "disk_used_percent" "mindmarket-disk-over-90" 90 1 \
  "Root disk over 90% on the MindMarket box — prune images / investigate log growth before the next deploy fails."

echo "== memory > 90% sustained 15 min =="
make_alarm_from_live_metric "mem_used_percent" "mindmarket-mem-over-90-15m" 90 3 \
  "Memory over 90% for 15 minutes on the t3.micro — the box's signature pre-outage signal."

echo "== EC2 system status check (+ auto-recover) =="
aws cloudwatch put-metric-alarm \
  --alarm-name "mindmarket-system-status-failed" \
  --alarm-description "AWS-side host failure for the MindMarket instance — auto-recover migrates it to healthy hardware." \
  --namespace AWS/EC2 \
  --metric-name StatusCheckFailed_System \
  --dimensions Name=InstanceId,Value="$INSTANCE_ID" \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data missing \
  --alarm-actions "$TOPIC_ARN" "arn:aws:automate:${REGION}:ec2:recover"
echo "alarm: mindmarket-system-status-failed (auto-recover armed)"

echo
echo "Done. Verify in the console: CloudWatch → Alarms (3 alarms, OK state)."
