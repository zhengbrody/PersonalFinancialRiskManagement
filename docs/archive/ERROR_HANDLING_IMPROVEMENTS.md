# MindMarket AI 错误处理改进报告

## 概述

本次改进对 MindMarket AI 的错误处理和用户提示进行了全面升级，用友好的、可操作的错误消息替换了原始的Python堆栈跟踪。

---

## 改进内容

### 1. 新增错误处理模块 (`error_handler.py`)

创建了独立的错误处理模块，提供统一的错误管理接口。

#### 主要功能：

- **友好错误显示**: `show_error()` - 显示用户友好的错误消息、可能原因和解决建议
- **警告显示**: `show_warning()` - 显示警告信息和建议
- **成功显示**: `show_success()` - 显示成功消息
- **特定错误处理**:
  - `handle_json_error()` - JSON格式错误（含位置信息）
  - `handle_weight_error()` - 权重配置错误
  - `handle_data_loading_error()` - 数据加载错误
  - `handle_risk_calculation_error()` - 风险计算错误
- **验证函数**:
  - `validate_weights()` - 验证并自动归一化权重
  - `validate_tickers()` - 验证ticker格式
  - `safe_operation()` - 安全执行操作的装饰器

#### 错误建议字典（ERROR_SUGGESTIONS）：

包含以下错误类型的详细建议：
- `json_decode_error` - JSON格式错误
- `connection_error` - 网络连接失败
- `insufficient_data` - 数据不足
- `linear_algebra_error` - 协方差矩阵计算失败
- `weight_error` - 权重配置错误
- `invalid_ticker` - 无效的股票代码
- `timeout_error` - 请求超时
- `value_error` - 参数值错误

---

### 2. app.py 的主要改进

#### 2.1 添加导入
```python
from error_handler import (
    show_error, show_warning, show_success, handle_json_error,
    handle_weight_error, handle_data_loading_error, handle_risk_calculation_error,
    validate_weights, validate_tickers, safe_operation
)
```

#### 2.2 增强的 `run_portfolio_analysis()` 函数

**改进点：**
- 添加了数据加载失败检查
- 将 `np.linalg.LinAlgError` 转换为用户友好的错误消息
- 提供具体的问题诊断

**新增处理：**
```python
# 检查失败的tickers
failed_tickers = dp.get_failed_tickers()
if failed_tickers and len(failed_tickers) == len(weights):
    raise ValueError("无法下载所有ticker的数据...")

# 线性代数错误处理
except np.linalg.LinAlgError as e:
    raise ValueError(
        "协方差矩阵计算失败。可能原因: "
        "资产高度相关、数据不足或数据质量问题"
    )
```

#### 2.3 改进的 `call_llm()` 函数

**改进点：**
- 更详细的错误分类
- 特定的错误消息（中文）
- Ollama连接超时处理

**新增错误处理：**
```python
# Ollama连接错误
except requests.exceptions.ConnectionError as e:
    raise ConnectionError(
        "无法连接到本地 Ollama (localhost:11434)。"
        "请确保 Ollama 已启动，或切换到 DeepSeek/Claude API。"
    )

# 超时错误
except requests.exceptions.Timeout as e:
    raise TimeoutError(
        "Ollama 响应超时。请检查网络连接或稍后重试。"
    )
```

#### 2.4 运行分析的完整错误处理流程

新增4步验证和错误处理：

**Step 1: JSON解析**
```python
try:
    weights: dict = json.loads(weights_input)
except json.JSONDecodeError as e:
    handle_json_error(e, weights_input)  # 显示错误位置
    st.stop()
```

**Step 2: 权重验证**
```python
is_valid, normalized_weights, validation_msg = validate_weights(weights)
if not is_valid:
    show_error(..., error_type="weight_error")
    st.stop()
```

**Step 3: Ticker验证**
```python
all_valid, valid_tickers, invalid_tickers = validate_tickers(list(weights.keys()))
if invalid_tickers:
    show_warning(..., suggestions=[...])
    st.stop()
```

