# 🧪 MindMarket AI - Feature Testing Checklist

> **HISTORICAL (2026-06-23).** Manual-test checklist for the original Streamlit
> app, retired on 2026-06-23. The split stack is verified by the automated gates
> (`pytest backend/tests` + root `pytest` + `npm test` + Playwright E2E). Kept
> for reference only.

After completing the sidebar fix, use this checklist to verify that all features work correctly.

---

## 📋 Test Steps

### Preparation
```bash
cd /Users/zhengdong/RiskManagement
pkill -9 streamlit
streamlit run app.py
```

Open your browser: `http://localhost:8501`
Hard refresh: `Cmd+Shift+R`

---

## ✅ Test Checklist

### 1️⃣ Home Page Test

**Sidebar visibility**:
- [ ] The left sidebar is fully displayed
- [ ] Includes the Language switch
- [ ] Includes the Weights JSON input box
- [ ] Includes the Parameters sliders
- [ ] Includes the Run Analysis button

**Welcome Page**:
- [ ] See the large "MindMarket AI" title
- [ ] See the Quick Start Guide (3 steps)
- [ ] See the "Try Example Portfolios" heading

**Example Portfolio buttons**:
- [ ] Click "🚀 Tech-Heavy Portfolio"
  - The Weights JSON should update to 6 tech stocks
  - The sidebar Weights input box should show the new JSON
- [ ] Click "🛡️ Balanced Portfolio"
  - The Weights JSON should update to SPY/TLT/GLD/QQQ/IWM
- [ ] Click "🌐 Crypto-Enhanced"
  - The Weights JSON should include BTC-USD and ETH-USD

**Floating AI Chat**:
- [ ] See the blue 🤖 circular button in the bottom-right corner
- [ ] The button has a pulsing glow animation
- [ ] Click the button; the chat panel slides up from the bottom
- [ ] You can type text in the input box
- [ ] Click Send or press Enter to send a message
- [ ] Receive an AI response (currently a demo: "This is a demo response...")
- [ ] Click 🤖 or the X button again to close the panel

---

### 2️⃣ Run Analysis Test

**Preparation**:
- [ ] The sidebar Weights JSON input box contains valid JSON
  ```json
  {
    "AAPL": 0.4,
    "TSLA": 0.3,
    "BTC-USD": 0.3
  }
  ```

**Run the analysis**:
- [ ] Click the sidebar's "🚀 Run Analysis" button
- [ ] See a spinner/loading indicator
- [ ] Data download begins (may take 5-30 seconds)
- [ ] **Expected result**:
  - Data download completes
  - Risk calculation completes
  - Automatically switches to the Overview tab
  - Analysis results are displayed

**If it fails**:
- Note the error message
- Check whether the tickers are valid (e.g. BTC-USD exists on Yahoo Finance)
- Check your network connection

---

### 3️⃣ Overview Tab Test

**Prerequisite**: Analysis has run successfully

**Sidebar persistence**:
- [ ] Switch from Home to the Overview tab
- [ ] The sidebar is still fully displayed
- [ ] All controls are still available

**Page content**:
- [ ] See the "AI Risk Digest"
- [ ] See the 4 core KPI cards:
  - VaR 95%
  - Sharpe Ratio
  - Max Drawdown
  - Total Return
- [ ] See the Cumulative Returns chart
- [ ] See the Portfolio Composition pie or bar chart

**Floating Chat**:
- [ ] The 🤖 button in the bottom-right corner is still visible
- [ ] Clicking it opens/closes normally

**No old Chat**:
- [ ] There is **no** old chat input box at the bottom of the page
- [ ] There is **no** "render_chat_popover" related UI

---

### 4️⃣ Risk Tab Test

**Sidebar persistence**:
- [ ] Switch to the Risk tab
- [ ] The sidebar is fully displayed

**Page content**:
- [ ] VaR Summary section
  - MC Histogram chart
  - VaR 95%, VaR 99%, CVaR 95% metrics
- [ ] Beta Analysis section
  - Beta value for each asset
  - ✓/✗ significance indicator
  - t-stat and p-value
- [ ] Stress Testing section
  - Market Shock scenario
  - **Key**: there should be no "market_shock undefined" error
  - Displays portfolio loss

**Floating Chat**:
- [ ] The 🤖 button is visible and usable

**No old Chat**:
- [ ] There is **no** old chat input box

---

### 5️⃣ Markets Tab Test

**Sidebar persistence**:
- [ ] Switch to the Markets tab
- [ ] The sidebar is fully displayed

**Page content**:
- [ ] Market Overview section
  - Current VIX value
  - Fear & Greed Index
- [ ] Yield Curve (if data is available)
- [ ] Macro News (if the API is configured)
- [ ] Fundamentals table

**Floating Chat**:
- [ ] The 🤖 button is visible

**No old Chat**:
- [ ] There is **no** old chat

---

### 6️⃣ Portfolio Tab Test

