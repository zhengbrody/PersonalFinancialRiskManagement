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
