"""
Stripe webhook Lambda handler.

Configure in Stripe Dashboard as the endpoint for:
  - checkout.session.completed
  - customer.subscription.created
  - customer.subscription.updated
  - customer.subscription.deleted

Required env vars:
  STRIPE_WEBHOOK_SECRET
  SUPABASE_URL
  SUPABASE_SERVICE_KEY
  STRIPE_BASIC_PRICE_ID
  STRIPE_PRO_PRICE_ID
"""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from libs.billing.stripe_sync import handle_stripe_event  # noqa: E402


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _header(headers: dict[str, Any], name: str) -> str:
    lname = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == lname:
            return value
    return ""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        return _response(500, {"error": "STRIPE_WEBHOOK_SECRET not configured"})

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    sig_header = _header(event.get("headers") or {}, "stripe-signature")
    if not sig_header:
        return _response(400, {"error": "Missing stripe-signature header"})

    try:
        import stripe

        stripe_event = stripe.Webhook.construct_event(body, sig_header, secret)
    except Exception as exc:
        return _response(400, {"error": f"Invalid Stripe webhook: {exc}"})

    try:
        result = handle_stripe_event(stripe_event)
    except Exception as exc:
        return _response(500, {"error": f"Webhook sync failed: {exc}"})

    return _response(200, {"ok": True, "result": result})
