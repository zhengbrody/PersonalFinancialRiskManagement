"""
infra/data_stack.py

DynamoDB table for the price cache. Owned alone in this stack so:
  - Schema changes don't force ApiStack redeploys
  - Lambdas read the table NAME via a CFN export, not a CDK construct
    reference, so the API can be redeployed without touching the table

Per ADR-0002 single-table key design:
    pk = "TICKER#<symbol>"
    sk = "BAR#<interval>#<period>"     e.g.  BAR#1d#1mo
    payload = {"bars": [...]}
    expiresAt = epoch seconds (TTL attribute)

On-demand billing (PAY_PER_REQUEST): no provisioned capacity to size
or auto-scale. At our Phase 2 read volume (<100K reads/mo) we're firmly
in DynamoDB's free tier; provisioned would hit the 25 RCU/25 WCU minimum
and burn $1+/mo whether we use it or not.

No GSI in Phase 2. ADR-0002 flagged the cross-sectional query
("all tickers' close on date Y") as not yet in the product surface;
adding the GSI doubles write cost and is a one-line change when needed.
"""
from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as ddb,
)
from constructs import Construct


class DataStack(Stack):
    """DynamoDB resources for the MindMarket platform."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.price_cache = ddb.Table(
            self,
            "PriceCache",
            table_name="MindMarketPriceCache",  # stable name → easier to reference
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expiresAt",
            point_in_time_recovery=False,  # cache is regenerable; PITR is wasted spend
            # Phase 2 is teardown-friendly. Production would RETAIN.
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(
            self,
            "PriceCacheTableName",
            value=self.price_cache.table_name,
            export_name="MindMarket-PriceCacheTableName",
        )
        CfnOutput(
            self,
            "PriceCacheTableArn",
            value=self.price_cache.table_arn,
            export_name="MindMarket-PriceCacheTableArn",
        )
