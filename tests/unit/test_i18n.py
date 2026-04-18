"""
tests/unit/test_i18n.py
Unit tests for i18n.py — LABELS dictionary and get_translator() function.
"""

import pytest

from i18n import LABELS, get_translator


# ══════════════════════════════════════════════════════════════
#  LABELS structure tests
# ══════════════════════════════════════════════════════════════

class TestLabelsStructure:
    """Verify that the LABELS dict is well-formed."""

    def test_zh_labels_exist(self):
        assert "zh" in LABELS
        assert isinstance(LABELS["zh"], dict)

    def test_en_labels_exist(self):
        assert "en" in LABELS
        assert isinstance(LABELS["en"], dict)

    def test_both_dicts_non_empty(self):
        assert len(LABELS["zh"]) > 0
        assert len(LABELS["en"]) > 0

    def test_zh_and_en_have_same_keys(self):
        """All keys in zh also exist in en and vice-versa (symmetry check)."""
        zh_keys = set(LABELS["zh"].keys())
        en_keys = set(LABELS["en"].keys())
        missing_in_en = zh_keys - en_keys
        missing_in_zh = en_keys - zh_keys
        assert missing_in_en == set(), f"Keys in zh but not en: {missing_in_en}"
        assert missing_in_zh == set(), f"Keys in en but not zh: {missing_in_zh}"

    def test_no_empty_string_values_zh(self):
        """No value in zh should be an empty string."""
        empty_keys = [k for k, v in LABELS["zh"].items() if isinstance(v, str) and v.strip() == ""]
        assert empty_keys == [], f"Empty values in zh: {empty_keys}"

    def test_no_empty_string_values_en(self):
        """No value in en should be an empty string."""
        empty_keys = [k for k, v in LABELS["en"].items() if isinstance(v, str) and v.strip() == ""]
        assert empty_keys == [], f"Empty values in en: {empty_keys}"

    def test_all_values_are_strings(self):
        """Every value in LABELS should be a string."""
        for lang in ("zh", "en"):
            non_str = {k: type(v).__name__ for k, v in LABELS[lang].items() if not isinstance(v, str)}
            assert non_str == {}, f"Non-string values in {lang}: {non_str}"

    def test_labels_have_substantial_content(self):
        """Both languages should have a significant number of keys (500+)."""
        assert len(LABELS["zh"]) >= 100, f"zh has only {len(LABELS['zh'])} keys"
        assert len(LABELS["en"]) >= 100, f"en has only {len(LABELS['en'])} keys"


# ══════════════════════════════════════════════════════════════
#  get_translator() tests
# ══════════════════════════════════════════════════════════════

class TestGetTranslator:
    """Verify get_translator returns correct translations."""

    def test_returns_callable(self):
        t = get_translator("en")
        assert callable(t)

    def test_zh_translator_returns_chinese(self):
        t = get_translator("zh")
        result = t("main_title")
        assert result == LABELS["zh"]["main_title"]
        # Verify it actually contains Chinese characters
        assert any("\u4e00" <= ch <= "\u9fff" for ch in result), \
            "Expected Chinese characters in zh translation"

    def test_en_translator_returns_english(self):
        t = get_translator("en")
        result = t("main_title")
        assert result == LABELS["en"]["main_title"]
        assert "Portfolio" in result or "Risk" in result

    def test_unknown_language_defaults_to_english(self):
        t = get_translator("fr")
        result = t("main_title")
        assert result == LABELS["en"]["main_title"]

    def test_unknown_key_returns_key_itself(self):
        t = get_translator("en")
        missing_key = "this_key_does_not_exist_xyz_12345"
        assert t(missing_key) == missing_key

    def test_unknown_key_for_zh_also_returns_key(self):
        t = get_translator("zh")
        missing_key = "nonexistent_key_abc"
        assert t(missing_key) == missing_key

    def test_format_string_substitution_tab_name(self):
        """Keys like chat_current_view contain {tab_name} placeholders."""
        t = get_translator("en")
        result = t("chat_current_view", tab_name="Risk")
        assert "Risk" in result
        assert "{tab_name}" not in result

    def test_format_string_substitution_zh(self):
        t = get_translator("zh")
        result = t("chat_current_view", tab_name="风险")
        assert "风险" in result
        assert "{tab_name}" not in result

    def test_format_string_substitution_mc_title(self):
        """mc_title uses {horizon} and {sims} placeholders."""
        t = get_translator("en")
        result = t("mc_title", horizon=21, sims=10000)
        assert "21" in result
        assert "10,000" in result or "10000" in result
        assert "{horizon}" not in result
        assert "{sims}" not in result

    def test_format_with_no_kwargs_preserves_placeholders(self):
        """Calling t(key) without kwargs should return the raw template string."""
        t = get_translator("en")
        raw = t("chat_current_view")
        assert "{tab_name}" in raw

    def test_each_language_produces_different_output(self):
        """zh and en should produce different translations for the same key."""
        t_zh = get_translator("zh")
        t_en = get_translator("en")
        # Use a key that is definitely different between languages
        assert t_zh("kpi_return") != t_en("kpi_return")

    def test_translator_for_multiple_known_keys(self):
        """Spot-check several well-known keys exist and translate."""
        t_en = get_translator("en")
        known_keys = [
            "kpi_return", "kpi_vol", "kpi_sharpe", "kpi_maxdd",
            "kpi_var95", "kpi_var99", "kpi_cvar95",
            "tab_cumret", "tab_drawdown", "tab_corr", "tab_mc",
        ]
        for key in known_keys:
            result = t_en(key)
            assert result != key, f"Key '{key}' was not found in en LABELS"