**Sidebar persistence**:
- [ ] Switch to the Portfolio tab
- [ ] The sidebar is fully displayed

**Page content**:
- [ ] Efficient Frontier chart (if implemented)
- [ ] Portfolio Optimization suggestions
- [ ] Compliance checks (single-stock / sector limits)

**Floating Chat**:
- [ ] The 🤖 button is visible

**No old Chat**:
- [ ] There is **no** old chat

---

### 7️⃣ Parameter Modification Test

**In the sidebar on any page**:
- [ ] Change the History (yr) slider → it should save to session_state
- [ ] Change MC Paths → it should save
- [ ] Change Horizon (d) → it should save
- [ ] Change the Weights JSON
- [ ] Click "Run Analysis" again → it should recalculate with the new parameters

---

### 8️⃣ Cross-Page Navigation Test

**Test scenario**:
1. [ ] Home → Overview → Risk → Markets → Portfolio
2. [ ] On every switch, the sidebar should stay visible
3. [ ] Parameter settings should stay consistent across all pages
4. [ ] The 🤖 button should be visible on all pages

---

### 9️⃣ Quick Actions Test (Sidebar collapsible menu)

**Expand "⚡ Quick Actions"**:
- [ ] Click "📋 Load Tech Portfolio"
  - The Weights JSON should update
- [ ] Click "🛡️ Load Balanced Portfolio"
  - The Weights JSON should update
- [ ] Click "🔥 Clear Cache"
  - You should see a "Cache cleared!" message

---

### 🔟 Advanced Settings Test (Sidebar collapsible menu)

**Expand "🔧 Advanced"**:
- [ ] Change Max Stock %
- [ ] Change Max Sector %
- [ ] Check "Enable Margin Monitoring"
- [ ] Settings should save to session_state

---

## 🐛 Common Troubleshooting

### Issue 1: Sidebar not showing
**Solution**:
```bash
# Clear the cache and restart
pkill -9 streamlit
rm -rf ~/.streamlit/cache
streamlit run app.py
# Hard refresh in the browser: Cmd+Shift+R
```

### Issue 2: Example Portfolio buttons unresponsive
**Check**:
- Whether the browser Console (F12) shows any errors
- Whether the Streamlit terminal shows any error messages
- Try manually pasting JSON into the Weights JSON input box

### Issue 3: Run Analysis fails
**Possible causes**:
- Invalid ticker (e.g. some crypto tickers don't exist on yfinance)
- Network issue (unable to reach Yahoo Finance)
- Malformed JSON (weights don't sum to 1)

**Solution**:
- Use standard tickers (AAPL, GOOGL, SPY, etc.)
- Check the JSON format
- Review the terminal error message

### Issue 4: Floating Chat not showing
**Check**:
- Whether the browser Console shows any JavaScript errors
- Try a different browser
- Check whether the browser is blocking certain scripts

### Issue 5: Slow data loading
**Normal**: The first run may take 5-30 seconds to download data
**Optimization**: Subsequent runs use the cache and are much faster (<3 seconds)

---

## ✅ Test Pass Criteria

**All features working**:
- ✅ Sidebar visible on all pages
- ✅ Example portfolio buttons can update weights
- ✅ Run Analysis can complete the analysis
- ✅ All 4 tabs display content correctly
- ✅ The floating chat button is visible on all pages
- ✅ There is **no** old chat popover
- ✅ Parameter changes are saved
- ✅ No errors such as "market_shock undefined"

**If there are any failures**:
1. Note exactly which test failed
2. Note the error message (browser Console + terminal)
3. Take a screenshot (if possible)
4. Let me know, and I'll fix it immediately

---

## 📊 Test Result Log

**Test date**: ___________
**Browser**: ___________
**Streamlit version**: ___________

| Test item | Pass | Fail | Notes |
|--------|------|------|------|
| 1. Home page | ☐ | ☐ | |
| 2. Run Analysis | ☐ | ☐ | |
| 3. Overview tab | ☐ | ☐ | |
| 4. Risk tab | ☐ | ☐ | |
| 5. Markets tab | ☐ | ☐ | |
| 6. Portfolio tab | ☐ | ☐ | |
| 7. Parameter modification | ☐ | ☐ | |
| 8. Cross-page navigation | ☐ | ☐ | |
| 9. Quick Actions | ☐ | ☐ | |
| 10. Advanced Settings | ☐ | ☐ | |

**Overall score**: _____ / 10

---

## 🎯 Next-Step Suggestions

### If all tests pass ✅
The project's **core features** are complete! Consider:
1. Finishing the Floating Chat's AI integration (connect a real AI backend)
2. Adding more example portfolios
3. Implementing the UI improvements in REDESIGN.md
4. Adding more risk metrics
5. Deploying to the cloud

### If there are test failures ❌
1. Note the specific failing test and error
2. Send them to me, and I'll fix them immediately
3. Re-test

---

**Let's start testing!** 🚀

When you're done, let me know:
- How many items passed
- Which items failed (if any)
- What feature you'd like to improve first
