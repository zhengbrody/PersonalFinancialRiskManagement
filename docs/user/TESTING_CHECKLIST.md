# 🧪 MindMarket AI - 功能测试清单

完成sidebar修复后，使用此清单验证所有功能是否正常工作。

---

## 📋 测试步骤

### 准备工作
```bash
cd /Users/zhengdong/RiskManagement
pkill -9 streamlit
streamlit run app.py
```

打开浏览器: `http://localhost:8501`
强制刷新: `Cmd+Shift+R`

---

## ✅ 测试清单

### 1️⃣ 主页 (Home) 测试

**Sidebar可见性**:
- [ ] 左侧sidebar完整显示
- [ ] 包含Language切换
- [ ] 包含Weights JSON输入框
- [ ] 包含Parameters滑块
- [ ] 包含Run Analysis按钮

**Welcome Page**:
- [ ] 看到"MindMarket AI"大标题
- [ ] 看到Quick Start Guide (3个步骤)
- [ ] 看到"Try Example Portfolios"标题

**Example Portfolio按钮**:
- [ ] 点击"🚀 Tech-Heavy Portfolio"
  - Weights JSON应该更新为6个科技股
  - Sidebar的Weights输入框应该显示新的JSON
- [ ] 点击"🛡️ Balanced Portfolio"
  - Weights JSON应该更新为SPY/TLT/GLD/QQQ/IWM
- [ ] 点击"🌐 Crypto-Enhanced"
  - Weights JSON应该包含BTC-USD和ETH-USD

**Floating AI Chat**:
- [ ] 右下角看到蓝色🤖圆形按钮
- [ ] 按钮有脉冲光晕动画
- [ ] 点击按钮，聊天面板从下方滑出
- [ ] 可以在输入框输入文字
- [ ] 点击Send或按Enter发送消息
- [ ] 收到AI响应（目前是demo："This is a demo response..."）
- [ ] 再次点击🤖或X按钮关闭面板

---

### 2️⃣ Run Analysis测试

**准备**:
- [ ] 在Sidebar的Weights JSON输入框中有有效的JSON
  ```json
  {
    "AAPL": 0.4,
    "TSLA": 0.3,
    "BTC-USD": 0.3
  }
  ```

**执行分析**:
- [ ] 点击Sidebar的"🚀 Run Analysis"按钮
- [ ] 看到spinner/loading提示
- [ ] 数据下载开始（可能需要5-30秒）
- [ ] **期望结果**:
  - 数据下载完成
  - 风险计算完成
  - 自动跳转到Overview标签页
  - 看到分析结果

**如果失败**:
- 记录错误信息
- 检查ticker是否有效（如BTC-USD在Yahoo Finance存在）
- 检查网络连接

---

### 3️⃣ Overview标签页测试

**前提**: 已成功运行分析

**Sidebar持久性**:
- [ ] 从Home切换到Overview标签
- [ ] Sidebar仍然完整显示
- [ ] 所有controls仍然可用

**页面内容**:
- [ ] 看到"AI Risk Digest"（AI风险摘要）
- [ ] 看到4个核心KPI卡片：
  - VaR 95%
  - Sharpe Ratio
  - Max Drawdown
  - Total Return
- [ ] 看到Cumulative Returns图表
- [ ] 看到Portfolio Composition饼图或条形图

**Floating Chat**:
- [ ] 右下角🤖按钮仍然可见
- [ ] 点击能正常打开/关闭

**无旧Chat**:
- [ ] 页面底部**没有**旧的chat输入框
- [ ] **没有**"render_chat_popover"相关UI

---

### 4️⃣ Risk标签页测试

**Sidebar持久性**:
- [ ] 切换到Risk标签
- [ ] Sidebar完整显示

**页面内容**:
- [ ] VaR Summary部分
  - MC Histogram图表
  - VaR 95%, VaR 99%, CVaR 95%指标
- [ ] Beta Analysis部分
  - 每个资产的beta值
  - ✓/✗ 显著性指标
  - t-stat和p-value
- [ ] Stress Testing部分
  - Market Shock场景
  - **关键**: 不应该有"market_shock undefined"错误
  - 显示portfolio loss

**Floating Chat**:
- [ ] 🤖按钮可见并可用

**无旧Chat**:
- [ ] **没有**旧的chat输入框

---

### 5️⃣ Markets标签页测试

**Sidebar持久性**:
- [ ] 切换到Markets标签
- [ ] Sidebar完整显示

**页面内容**:
- [ ] Market Overview部分
  - VIX当前值
  - Fear & Greed Index
- [ ] Yield Curve（如果数据可用）
- [ ] Macro News（如果API配置）
- [ ] Fundamentals表格

**Floating Chat**:
- [ ] 🤖按钮可见

**无旧Chat**:
- [ ] **没有**旧chat

---

### 6️⃣ Portfolio标签页测试

**Sidebar持久性**:
- [ ] 切换到Portfolio标签
- [ ] Sidebar完整显示

