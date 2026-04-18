# MindMarket AI -- UI/UX Redesign Proposal

## SECTION 1: CURRENT UX DIAGNOSIS

### Critical Issues

**1. Navigation overload**
7 main tabs + 18 subtabs = 25 navigation targets. Users scan tabs left-to-right and lose context after the third. The cognitive cost of finding the right view is too high for a tool people use daily.

**2. The sidebar is a control dump**
17 sidebar widgets crammed together: language toggle, portfolio loader, JSON editor, 4 sliders, a number input, an expander, API configuration, and the run button. A first-time user sees a wall of knobs before they see any data. This signals "developer tool" not "enterprise product."

**3. No visual hierarchy**
10 KPI cards of equal size, equal weight, equal border treatment. When everything is equally important, nothing is. The eye has no anchor. Bloomberg works because it has a clear primary number (the price) and everything else is secondary.

**4. 37 horizontal rules**
Each `st.markdown("---")` is a visual interruption. 37 of them across the page turns the layout into a series of disconnected blocks instead of a flowing analytical narrative.

**5. Emoji everywhere**
26+ emoji in tab names and headers. Each one competes for attention. Institutional software uses text labels and subtle iconography. Emoji signals consumer app.

**6. AI is fragmented**
Sentiment analysis is one tab, AI briefing is another tab, the chatbot is at the bottom of every page. Three separate AI surfaces with no cohesion. The user has to visit 3 places to get the AI perspective.

**7. Charts float without context**
47+ charts rendered with no consistent container, no section headers, no interpretive text pattern. A correlation heatmap appears without explaining what the user should look for. A Monte Carlo histogram appears without stating the conclusion.

**8. The brand badge is gratuitous**
A gradient pill that says "MINDMARKET AI 1.0 -- QUANTITATIVE INTELLIGENCE" at the top of every page load. This is marketing copy in an analytics workspace. It wastes vertical space and looks like a demo watermark.

**9. The first screen is empty**
Before running analysis, the user sees a title, a badge, and "Configure in sidebar then click Run Analysis." There is no onboarding, no sample data, no explanation of what the product does. First impression is a blank canvas.

**10. Configuration before insight**
The user must configure settings, load holdings, and click Run before seeing anything. Repeat users still go through this every session. The product should remember state and load automatically.

---

## SECTION 2: NEW INFORMATION ARCHITECTURE

### Design Philosophy: Decision-First Navigation

Replace 7 tabs with **4 primary views** organized around the decision workflow:

```
OVERVIEW  -->  RISK  -->  MARKETS  -->  PORTFOLIO
(what)         (why)      (context)     (action)
```

### New Navigation Structure

| # | View | Purpose | Contains (merged from) |
|---|------|---------|----------------------|
| 1 | **Overview** | Executive dashboard. "How am I doing?" | KPI summary, cumulative returns, drawdown, daily P&L, AI risk digest, margin status |
| 2 | **Risk** | Deep risk analytics. "What could go wrong?" | Monte Carlo VaR, stress testing (all 3 modes), component attribution, factor exposure, macro sensitivity, correlation, liquidity, Barra attribution |
| 3 | **Markets** | External context. "What is happening?" | VIX/Fear&Greed/yield curve, macro news, fundamentals, insider signals, technical indicators, Reddit sentiment |
| 4 | **Portfolio** | Optimization and action. "What should I do?" | Efficient frontier, Quantamental allocation, trade blotter, compliance check, cash deployment, rebalancing suggestions |

### What changes

- **"Returns & Risk" + part of "Risk Analysis"** merge into Overview (returns, drawdown) and Risk (VaR, stress)
- **"Factor & Macro"** merges into Risk (factor/macro analysis is risk analysis)
- **"Market Intelligence" + "AI Sentiment"** merge into Markets
- **"Portfolio Management"** stays but absorbs the AI briefing as an inline module
- **"AI Briefing"** becomes a floating panel accessible from any view, not a separate tab
- **Chatbot** becomes a persistent bottom drawer, not a page section
- **Historical Scenarios** moves into Risk > Stress Testing as a mode
- **Rolling Correlation** becomes a collapsible panel inside the factor section

### Default Landing Page

Overview. Always. It should answer the 5 critical questions in under 10 seconds without any clicks.

