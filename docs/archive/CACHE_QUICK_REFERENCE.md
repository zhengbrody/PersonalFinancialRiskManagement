# Streamlit 缓存优化 - 快速参考

## 核心修改位置

### 1. 添加 DataProvider 缓存资源
**文件**: `app.py` 第301-322行
```python
@st.cache_resource(ttl=86400)
def get_data_provider(weights_json: str, period_years: int):
    weights = json.loads(weights_json)
    dp = DataProvider(weights, period_years=period_years, ...)
    dp.fetch_prices()  # 立即加载
    return dp
```

### 2. 修复分析函数缓存键
**文件**: `app.py` 第324行
```python
# 前: run_portfolio_analysis(weights: dict, ...)  ❌ dict 不 hashable
# 后: run_portfolio_analysis(weights_json: str, ...)  ✓ string hashable

weights_json = json.dumps(weights, sort_keys=True)  # 生成缓存键
report, prices, cumret = run_portfolio_analysis(weights_json, ...)
```

### 3. Session State 权重跟踪
**文件**: `app.py` 第1268行
```python
weights_json = json.dumps(weights, sort_keys=True)
weights_changed = weights_json != st.session_state.last_weights_json

if using_cache:
    st.info("Using cached results")
    # 不重新计算，直接显示 st.session_state.report
else:
    # 执行完整分析并保存到 session state
    st.session_state.last_weights_json = weights_json
```

### 4. 性能监控
**文件**: `app.py` 第1359-1365行
```python
analysis_duration_ms = (time.time() - analysis_start) * 1000

perf_col1, perf_col2 = st.columns(2)
with perf_col1:
    st.caption(f"Computation time: {analysis_duration_ms:.0f}ms")
with perf_col2:
    st.caption(f"Target: <10s (cold), <3s (cached)")
```

---

## 性能指标总结

| 场景 | 时间 | 目标 | 状态 |
|------|------|------|------|
| 首次运行（7股） | 2.19s | <10s | ✓✓✓ |
| 缓存命中（权重不变） | 0.20s | <3s | ✓✓✓ |
| 参数变化（数据重用） | ~1.5s | <5s | ✓✓ |

---

## 运行性能测试

```bash
# 全部测试
pytest tests/performance/test_streamlit_performance.py -v -s --no-cov

# 7股冷启动测试
pytest tests/performance/test_streamlit_performance.py::TestCachePerformance::test_full_analysis_7_stocks_cold -v -s --no-cov

# 缓存命中测试
pytest tests/performance/test_streamlit_performance.py::TestCachePerformance::test_multiple_runs_same_weights -v -s --no-cov
```

---

## 缓存清除

```bash
# 清除 Streamlit 缓存
streamlit cache clear

# 清除文件系统缓存
rm -rf .cache/market_data/
```

---

## 查看日志

```bash
# 查看缓存命中日志
grep "cache_hit\|analysis.cache" logs/app.log

# 查看性能指标
grep "duration_ms" logs/app.log

# 实时日志
tail -f logs/app.log
```

---

## 关键代码片段

### 如何使用缓存
```python
# app.py 中调用
weights_json = json.dumps(weights, sort_keys=True)

# 调用缓存的分析函数
report, prices, cumret = run_portfolio_analysis(
    weights_json,           # JSON 字符串作为缓存键
    period_years,
    mc_sims,
    mc_horizon,
    risk_free_fallback,
)

# 检查缓存命中
if weights_json == st.session_state.last_weights_json:
    print("缓存命中！")
```

### DataProvider 缓存用法
```python
# 内部在 run_portfolio_analysis 中
dp = get_data_provider(weights_json, period_years)
# 首次调用: 创建 + 下载数据 (0.78s)
# 后续调用: 从缓存获取实例 (<100ms)

prices = dp.fetch_prices()  # 从内存获取，超快
```

---

## TTL 设置参考

| 缓存层 | TTL | 用途 |
|--------|-----|------|
| DataProvider (@st.cache_resource) | 86400s (24h) | 保持数据在内存 |
| Analysis (@st.cache_data) | 3600s (1h) | 缓存完整结果 |
| Live Weights (@st.cache_data) | 300s (5m) | 实时权重更新 |
| Daily PnL (@st.cache_data) | 60s (1m) | 每日数据 |

---

## 故障排除

### 问题: 修改权重后仍显示旧结果
**原因**: Session state 未更新
**解决**: 确保在 `st.session_state.update()` 中设置 `last_weights_json`

### 问题: 缓存似乎不工作（每次都重新计算）
**原因**: 权重未正确转为 JSON 或 sort_keys 不一致
**检查**:
```python
print(f"Weights JSON: {json.dumps(weights, sort_keys=True)}")
print(f"Last weights: {st.session_state.last_weights_json}")
```

### 问题: "No runtime found, using MemoryCacheStorageManager"
**原因**: Streamlit 不在标准运行时（如直接 python 调用）
**解决**: 使用 `streamlit run app.py` 运行

---

## 监控缓存效率

在应用运行时添加调试面板（仅限开发）:

```python
# 在 app.py 末尾添加
if st.secrets.get("DEBUG_MODE"):
    with st.expander("Debug: Cache Info"):
        st.write(f"Last weights JSON: {st.session_state.last_weights_json[:50]}...")
        st.write(f"Last analysis duration: {st.session_state.last_analysis_duration_ms:.0f}ms")
        st.write(f"From cache: {st.session_state.analysis_from_cache}")

        # 清除缓存按钮
        if st.button("Clear All Caches"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.write("Caches cleared!")
```

---

## 相关文件

| 文件 | 修改内容 | 行号 |
|------|---------|------|
| app.py | @st.cache_resource 函数 | 301-322 |
| app.py | @st.cache_data 函数修复 | 324-388 |
| app.py | Session state 初始化 | 1131-1134 |
| app.py | 权重检查和性能监控 | 1267-1365 |
| tests/performance/test_streamlit_performance.py | 性能测试套件 | - |
| PERFORMANCE_OPTIMIZATION.md | 详细报告 | - |

---

## 最后验证清单

- [x] `@st.cache_resource` 添加到 `get_data_provider()`
- [x] `@st.cache_data` 的缓存键改为 JSON 字符串
- [x] Session state 初始化三个追踪变量
- [x] 权重变化检查逻辑实现
- [x] 性能监控代码添加
- [x] 性能测试通过（2.19s 冷启动）
- [x] 缓存测试通过（0.20s 命中）
- [x] 日志记录性能指标

**优化完成！** 🚀