**Step 4-5: 数据加载和风险计算**
```python
try:
    with st.spinner("正在下载市场数据（可能需要30-60秒）..."):
        report, prices, cumret = run_portfolio_analysis(...)
    show_success(f"成功加载 {len(prices.columns)} 个ticker的数据")
except ValueError as e:
    show_error(e, title="数据加载失败", error_type="insufficient_data")
except Exception as e:
    # 检查是否是线性代数错误
    if "linalg" in str(e).lower():
        show_error(e, title="协方差矩阵计算失败",
                  error_type="linear_algebra_error")
    st.stop()
```

#### 2.5 改进的 `render_chat_popover()` 函数

**改进点：**
- 每个操作都有spinner（"AI分析中..."）
- 特定的错误类型处理
- 详细的错误日志

**新增错误处理：**
```python
try:
    with st.spinner("AI分析中..."):
        _resp = call_llm(...)
    st.markdown(_resp)
except ConnectionError as _e:
    show_error(..., error_type="connection_error")
except TimeoutError as _e:
    show_warning(..., suggestions=[...])
except ValueError as _e:
    show_error(..., error_type="value_error")
```

---

### 3. 添加的 Spinner（加载指示器）

现在所有耗时操作都显示spinner：

| 操作 | Spinner文本 |
|------|-----------|
| 数据下载 | "正在下载市场数据（可能需要30-60秒）..." |
| 权重解析 | N/A（快速操作） |
| 数据加载 | 自动处理 |
| 风险引擎构建 | "正在构建风险引擎..." |
| AI分析 | "AI分析中..." |

---

### 4. 单元测试 (`tests/unit/test_error_handling.py`)

创建了全面的单元测试，覆盖以下场景：

#### 权重验证测试（7个）
- ✓ 有效的权重
- ✓ 需要归一化的权重
- ✓ 空权重字典
- ✓ 负权重
- ✓ 非数字权重
- ✓ 权重容差
- ✓ 超出容差的权重

#### Ticker验证测试（6个）
- ✓ 有效的ticker
- ✓ 包含特殊字符的ticker
- ✓ 混合有效和无效的ticker
- ✓ 包含连字符的ticker（如BTC-USD）
- ✓ 空ticker列表
- ✓ 包含等号的ticker

#### JSON解析测试（6个）
- ✓ 有效的JSON
- ✓ 缺少右大括号
- ✓ 使用单引号的JSON
- ✓ 尾部逗号
- ✓ 包含注释的JSON
- ✓ 数组而不是对象

#### 错误场景测试（5个）
- ✓ 所有ticker都无效
- ✓ 权重总和为0
- ✓ 大量ticker（1000个）
- ✓ 混合大小写的ticker
- ✓ 复杂的权重归一化

#### 错误消息测试（2个）
- ✓ JSON错误包含行号信息
- ✓ 权重验证错误消息详细

#### 集成测试（3个）
- ✓ 完整的验证流程
- ✓ 无效输入早期退出
- ✓ 优雅的部分失败处理

**测试结果：29/29 通过 (100%)**

---

## 用户友好的错误示例

### 示例 1: JSON 格式错误

**之前：**
```
JSONDecodeError: Expecting ',' delimiter: line 1 column 32 (char 31)
Traceback...
```

**之后：**
```
❌ JSON格式错误
错误: Expecting ',' delimiter: line 1 column 32
错误位置: 第 1 行，第 32 列

错误附近的代码:
>>> {"AAPL": 0.5, "GOOGL": 0.5

📋 可能的原因和解决方案:
常见JSON错误:
- 字符串必须用双引号（"），不能用单引号（'）
- 最后一个元素后面不能有逗号
- 大括号和方括号必须成对出现
```

### 示例 2: 数据加载失败

**之前：**
```
ValueError: ...
Traceback...
```

**之后：**
```
❌ 数据加载失败
错误: 无法下载所有ticker的数据。可能原因: 网络不可用、股票代码无效或日期范围错误

📋 可能的原因和解决方案:
可能的原因:
- 网络连接中断
- 股票代码无效
- 日期范围错误

建议的解决方案:
- 增加历史数据周期（建议≥2年）
- 检查股票代码是否正确
- 确保网络连接正常
```

### 示例 3: 协方差矩阵错误

**之前：**
```
numpy.linalg.LinAlgError: Singular matrix
Traceback...
```