### Repeat User Workflow

1. Open app -> Overview loads with cached data from last session
2. Click "Refresh" to update prices (single button, not "Load Portfolio" + "Run Analysis")
3. Scan KPIs -> see daily P&L, risk level, any alerts
4. If alert -> click through to Risk detail
5. If rebalancing needed -> go to Portfolio
6. Chat with AI at any point via persistent drawer

---

## SECTION 3: DASHBOARD HOMEPAGE (OVERVIEW)

### Layout (top to bottom)

```
+------------------------------------------------------------------+
|  [MINDMARKET AI]                              [Refresh] [Settings]|
+------------------------------------------------------------------+
|                                                                    |
|  PORTFOLIO VALUE          DAILY P&L        VAR 95% (21d)  SHARPE |
|  $142,830                +$1,247 (+0.88%)  -8.36%         1.42   |
|  [primary, large]        [delta highlight]  [risk color]   [muted]|
|                                                                    |
+------------------------------------------------------------------+
|                                                                    |
|  [Cumulative Returns -- 2Y line chart, portfolio vs SPY]          |
|  Full width. Clean. Two lines only. No legend clutter.            |
|                                                                    |
+------------------------------------------------------------------+
|                          |                                         |
|  RISK SNAPSHOT           |  AI RISK DIGEST                        |
|  Max Drawdown: -12.3%   |  "Portfolio VaR is elevated at 8.4%    |
|  Stress Loss: -18.2%    |   driven by semiconductor concentration |
|  Margin Buffer: 28.1%   |   (42% of risk). RSI overbought on     |
|  Macro Score: 47/100    |   NVDA. Consider trimming by 3pp."     |
|                          |                                         |
+------------------------------------------------------------------+
|                                                                    |
|  TOP RISK DRIVERS                          SECTOR EXPOSURE        |
|  1. NVDA  28% VaR, RSI 78 (OB)           Semis    38%  |||||||  |
|  2. TSLA  12% VaR, Beta 1.9              Big Tech 22%  |||||    |
|  3. BTC   9% VaR, Vol 65%                Crypto   11%  |||      |
|                                                                    |
+------------------------------------------------------------------+
|  MARKET REGIME                                                     |
|  VIX: 22.4 (Elevated)  |  F&G: 28 (Fear)  |  Yield: Flat        |
+------------------------------------------------------------------+
```

### Key Principles
- **4 KPI cards max** at the top. Not 10.
- **One primary chart**. Not 5 competing charts.
- **AI digest is inline**, not in a separate tab. 3-4 sentences max.
- **Risk drivers are ranked**, not listed alphabetically.
- **Market regime is a compact strip**, not a full tab.

---

## SECTION 4: SIDEBAR REDESIGN

### New Sidebar Structure

```
[MindMarket AI logo -- text only, no gradient]

[Language: EN / CN toggle -- minimal]

--- Portfolio ---
[Load Holdings]  (single button, auto-runs analysis)
Total Value: $142,830
Leverage: 1.23x

--- Quick Settings ---
History: [2Y]     MC Paths: [10K]
Horizon: [21d]    Shock: [-10%]

[> Advanced Settings]  (collapsed expander)
   Risk-free fallback: 4.5%
   Risk limits...

[> AI Configuration]  (collapsed expander)
   Provider: [Claude / DeepSeek / Ollama]
   API Key: [****]
```

### What Changed
- **JSON editor removed** from sidebar. Weights come from portfolio_config.py or a file upload on a settings page
- **Risk-free rate, risk limits, API config** hidden in expanders (collapsed by default)
- **"Load Holdings" and "Run Analysis"** merged into one button. Loading should trigger analysis automatically
- **Sliders** condensed into a 2x2 grid using `st.columns([1,1])` inside the sidebar
- **Total widget count**: 17 -> 7 visible (rest in expanders)

---

## SECTION 5: DESIGN SYSTEM

### Color Palette (Dark Mode)

