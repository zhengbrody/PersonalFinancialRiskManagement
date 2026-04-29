"""
infra/api_stack.py

REST API Gateway + 3 Lambda DockerImageFunctions + usage plan.

Routes:
    POST /var               -> risk-calculator Lambda
    POST /greeks            -> options-pricer Lambda
    GET  /price/{ticker}    -> price-cache Lambda

API key + usage plan: 1000 req/day per key (Phase 2 spec). Built into
REST API as native CDK constructs (UsagePlan + ApiKey + UsagePlanKey)
— no Lambda authorizer plumbing.

IAM: least-privilege per Lambda.
    risk-calculator   -> can READ PriceCache (future: warm-cache reads)
    options-pricer    -> can READ PriceCache (future: spot price lookup)
    price-cache       -> can READ + WRITE PriceCache (only writer)

Container Image Lambdas (per ADR-0002): cdk's DockerImageFunction handles
the build + ECR push. Build context is repo root so the Dockerfiles can
COPY libs/ from the parent directory.

Why one stack for all 3 Lambdas + the API: API Gateway resources reference
all three Lambda integrations. Splitting would force cross-stack
function ARN exports and 2x deploy time for what is essentially one
"surface area."
"""
from __future__ import annotations

import pathlib

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigw,
    aws_dynamodb as ddb,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct


# Repo root, computed once: this file is at /infra/infra/api_stack.py,
# so the repo root is two levels up.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class ApiStack(Stack):
    """REST API + 3 Lambdas + usage plan."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        price_cache_table: ddb.ITable,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Risk calculator Lambda (no DDB write needed) ──────────
        # `platform=LINUX_AMD64` forces docker buildx to cross-compile
        # for x86_64 even when the operator runs on arm64 (M-series Mac).
        # Without it: image builds for arm64, push silently succeeds, then
        # Lambda errors at first invocation with "Runtime.InvalidEntrypoint".
        # Worse: numpy/scipy may have wheels for the build arch but not
        # the deploy arch, causing the build step to fall back to compiling
        # from source and fail because the Lambda base image has no compiler.
        risk_fn = _lambda.DockerImageFunction(
            self,
            "RiskCalculatorFn",
            function_name="mindmarket-risk-calculator",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=str(_REPO_ROOT),
                file="services/risk-calculator/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            memory_size=3008,           # numpy + scipy + pandas; 3 GB gives ~2 vCPU
            timeout=Duration.seconds(30),
            architecture=_lambda.Architecture.X86_64,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "PRICE_CACHE_TABLE": price_cache_table.table_name,
            },
        )
        # Read-only on PriceCache (future-proofing for warm-cache reads)
        price_cache_table.grant_read_data(risk_fn)

        # ── Options pricer Lambda (no DDB) ────────────────────────
        opts_fn = _lambda.DockerImageFunction(
            self,
            "OptionsPricerFn",
            function_name="mindmarket-options-pricer",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=str(_REPO_ROOT),
                file="services/options-pricer/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            memory_size=512,            # Greeks are cheap; smaller mem = cheaper invokes
            timeout=Duration.seconds(15),
            architecture=_lambda.Architecture.X86_64,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # ── Price cache Lambda (only writer) ──────────────────────
        cache_fn = _lambda.DockerImageFunction(
            self,
            "PriceCacheFn",
            function_name="mindmarket-price-cache",
            code=_lambda.DockerImageCode.from_image_asset(
                directory=str(_REPO_ROOT),
                file="services/price-cache/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            memory_size=1024,
            timeout=Duration.seconds(30),       # yfinance can be slow
            architecture=_lambda.Architecture.X86_64,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "PRICE_CACHE_TABLE": price_cache_table.table_name,
            },
        )
        price_cache_table.grant_read_write_data(cache_fn)

        # ── REST API ──────────────────────────────────────────────
        api = apigw.RestApi(
            self,
            "Api",
            rest_api_name="mindmarket-api",
            description="MindMarket Phase 2 compute API",
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_burst_limit=20,
                throttling_rate_limit=10,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=False,  # don't log request bodies (privacy + cost)
                metrics_enabled=True,
            ),
            default_method_options=apigw.MethodOptions(
                api_key_required=True,
            ),
            cloud_watch_role=True,
        )

        # POST /var
        var_route = api.root.add_resource("var")
        var_route.add_method(
            "POST",
            apigw.LambdaIntegration(risk_fn, proxy=True),
        )

        # POST /greeks
        greeks_route = api.root.add_resource("greeks")
        greeks_route.add_method(
            "POST",
            apigw.LambdaIntegration(opts_fn, proxy=True),
        )

        # GET /price/{ticker}
        price_root = api.root.add_resource("price")
        price_ticker = price_root.add_resource("{ticker}")
        price_ticker.add_method(
            "GET",
            apigw.LambdaIntegration(cache_fn, proxy=True),
        )

        # ── API key + usage plan (the Phase 2 spec's throttle) ────
        # 1000 requests/day cap = ~42/hr; rate 10/sec, burst 20.
        # Ensures a misbehaving client can't drain Lambda budget.
        plan = api.add_usage_plan(
            "DefaultPlan",
            name="mindmarket-default",
            throttle=apigw.ThrottleSettings(rate_limit=10, burst_limit=20),
            quota=apigw.QuotaSettings(limit=1000, period=apigw.Period.DAY),
        )
        plan.add_api_stage(stage=api.deployment_stage)

        api_key = api.add_api_key(
            "DefaultKey",
            api_key_name="mindmarket-default-key",
        )
        plan.add_api_key(api_key)

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(
            self,
            "ApiUrl",
            value=api.url,
            description="REST API base URL (append /var, /greeks, /price/AAPL)",
        )
        CfnOutput(
            self,
            "ApiKeyId",
            value=api_key.key_id,
            description=(
                "Run `aws apigateway get-api-key --api-key <ID> --include-value` "
                "to fetch the actual key"
            ),
        )
        CfnOutput(
            self,
            "RiskFunctionName",
            value=risk_fn.function_name,
        )
        CfnOutput(
            self,
            "OptionsFunctionName",
            value=opts_fn.function_name,
        )
        CfnOutput(
            self,
            "PriceCacheFunctionName",
            value=cache_fn.function_name,
        )