**之后：**
```
❌ 协方差矩阵计算失败
错误: 协方差矩阵计算失败。可能原因: 资产高度相关、数据不足或数据质量问题

📋 可能的原因和解决方案:
可能的原因:
- 资产完全相关（高度相关）
- 数据中存在NaN或无穷大值
- 样本量不足导致矩阵奇异

建议的解决方案:
- 移除过度相关的资产对
- 增加历史数据周期
- 检查数据质量（可能存在异常值）
```

### 示例 4: 权重配置错误

**之前：**
```
ValueError: ...
```

**之后：**
```
❌ 权重配置错误
错误: 权重总和不等于1.0

✓ 数据加载完成（自动处理）
已自动归一化为100%

**归一化后的权重:**
- GOOGL: 58.33%
- AAPL: 41.67%
```

---

## 代码统计

### 新增或修改的文件

| 文件 | 操作 | 行数 |
|------|------|------|
| `error_handler.py` | 创建 | 425 |
| `app.py` | 修改 | +150（改进现有代码） |
| `tests/unit/test_error_handling.py` | 创建 | 341 |

### 改进统计

| 指标 | 数量 |
|------|------|
| 添加的try-except块 | 12+ |
| 添加的spinner | 4 |
| 错误建议类型 | 8 |
| 单元测试用例 | 29 |
| 验证函数 | 2（validate_weights, validate_tickers） |
| 特定错误处理函数 | 4 |

---

## 用户体验改进

### 1. 清晰的错误分类
- 用户输入错误 (JSON, 权重, ticker格式)
- 数据问题 (网络, 无效代码, 数据不足)
- 计算问题 (矩阵奇异, 数据质量)
- 配置问题 (API密钥, LLM设置)

### 2. 可操作的建议
每个错误都包含：
- 问题原因分析
- 具体的解决步骤
- 参考资源（如股票代码格式、JSON语法等）

### 3. 逐步的验证流程
```
JSON解析 → 权重验证 → Ticker验证 → 数据下载 → 风险计算
   ↓         ↓          ↓          ↓         ↓
 快速失败   自动修复    验证格式   详细提示  专业诊断
```

### 4. 非侵入性的技术细节
- 技术详情在可展开的expander中
- 堆栈跟踪自动记录到日志（logs/app.log）
- 用户看到的是总结和建议，不是技术细节

---

## 验收标准检查

- ✅ `app.py`有全局错误边界和异常处理
- ✅ 所有耗时操作有spinner（4个）
- ✅ 数据加载失败有详细提示
- ✅ 输入验证有友好错误和建议
- ✅ 29个错误处理测试通过（100%）

---

## 日志支持

所有错误都自动记录到 `logs/app.log`：

```
2024-04-04 10:23:45 ERROR ui.analysis.failed error=协方差矩阵计算失败
2024-04-04 10:24:12 ERROR ui.json_parse_error lineno=1 colno=32
2024-04-04 10:25:01 WARNING ui.weights.normalized original_sum=1.15
```

用户可以在错误提示中看到：
> 建议: 刷新页面重试 • 检查日志: logs/app.log

---

## 未来改进空间

1. **多语言支持**: 当前使用中文，可扩展to English/其他语言
2. **错误分析仪表板**: 显示最常见的错误和趋势
3. **自动修复建议**: 对于某些错误（如权重），自动修复而不是停止
4. **错误恢复流程**: 某些操作失败时的自动重试机制
5. **用户反馈**: 允许用户报告错误和建议改进

---

## 如何使用

### 对于最终用户
1. 遇到错误时，阅读友好的错误消息和建议
2. 如需要技术细节，点击"技术细节（开发者）"展开器
3. 如问题持续，检查 `logs/app.log`

### 对于开发者
1. 在 `error_handler.py` 中添加新的错误类型到 `ERROR_SUGGESTIONS`
2. 在 `validate_*` 函数中添加新的验证逻辑
3. 使用 `show_error()`, `show_warning()`, `handle_*()` 函数显示错误
4. 所有错误自动记录到日志

---

## 完成时间

- 创建 error_handler.py: 2024-04-04
- 改进 app.py: 2024-04-04
- 创建单元测试: 2024-04-04
- 所有测试通过: 2024-04-04

---

## 贡献者

Claude Code 🧠