```python
TOKENS = {
    # Backgrounds
    "bg_primary":     "#0F1117",   # App background (near-black)
    "bg_surface":     "#161B22",   # Card / panel surface
    "bg_elevated":    "#1C2128",   # Elevated surface (popover, drawer)
    "bg_hover":       "#21262D",   # Hover state

    # Borders
    "border_subtle":  "rgba(139, 148, 158, 0.12)",  # Barely visible
    "border_default": "rgba(139, 148, 158, 0.20)",  # Normal borders
    "border_strong":  "rgba(139, 148, 158, 0.35)",  # Emphasis borders

    # Text
    "text_primary":   "#E6EDF3",   # Primary text (high contrast)
    "text_secondary": "#8B949E",   # Secondary / labels
    "text_tertiary":  "#484F58",   # Muted / disabled
    "text_link":      "#58A6FF",   # Interactive text

    # Accent (single brand color -- teal)
    "accent":         "#0B7285",   # Primary actions, active states
    "accent_subtle":  "rgba(11, 114, 133, 0.12)",  # Accent background

    # Semantic
    "positive":       "#2EA043",   # Gains, success, buy
    "positive_bg":    "rgba(46, 160, 67, 0.10)",
    "negative":       "#DA3633",   # Losses, risk, sell
    "negative_bg":    "rgba(218, 54, 51, 0.10)",
    "warning":        "#D29922",   # Caution, elevated
    "warning_bg":     "rgba(210, 153, 34, 0.10)",
    "neutral":        "#8B949E",   # Informational
    "neutral_bg":     "rgba(139, 148, 158, 0.08)",
}
```

### Typography

| Level | Size | Weight | Color | Use |
|-------|------|--------|-------|-----|
| Page title | 24px | 600 | text_primary | One per page |
| Section heading | 16px | 600 | text_primary | Section dividers |
| Subsection | 14px | 500 | text_primary | Within sections |
| Body | 14px | 400 | text_primary | Default text |
| Label | 12px | 500 | text_secondary | Form labels, KPI labels |
| Caption | 11px | 400 | text_tertiary | Helper text, timestamps |
| Overline | 10px | 600 | text_tertiary, uppercase, letter-spacing: 1px | Category labels |

### Spacing

```
4px   -- Tight (icon-text gap)
8px   -- Compact (within card)
12px  -- Default (between elements)
16px  -- Comfortable (card padding)
24px  -- Section gap
32px  -- Major section gap
```

### Card Style

```css
.card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 16px;
    /* NO left accent border. NO hover animation. Clean. */
}
```

### Button Hierarchy

| Level | Style | Use |
|-------|-------|-----|
| Primary | Filled accent bg, white text | "Refresh Data", "Run Analysis" |
| Secondary | Outlined, accent border | "Compute Frontier", "Fetch News" |
| Ghost | Text only, no border | "Advanced Settings", "Show Details" |

### Chart Container

```css
.chart-container {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 16px 16px 8px 16px;
    /* Title inside container, not above it */
}
```

### No:
- No left accent borders on cards
- No hover lift animations
- No gradient backgrounds
- No emoji in navigation
- No colored icon prefixes on KPIs

---

## SECTION 6: KPI CARD SYSTEM

### Tier 1: Primary KPIs (Always visible, top row)

| KPI | Label | Format | Context |
|-----|-------|--------|---------|
| Portfolio Value | "Portfolio Value" | $142,830 | Show leverage in tooltip |
| Daily P&L | "Today" | +$1,247 (+0.88%) | Green/red delta |
| VaR 95% | "Value at Risk (21d)" | -8.36% | Red if > 10% |
| Sharpe Ratio | "Sharpe" | 1.42 | Tooltip: "Rf = 4.5%, Vol = 18.2%" |

### Tier 2: Secondary KPIs (Visible on Overview, smaller)

| KPI | Where it lives |
|-----|---------------|
| Max Drawdown | Overview > Risk Snapshot panel |
| Stress Loss | Overview > Risk Snapshot panel |
| Macro Risk Score | Overview > Market Regime strip |
| Margin Distance | Overview > Risk Snapshot (only if margin exists) |
| Annual Return | Overview > Risk Snapshot panel |
| Volatility EWMA | Risk > detail section |
| VaR 99% | Risk > detail section |
| CVaR 95% | Risk > detail section |
| Avg Days to Exit | Risk > Liquidity section |

### Card Design

```
+-----------------------------+
| Portfolio Value         [i] |  <-- label: 12px, secondary color
| $142,830                    |  <-- value: 28px, primary color, semibold
| +$1,247 today              |  <-- delta: 12px, green/red
+-----------------------------+
```

