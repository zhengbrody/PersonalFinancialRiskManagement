# Sidebar Not Showing - Troubleshooting Guide

> **HISTORICAL (2026-06-23).** Troubleshooting for the original Streamlit app
> (sidebar / session-state / `st.*` issues), retired on 2026-06-23. None of it
> applies to the Next.js + FastAPI split stack. Kept for reference only.

## Current situation
- ✅ Code review passed (the sidebar code exists and is correct)
- ✅ initial_sidebar_state="expanded" is set
- ✅ CSS does not hide the sidebar
- ❌ **Problem**: the sidebar is not visible in the browser

---

## Immediate Test Steps

### Step 1: Test the simplified version

**Run in the terminal**:
```bash
cd /Users/zhengdong/RiskManagement
streamlit run test_sidebar.py
```

**Open in the browser**: `http://localhost:8501`

**How to interpret the result**:
- ✅ If you see the left sidebar → Streamlit itself is fine, and app.py has a bug
- ❌ If there's still no sidebar → a Streamlit configuration or browser issue

---

### Step 2: Check the browser console

**Open the browser developer tools**:
- Chrome/Edge: `F12` or `Cmd+Option+I` (Mac)
- Firefox: `F12` or `Cmd+Option+I` (Mac)

**Look at the Console tab**:
- Red errors → copy them to me
- JavaScript errors → possibly a Streamlit version issue

**Look at the Network tab**:
- Refresh the page
- Check for any failed requests (shown in red)

---

### Step 3: Force-clear the cache

**Thoroughly clear the browser cache**:

**Chrome/Edge**:
1. Open `chrome://settings/clearBrowserData`
2. Time range: "All time"
3. Select: "Cached images and files", "Cookies and other site data"
4. Click "Clear data"
5. Restart the browser

**Firefox**:
1. Open `about:preferences#privacy`
2. "Cookies and Site Data" → "Clear Data"
3. Check both options
4. Clear → restart the browser

**Safari**:
1. Menu → Preferences → Privacy
2. "Manage Website Data" → "Remove All"
3. Restart the browser

---

### Step 4: Check the Streamlit version

```bash
streamlit --version
```

**Expected**: `Streamlit, version 1.28.0` or higher

**If the version is too low**:
```bash
pip install --upgrade streamlit
```

---

### Step 5: Try a different browser

If you're using Chrome, try:
- Firefox
- Safari
- Edge

Browser extensions can sometimes interfere with Streamlit.

---

### Step 6: Check the Streamlit config file

```bash
cat ~/.streamlit/config.toml
```

**If it exists, look for**:
```toml
[server]
enableCORS = false  # should be false or absent

[browser]
gatherUsageStats = false
```

**If there is a problematic config, delete it**:
```bash
rm ~/.streamlit/config.toml
```

---

### Step 7: Completely reinstall Streamlit

```bash
# Uninstall
pip uninstall streamlit -y

# Clear the cache
rm -rf ~/.streamlit

# Reinstall
pip install streamlit

# Verify
streamlit hello
```

---

## Collecting Debug Information

Please run the following commands and share the output with me:

```bash
# 1. Streamlit version
streamlit --version

# 2. Python version
python3 --version

# 3. Browser info
# (tell me manually: Chrome/Firefox/Safari + version number)

# 4. Test the simplified version
streamlit run test_sidebar.py
# then tell me whether you see the sidebar

# 5. Check for errors
python3 app.py 2>&1 | head -50
```

---

## Possible Causes

### 1. Corrupted Streamlit cache
**Symptom**: no sidebar in any Streamlit app
**Solution**: delete the `~/.streamlit` folder

### 2. Browser cache
**Symptom**: no sidebar only in this project
**Solution**: fully clear the browser cache or use incognito mode

### 3. Runtime error in app.py
**Symptom**: test_sidebar.py shows the sidebar, but app.py doesn't
**Solution**: need to review the detailed error log

### 4. Multi-page app issue
**Symptom**: Streamlit multi-page apps sometimes have odd sidebar behavior
**Solution**: check the pages/ folder

### 5. CSS conflict
**Symptom**: the sidebar is hidden by custom CSS
**Solution**: temporarily comment out all st.markdown(CSS)

---

## Quick Diagnostic Commands

```bash
cd /Users/zhengdong/RiskManagement

# Diagnostic script
python3 diagnose.py

# Test the simplified version
streamlit run test_sidebar.py

# Check app.py syntax
python3 -m py_compile app.py
```

---

## Contact Information

If none of the above works, please provide:

1. The `streamlit --version` output
2. The `python3 --version` output
3. Browser name and version
4. Whether `streamlit run test_sidebar.py` shows the sidebar
5. Any error messages in the browser Console (F12 → Console tab)
6. The full terminal output when running streamlit

I'll diagnose further based on this information!
