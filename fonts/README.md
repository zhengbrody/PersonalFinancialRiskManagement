# fonts/

This directory is the **preferred** location for a Unicode (CJK-capable)
TTF / OTF font used by the equity research PDF builder
(`libs/analysis/equity_pdf.py`). The file is gitignored so we don't bloat
the repo with a 10 MB binary — drop it in here at deploy time.

## Recommended font

Google **Noto Sans Simplified Chinese**, regular weight:

```bash
# inside this fonts/ directory
curl -L -o NotoSansSC-Regular.ttf \
  "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
```

(Rename the file to `NotoSansSC-Regular.ttf` even if you grabbed the
`.otf` — fpdf2 accepts both, the search path in `equity_pdf.py` looks
for either extension.)

## How the lookup works

`libs/analysis/equity_pdf.py:_resolve_cjk_font()` walks these locations,
first match wins:

1. `MINDMARKET_CJK_FONT_PATH` env var (absolute path).
2. `fonts/NotoSansSC-Regular.ttf` / `.otf` in the repo root.
3. `fonts/cjk.ttf` in the repo root (override-by-rename).
4. Common Linux production paths (Debian, Ubuntu, RHEL/AL2023 with
   `google-noto-sans-cjk-fonts` installed).
5. macOS dev paths (`PingFang.ttc`, `Hiragino Sans GB.ttc`,
   `STHeiti.ttc`).

If nothing matches, the PDF builder falls back to Helvetica + Latin-1
sanitiser (Chinese / emoji become `?`). The dashboard in the Streamlit
UI is always Unicode-correct — only the PDF cares.

## Production install (EC2 AL2023)

The cleanest path for our AWS EC2 host is the system package:

```bash
sudo dnf install -y google-noto-sans-cjk-fonts
```

That puts `/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc`
on disk; the equity PDF builder picks it up automatically on the next
script run — no app restart, no code change.