- Width: 4 cards in a row (25% each)
- No icon prefixes
- No emoji
- Tooltip `[i]` for methodology explanation
- Delta text below value, not as st.metric delta (more control)

---

## SECTION 7: CHART UX

### Chart Container System

Every chart wrapped in a consistent container:

```python
def render_chart_section(title, subtitle, fig, insight=None):
    """Standard chart presentation."""
    st.markdown(f'<p style="font-size:14px;font-weight:600;margin:0">{title}</p>', ...)
    if subtitle:
        st.markdown(f'<p style="font-size:12px;color:#8B949E;margin:0 0 8px 0">{subtitle}</p>', ...)
    render_plotly(fig)
    if insight:
        st.caption(f"Insight: {insight}")
```

### Chart Rules

| Rule | Implementation |
|------|---------------|
| Max 2 charts visible without scrolling | Use expanders for secondary charts |
| Title inside chart area, not above | Use Plotly layout.title |
| No legend for <= 2 series | Hide legend, use inline labels |
| Muted gridlines | rgba(139, 148, 158, 0.08) |
| Consistent axis formatting | % for returns, $ for values, dates formatted |
| Heatmaps | Use diverging palette centered on 0, not full rainbow |
| Multi-line charts > 5 lines | Default to top-5 + portfolio, expandable to all |
| Annotations | Max 2 per chart (VaR lines on MC, current portfolio on frontier) |

### Chart Pairing

Every analytical chart should be paired with a one-sentence insight below it:

```
[Correlation Heatmap]
Insight: NVDA-TSM correlation is 0.82 -- consider this a single position for risk purposes.
```

---

## SECTION 8: AI EXPERIENCE REDESIGN

### Three AI Surfaces

**1. Inline AI Digest (on every view)**
A compact 3-4 sentence summary at the top of each view, generated from the relevant data section. Not a separate tab. Format:

```
+------------------------------------------------------------------+
| AI  "Portfolio risk is elevated. VaR 95% at 8.4% is above your  |
|      historical average of 6.2%. Primary driver: semiconductor    |
|      concentration. NVDA RSI at 78 suggests overbought entry."   |
+------------------------------------------------------------------+
```

- Light background tint (accent_subtle)
- Small "AI" label prefix
- No avatar, no chat bubble styling
- Timestamp: "Updated 2 min ago"
- Source: "Based on: EWMA VaR, RSI(14), sector weights"

**2. AI Command Bar (replaces bottom chatbot)**
A persistent input bar at the bottom of every page (like Spotlight / Command-K):

```
+------------------------------------------------------------------+
| Ask AI: "What happens if rates rise 100bp?"            [Enter]   |
+------------------------------------------------------------------+
```

- Always visible, minimal footprint
- Expands into a side panel when activated
- Responses appear in a slide-over panel, not inline
- Context-aware: knows which view you're on

**3. AI Briefing (on-demand, in Portfolio view)**
Not a separate tab. A button on the Portfolio view: "Generate Morning Brief"
Opens in a modal/panel with the full briefing. Exportable.

### Trust Signals

- Every AI output shows: model used, timestamp, data sources referenced
- Quantitative claims link to the chart that produced them
- "AI-generated" label on all AI content (small, gray, bottom-right)

---

## SECTION 9: PAGE-BY-PAGE LAYOUTS

### View 1: OVERVIEW

**Goal**: Answer "How is my portfolio doing right now?" in 10 seconds.

```
[Header: MindMarket AI + Refresh + Settings]
[4 Primary KPIs: Value | Today P&L | VaR | Sharpe]
[Cumulative Returns chart -- portfolio vs benchmark, 2Y]
[Two-column row:]
  [Left: Risk Snapshot -- 5 secondary metrics in compact list]
  [Right: AI Risk Digest -- 3-4 sentence summary]
[Two-column row:]
  [Left: Top Risk Drivers -- ranked table, 5 rows]
  [Right: Sector Exposure -- horizontal bar chart]
[Market Regime Strip: VIX | F&G | Yield Curve Status]
```

**Primary CTA**: "View Detailed Risk" (links to Risk view)
**Default visible**: Everything above
**Collapsed**: None (this page is the executive summary)

