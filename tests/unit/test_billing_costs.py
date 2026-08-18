import pytest

from libs.billing.costs import (
    estimate_cost_usd,
    estimate_llm_event,
    estimate_tokens,
    normalize_provider,
)


def test_estimate_tokens_uses_four_chars_per_token():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_normalize_provider_from_provider_or_model():
    assert normalize_provider("Anthropic Claude", "claude-sonnet") == "anthropic"
    assert normalize_provider("DeepSeek API", "deepseek-chat") == "deepseek"
    assert normalize_provider("Ollama (Local)", "llama3") == "ollama"


def test_estimate_cost_usd_for_anthropic():
    assert (
        estimate_cost_usd(
            "anthropic",
            "claude-sonnet",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )
        == 18.0
    )


def test_estimate_cost_usd_uses_haiku_model_pricing():
    assert (
        estimate_cost_usd(
            "anthropic",
            "claude-haiku-4-5",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )
        == 6.0
    )


def test_estimate_llm_event_uses_max_tokens_before_response():
    event = estimate_llm_event(
        prompt="hello world",
        system="system",
        provider="anthropic",
        model="claude-sonnet",
        max_tokens=100,
    )
    assert event["estimated"] is True
    assert event["tokens_out"] == 100
    assert event["cost_usd"] > 0


def test_estimate_llm_event_uses_response_tokens_when_available():
    event = estimate_llm_event(
        prompt="hello world",
        provider="anthropic",
        model="claude-sonnet",
        max_tokens=100,
        response_text="short answer",
    )
    assert event["estimated"] is False
    assert event["tokens_out"] == estimate_tokens("short answer")


def test_v4_models_are_priced_and_cheaper_than_the_model_they_replaced():
    """Without an entry, cost accounting silently falls back to the coarse
    provider-level rate. v4-flash replaced deepseek-chat and is cheaper even at
    DeepSeek's peak (2x off-peak) cache-miss rates, which is what we record —
    an estimate must never understate."""
    from libs.billing.costs import MODEL_PRICING_BY_MODEL

    old = MODEL_PRICING_BY_MODEL["deepseek-chat"]
    flash = MODEL_PRICING_BY_MODEL["deepseek-v4-flash"]
    pro = MODEL_PRICING_BY_MODEL["deepseek-v4-pro"]

    assert flash.input_per_million < old.input_per_million
    assert flash.output_per_million < old.output_per_million
    assert pro.input_per_million > flash.input_per_million
    assert pro.output_per_million > flash.output_per_million


def test_v4_cost_is_estimated_from_the_model_not_the_provider_fallback():
    from libs.billing.costs import estimate_cost_usd

    flash = estimate_cost_usd("deepseek", "deepseek-v4-flash", tokens_in=1_000_000, tokens_out=0)
    provider_rate = estimate_cost_usd(
        "deepseek", "unknown-model", tokens_in=1_000_000, tokens_out=0
    )
    assert flash == pytest.approx(0.44)
    assert flash != provider_rate, "the per-model entry must win over the provider default"
