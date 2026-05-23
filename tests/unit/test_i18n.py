"""tests/unit/test_i18n.py — i18n compatibility shim tests.

The Chinese branch was removed (browser auto-translate handles other
languages). ``i18n.py`` is kept as a backward-compat shim so existing
``t("key")`` calls across pages keep working. These tests just verify
the English path and the "unknown language falls back to English"
behavior callers rely on.
"""

from i18n import LABELS, get_translator


class TestLabelsStructure:
    def test_en_labels_exist(self):
        assert "en" in LABELS
        assert isinstance(LABELS["en"], dict)

    def test_en_non_empty(self):
        assert len(LABELS["en"]) >= 100

    def test_no_empty_string_values(self):
        empty = [k for k, v in LABELS["en"].items() if isinstance(v, str) and not v.strip()]
        assert empty == [], f"Empty values in en: {empty}"

    def test_all_values_are_strings(self):
        non_str = {k: type(v).__name__ for k, v in LABELS["en"].items() if not isinstance(v, str)}
        assert non_str == {}, f"Non-string values: {non_str}"


class TestGetTranslator:
    def test_returns_callable(self):
        assert callable(get_translator("en"))

    def test_en_translator_returns_english(self):
        t = get_translator("en")
        assert t("main_title") == LABELS["en"]["main_title"]

    def test_unknown_language_defaults_to_english(self):
        """Crucial for backward-compat: pages that still pass `lang='zh'`
        must get English instead of a KeyError."""
        t = get_translator("zh")
        assert t("main_title") == LABELS["en"]["main_title"]

    def test_arbitrary_language_falls_back(self):
        t = get_translator("fr")
        assert t("main_title") == LABELS["en"]["main_title"]

    def test_unknown_key_returns_key_itself(self):
        t = get_translator("en")
        assert t("this_key_does_not_exist_xyz_12345") == "this_key_does_not_exist_xyz_12345"

    def test_format_string_substitution(self):
        t = get_translator("en")
        result = t("chat_current_view", tab_name="Risk")
        assert "Risk" in result
        assert "{tab_name}" not in result

    def test_format_with_no_kwargs_preserves_placeholders(self):
        t = get_translator("en")
        raw = t("chat_current_view")
        assert "{tab_name}" in raw

    def test_translator_for_multiple_known_keys(self):
        t = get_translator("en")
        for key in (
            "kpi_return",
            "kpi_vol",
            "kpi_sharpe",
            "kpi_maxdd",
            "kpi_var95",
            "kpi_var99",
            "kpi_cvar95",
            "tab_cumret",
            "tab_drawdown",
            "tab_corr",
            "tab_mc",
        ):
            assert t(key) != key, f"Missing key in en: {key}"