---

### View 2: RISK

**Goal**: Deep-dive into "What could go wrong and why?"

```
[Section: Value at Risk]
  [MC Distribution histogram + VaR/CVaR metrics sidebar]

[Section: Stress Testing]
  [Mode selector: Market Shock | Macro Scenario | Black Swan]
  [Stress result + waterfall chart]
  [Collapsible: Stress Matrix table]

[Section: Risk Attribution]
  [Treemap (primary) + Component VaR table (secondary, collapsed)]

[Section: Factor Exposure]
  [6-factor beta bar chart + interpretation callouts]
  [Collapsible: Per-asset factor heatmap]

[Section: Additional Analysis]
  [Collapsible: Correlation matrix]
  [Collapsible: Macro sensitivity radar + interpretation]
  [Collapsible: Rolling correlation]
  [Collapsible: Liquidity risk]
  [Collapsible: Barra PCA attribution]
```

**Primary CTA**: "Run Stress Test" (within stress section)
**Default visible**: VaR, Stress, Attribution, Factor
**Collapsed**: Correlation, Macro detail, Rolling, Liquidity, Barra

---

### View 3: MARKETS

**Goal**: "What is happening in the world that affects me?"

```
[Section: Market Regime]
  [VIX gauge + F&G gauge + Yield Curve chart -- in a row]
  [AI Market Summary: 2-sentence macro context]

[Section: News & Sentiment]
  [Macro news feed -- compact list, 10 items]
  [Reddit FOMO panel -- top 5 tickers if available]

[Section: Holdings Intelligence]
  [Fundamentals table with DCF + insider + technicals integrated]
  [Per-stock sentiment tear sheets (collapsible per stock)]
```

**Primary CTA**: "Refresh Market Data"
**Default visible**: Market Regime, News
**Collapsed**: Individual stock tear sheets

---

### View 4: PORTFOLIO

**Goal**: "What should I do?"

```
[Section: Current Allocation]
  [Sector pie + weight table side by side]

[Section: Optimization]
  [Efficient Frontier chart]
  [3-column weight comparison: Current | Optimal | AI-Adjusted]
  [Compliance check results (inline, not a gate)]

[Section: Trade Orders]
  [Trade Blotter table -- the actionable output]
  [Export button]

[Section: Margin Monitor]
  [Gauge + scenario table (collapsed if no margin)]

[Section: Cash Deployment]
  [Collapsible: What-if simulator]
```

**Primary CTA**: "Generate Trade Orders"
**Default visible**: Allocation, Optimization, Trade Orders
**Collapsed**: Margin, Cash Deployment

---

## SECTION 10: STREAMLIT IMPLEMENTATION GUIDANCE

### Layout Patterns

**Page wrapper**:
```python
def render_page(title, subtitle=None):
    st.markdown(f'<h2 style="margin:0;font-weight:600">{title}</h2>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p style="color:#8B949E;margin:0 0 24px 0">{subtitle}</p>', unsafe_allow_html=True)
```

**Section wrapper**:
```python
def render_section(title, collapsed=False):
    if collapsed:
        return st.expander(title, expanded=False)
    st.markdown(f'<p style="font-size:16px;font-weight:600;margin:24px 0 12px 0">{title}</p>', unsafe_allow_html=True)
    return st.container()
```

**KPI card (custom HTML instead of st.metric)**:
```python
def render_kpi(label, value, delta=None, delta_color="neutral"):
    color_map = {"positive": "#2EA043", "negative": "#DA3633", "neutral": "#8B949E"}
    delta_html = f'<div style="font-size:12px;color:{color_map[delta_color]}">{delta}</div>' if delta else ""
    st.markdown(f'''
    <div style="background:#161B22;border:1px solid rgba(139,148,158,0.12);border-radius:8px;padding:16px">
        <div style="font-size:12px;color:#8B949E;font-weight:500">{label}</div>
        <div style="font-size:28px;font-weight:600;color:#E6EDF3;margin:4px 0">{value}</div>
        {delta_html}
    </div>''', unsafe_allow_html=True)
```

**Chart section**:
```python
def render_chart(title, fig, insight=None, subtitle=None):
    with st.container():
        render_plotly(fig)
        if insight:
            st.caption(insight)
```