**页面内容**:
- [ ] Efficient Frontier图表（如果实现）
- [ ] Portfolio Optimization建议
- [ ] Compliance检查（单股/行业限制）

**Floating Chat**:
- [ ] 🤖按钮可见

**无旧Chat**:
- [ ] **没有**旧chat

---

### 7️⃣ 参数修改测试

**在任意页面的Sidebar**:
- [ ] 修改History (yr)滑块 → 应该保存到session_state
- [ ] 修改MC Paths → 应该保存
- [ ] 修改Horizon (d) → 应该保存
- [ ] 修改Weights JSON
- [ ] 再次点击"Run Analysis" → 应该用新参数重新计算

---

### 8️⃣ 跨页面导航测试

**测试场景**:
1. [ ] Home → Overview → Risk → Markets → Portfolio
2. [ ] 每次切换，Sidebar都应该保持可见
3. [ ] 参数设置应该在所有页面保持一致
4. [ ] 🤖按钮在所有页面都可见

---

### 9️⃣ Quick Actions测试（Sidebar折叠菜单）

**展开"⚡ Quick Actions"**:
- [ ] 点击"📋 Load Tech Portfolio"
  - Weights JSON应该更新
- [ ] 点击"🛡️ Load Balanced Portfolio"
  - Weights JSON应该更新
- [ ] 点击"🔥 Clear Cache"
  - 应该看到"Cache cleared!"提示

---

### 🔟 Advanced Settings测试（Sidebar折叠菜单）

**展开"🔧 Advanced"**:
- [ ] 修改Max Stock %
- [ ] 修改Max Sector %
- [ ] 勾选"Enable Margin Monitoring"
- [ ] 设置应该保存到session_state

---

## 🐛 常见问题排查

### 问题1: Sidebar不显示
**解决**:
```bash
# 清除缓存并重启
pkill -9 streamlit
rm -rf ~/.streamlit/cache
streamlit run app.py
# 浏览器强制刷新: Cmd+Shift+R
```

### 问题2: Example Portfolio按钮无响应
**检查**:
- 浏览器Console (F12) 是否有错误
- Streamlit终端是否有错误信息
- 尝试手动在Weights JSON输入框粘贴JSON

### 问题3: Run Analysis失败
**可能原因**:
- Ticker无效（如某些加密货币ticker在yfinance不存在）
- 网络问题（无法连接Yahoo Finance）
- JSON格式错误（weights总和不为1）

**解决**:
- 使用标准ticker (AAPL, GOOGL, SPY等)
- 检查JSON格式
- 查看终端错误信息

### 问题4: Floating Chat不显示
**检查**:
- 浏览器Console是否有JavaScript错误
- 尝试不同浏览器
- 检查浏览器是否阻止了某些脚本

### 问题5: 数据加载慢
**正常**: 首次运行可能需要5-30秒下载数据
**优化**: 后续运行会使用缓存，快很多（<3秒）

---

## ✅ 测试通过标准

**所有功能正常**:
- ✅ Sidebar在所有页面可见
- ✅ Example portfolio按钮能更新weights
- ✅ Run Analysis能完成分析
- ✅ 所有4个标签页能正常显示内容
- ✅ Floating chat按钮在所有页面可见
- ✅ **没有**旧的chat popover
- ✅ 参数修改后能保存
- ✅ 无"market_shock undefined"等错误

**如果有失败项**:
1. 记录具体是哪个测试失败
2. 记录错误信息（浏览器Console + 终端）
3. 截图（如果可能）
4. 告诉我，我会立即修复

---

## 📊 测试结果记录

**测试日期**: ___________
**浏览器**: ___________
**Streamlit版本**: ___________

| 测试项 | 通过 | 失败 | 备注 |
|--------|------|------|------|
| 1. 主页 | ☐ | ☐ | |
| 2. Run Analysis | ☐ | ☐ | |
| 3. Overview标签 | ☐ | ☐ | |
| 4. Risk标签 | ☐ | ☐ | |
| 5. Markets标签 | ☐ | ☐ | |
| 6. Portfolio标签 | ☐ | ☐ | |
| 7. 参数修改 | ☐ | ☐ | |
| 8. 跨页面导航 | ☐ | ☐ | |
| 9. Quick Actions | ☐ | ☐ | |
| 10. Advanced Settings | ☐ | ☐ | |

**总体评分**: _____ / 10

---

## 🎯 下一步建议

### 如果所有测试通过 ✅
项目的**核心功能**已经完成！可以考虑：
1. 完善Floating Chat的AI集成（连接真实AI后端）
2. 添加更多example portfolios
3. 实施REDESIGN.md中的UI改进
4. 添加更多risk metrics
5. 部署到云端

### 如果有测试失败 ❌
1. 记录失败的具体测试和错误
2. 提供给我，我会立即修复
3. 重新测试

---

**开始测试吧！** 🚀

完成后告诉我：
- 有多少项通过
- 哪些项失败（如果有）
- 你想优先改进什么功能