### Navigation with st.tabs
4 tabs max. No emoji in tab names. Plain text:

```python
tab_overview, tab_risk, tab_markets, tab_portfolio = st.tabs([
    "Overview", "Risk", "Markets", "Portfolio"
])
```

### Progressive Disclosure
Use `st.expander` for all secondary content. Default collapsed. Consistent labeling: "Show detailed [X]"

### Session State
- Cache analysis results aggressively
- Auto-load last portfolio on app start
- Remember which view the user was on

### Avoid
- Nested st.tabs (2 levels max)
- st.markdown("---") as section dividers (use spacing instead)
- st.metric for KPIs (use custom HTML for control)
- Emojis in any structural element

---

## SECTION 11: CODE REFACTOR PLAN

### New Module Structure

```
app.py                  # Main app: routing, session state, sidebar
ui/
  tokens.py             # Design tokens (colors, spacing, fonts)
  components.py         # render_kpi, render_section, render_chart, render_ai_digest
  layout.py             # render_page, render_sidebar, render_nav
views/
  overview.py           # Overview page renderer
  risk.py               # Risk page renderer
  markets.py            # Markets page renderer
  portfolio.py          # Portfolio page renderer
```

### Centralized Tokens (tokens.py)

```python
CLR = {
    "bg": "#0F1117",
    "surface": "#161B22",
    "border": "rgba(139, 148, 158, 0.12)",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "accent": "#0B7285",
    "positive": "#2EA043",
    "negative": "#DA3633",
    "warning": "#D29922",
}
```

### Reusable Components (components.py)

```python
def render_kpi(label, value, delta=None, delta_color="neutral"): ...
def render_section(title, collapsed=False): ...
def render_chart(title, fig, insight=None): ...
def render_ai_digest(text, sources=None, timestamp=None): ...
def render_metric_row(metrics: list[dict]): ...
def render_risk_badge(level: str): ...  # "low" | "medium" | "high" | "critical"
```

### What NOT to refactor
- risk_engine.py -- pure computation, no UI
- data_provider.py -- data layer, no UI
- market_intelligence.py -- data layer (only format functions touch UI)
- i18n.py -- keep as-is but remove emoji from label values

---

## SECTION 12: FINAL DELIVERABLE

### A. New Navigation

```
Overview  |  Risk  |  Markets  |  Portfolio
```

### B. Page Map

```
Overview
  - 4 KPIs
  - Cumulative Returns chart
  - Risk Snapshot + AI Digest
  - Top Risk Drivers + Sector Exposure
  - Market Regime strip

Risk
  - VaR Section (MC + metrics)
  - Stress Testing (3 modes)
  - Risk Attribution (treemap)
  - Factor Exposure (6-factor bar)
  - [Collapsed] Correlation, Macro, Rolling, Liquidity, Barra

Markets
  - Market Regime (VIX + F&G + Yield)
  - News Feed + Reddit FOMO
  - [Collapsed] Per-stock Tear Sheets

Portfolio
  - Current Allocation
  - Optimization (Frontier + Comparison + Compliance)
  - Trade Blotter
  - [Collapsed] Margin, Cash Deployment
```

### C. Design System Summary

```
Background:    #0F1117 / #161B22 / #1C2128
Text:          #E6EDF3 / #8B949E / #484F58
Accent:        #0B7285
Semantic:      Green #2EA043 / Red #DA3633 / Yellow #D29922
Borders:       rgba(139, 148, 158, 0.12)
Border-radius: 8px
Font:          System default (Inter if available)
No emoji. No gradients. No hover animations. No left-accent borders.
```

### D. High-Priority UI Changes

1. Reduce tabs from 7 to 4
2. Remove all emoji from navigation
3. Remove brand gradient badge
4. Collapse secondary KPIs into panels
5. Hide advanced settings behind expanders
6. Merge "Load" + "Run" into single action
7. Add AI digest inline on Overview
8. Remove 37 horizontal rules, use spacing
9. Add chart insight captions
10. Implement custom KPI cards (not st.metric)

### E. Phased Implementation Plan

**Phase 1: Quick Wins (1 day)**
- Remove emoji from tab names
- Remove brand badge
- Collapse sidebar: merge load+run, hide advanced in expanders
- Remove horizontal rules, add CSS spacing
- Reduce to 4 main tabs
- Remove secondary KPI row (move to panels)

**Phase 2: Structural (2-3 days)**
- Implement custom KPI cards via HTML
- Create chart container system
- Merge views per new IA
- Add AI digest to Overview
- Move chatbot to persistent bottom bar
- Implement collapsible sections for secondary analytics

**Phase 3: Polish (2-3 days)**
- Apply full design token system
- Custom CSS for cards, borders, typography
- Chart pairing with insight text
- Trust signals on AI outputs
- Loading states and empty states
- Mobile responsive refinements
- Onboarding: sample portfolio for first-time users

---

## BONUS: SAMPLE WIREFRAMES

### Homepage Text Wireframe

```
+------------------------------------------------------------------+
|  MindMarket AI                            [Refresh] [Settings]    |
+------------------------------------------------------------------+
|                                                                    |
|  Portfolio Value       Today           VaR 95% (21d)    Sharpe   |
|  $142,830             +$1,247 (0.88%)  -8.36%           1.42    |
|                                                                    |
+------------------------------------------------------------------+
|                                                                    |
|  PERFORMANCE                                                       |
|  [--- 2Y cumulative return line chart: Portfolio vs SPY ---]      |
|  Insight: Portfolio returned +18.4% vs SPY +22.1% over 2 years.  |
|                                                                    |
+------------------------------------------------------------------+
|                              |                                     |
|  RISK SNAPSHOT               |  AI RISK DIGEST                    |
|  Annual Return     +12.4%   |  Portfolio VaR is elevated at      |
|  Volatility EWMA   18.2%   |  8.4%, above historical avg of     |
|  Max Drawdown      -12.3%   |  6.2%. Semiconductor exposure      |
|  Stress Loss       -18.2%   |  drives 42% of total risk.         |
|  Margin Buffer      28.1%   |  Consider trimming NVDA by 3pp.    |
|                              |                                     |
+------------------------------------------------------------------+
|                              |                                     |
|  TOP RISK CONTRIBUTORS       |  SECTOR ALLOCATION                 |
|  # Ticker  VaR%   Signal    |  Semiconductors  38%  ||||||||     |
|  1 NVDA    28.1%  RSI:78    |  Big Tech        22%  |||||        |
|  2 TSLA    12.3%  Beta:1.9  |  Crypto          11%  |||          |
|  3 BTC     9.4%   Vol:65%   |  Fintech          8%  ||           |
|  4 META    7.2%   --        |  Other            21%  ||||        |
|  5 GOOGL   6.8%   --        |                                     |
|                              |                                     |
+------------------------------------------------------------------+
|  MARKET REGIME                                                     |
|  VIX: 22.4 Elevated  |  Fear & Greed: 28 Fear  |  Curve: Flat   |
+------------------------------------------------------------------+
|  Ask AI: [___________________________________________] [Enter]    |
+------------------------------------------------------------------+
```

### Sidebar Text Wireframe

```
+------------------------+
|  MindMarket AI         |
|  [EN] [CN]             |
+------------------------+
|                        |
|  PORTFOLIO             |
|  [Refresh Data]        |
|  Value: $142,830       |
|  Leverage: 1.23x       |
|                        |
+------------------------+
|                        |
|  PARAMETERS            |
|  History   [2Y]        |
|  MC Paths  [10K]       |
|  Horizon   [21d]       |
|  Shock     [-10%]      |
|                        |
|  > Advanced Settings   |
|  > AI Configuration    |
|                        |
+------------------------+
```

### Dark Mode Token CSS

```css
:root {
    --bg-primary: #0F1117;
    --bg-surface: #161B22;
    --bg-elevated: #1C2128;
    --border-subtle: rgba(139, 148, 158, 0.12);
    --border-default: rgba(139, 148, 158, 0.20);
    --text-primary: #E6EDF3;
    --text-secondary: #8B949E;
    --text-tertiary: #484F58;
    --accent: #0B7285;
    --positive: #2EA043;
    --negative: #DA3633;
    --warning: #D29922;
    --radius: 8px;
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 12px;
    --space-lg: 16px;
    --space-xl: 24px;
    --space-2xl: 32px;
}
```
