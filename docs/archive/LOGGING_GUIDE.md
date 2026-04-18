# 日志系统使用指南

## 概述

MindMarket AI 使用结构化日志系统（基于 `structlog` 和 `python-json-logger`）来记录所有关键操作。日志以 JSON 格式存储，便于解析、搜索和分析。

## 日志配置

### 位置
- 日志文件：`logs/app.log`
- 配置文件：`logging_config.py`

### 特性
- **JSON格式**：所有日志条目都是有效的JSON，便于机器解析
- **自动滚动**：日志文件达到10MB时自动轮换，保留最近5个文件
- **多级别**：INFO、WARNING、ERROR级别
- **上下文信息**：包含文件名、行号、时间戳等

### 日志字段说明
```json
{
  "asctime": "2026-04-04 22:47:57,298",      // 时间戳
  "name": "data_provider",                   // Logger名称（模块）
  "levelname": "INFO",                       // 日志级别
  "message": "{...}",                        // 结构化消息（JSON）
  "taskName": null
}
```

**message 字段内容**：
```json
{
  "event": "data.fetch_prices.start",        // 事件名称
  "level": "info",                           // 级别
  "timestamp": "2026-04-05T05:47:57.298Z",   // ISO时间戳
  "filename": "data_provider.py",            // 源文件
  "lineno": 20,                              // 行号
  "ticker": "AAPL",                          // 自定义字段
  "duration_ms": 123.45,                     // 性能指标
  // ... 其他自定义字段
}
```

---

## 关键事件清单

### 数据下载（data_provider）

| 事件名称 | 级别 | 说明 | 关键字段 |
|---------|------|------|---------|
| `data.fetch_prices.start` | INFO | 批量数据下载开始 | `tickers`, `ticker_count`, `force_refresh`, `period_years` |
| `data.download.success` | INFO | 单个ticker下载成功 | `ticker`, `rows`, `duration_ms`, `cached` |
| `data.fetch_prices.ticker_failed` | WARNING | 单个ticker失败 | `ticker`, `error` |
| `data.fetch_prices.validation_failed` | WARNING | 数据验证失败 | `ticker`, `error` |
| `data.fetch_prices.complete` | INFO | 批量下载完成 | `successful`, `failed`, `total`, `duration_ms` |
| `data.cache.hit` | INFO | 缓存命中 | `ticker`, `data_type`, `rows`, `duration_ms` |
| `data.cache.load_failed` | WARNING | 缓存加载失败 | `ticker`, `error` |
| `data.download.empty` | WARNING | 下载数据为空 | `ticker`, `data_type` |
| `data.download.failed` | ERROR | 下载失败 | `ticker`, `error` |

### 风险计算（risk_engine）

| 事件名称 | 级别 | 说明 | 关键字段 |
|---------|------|------|---------|
| `risk.run.start` | INFO | 风险引擎启动 | `benchmark`, `mc_simulations`, `mc_horizon` |
| `risk.var.mc.start` | INFO | 蒙特卡洛VaR开始 | `mc_simulations`, `mc_horizon`, `n_assets` |
| `risk.var.mc.complete` | INFO | 蒙特卡洛VaR完成 | `var_95`, `var_99`, `duration_ms` |
| `risk.beta.start` | INFO | Beta计算开始 | `benchmark` |
| `risk.beta.complete` | INFO | Beta计算完成 | `benchmark`, `tickers_calculated`, `duration_ms` |
| `risk.beta.benchmark_failed` | WARNING | 基准数据获取失败 | `benchmark`, `error` |
| `risk.stress.start` | INFO | 压力测试开始 | `market_shock` |
| `risk.stress.complete` | INFO | 压力测试完成 | `market_shock`, `portfolio_loss`, `duration_ms` |
| `risk.run.complete` | INFO | 风险引擎完成 | `var_95`, `var_99`, `annual_return`, `sharpe_ratio`, `duration_ms` |

### UI交互（app）

| 事件名称 | 级别 | 说明 | 关键字段 |
|---------|------|------|---------|
| `ui.button.run_analysis_clicked` | INFO | 运行分析按钮点击 | - |
| `ui.button.refresh_data_clicked` | INFO | 刷新数据按钮点击 | - |
| `ui.weights.parsed` | INFO | 权重JSON解析成功 | `ticker_count` |
| `ui.weights.invalid_json` | WARNING | 权重JSON格式错误 | `error` |
| `ui.weights.normalized` | INFO | 权重归一化 | `original_sum` |
| `ui.analysis.start` | INFO | 分析开始 | `tickers`, `period_years`, `mc_sims` |
| `ui.analysis.complete` | INFO | 分析完成 | `duration_ms`, `var_95`, `sharpe_ratio` |
| `ui.analysis.failed` | ERROR | 分析失败 | `error`, `duration_ms` |
| `ui.refresh_data.success` | INFO | 数据刷新成功 | `ticker_count` |
| `ui.refresh_data.failed` | ERROR | 数据刷新失败 | `error` |

---

## 日志查询示例

### 使用 grep + jq

#### 1. 查找所有数据下载事件
```bash
grep "data.fetch" logs/app.log | jq -r '.message | fromjson | "\(.event) - \(.duration_ms)ms"'
```

#### 2. 查找失败的ticker
```bash
grep "ticker_failed" logs/app.log | jq -r '.message | fromjson | "\(.ticker): \(.error)"'
```

#### 3. 统计VaR计算耗时
```bash
grep "risk.var.mc.complete" logs/app.log | \
  jq -r '.message | fromjson | .duration_ms' | \
  awk '{sum+=$1; count++} END {print "平均:", sum/count, "ms"}'
```

#### 4. 查找所有错误
```bash
grep '"levelname":"ERROR"' logs/app.log | jq -r '.message | fromjson | .event, .error'
```

#### 5. 查找慢操作（>5秒）
```bash
grep "duration_ms" logs/app.log | \
  jq -r '.message | fromjson | select(.duration_ms > 5000) | "\(.event): \(.duration_ms)ms"'
```

#### 6. 按时间范围查询
```bash
grep "2026-04-04 22:4" logs/app.log | jq -r '.message | fromjson | .event'
```

#### 7. 查看特定ticker的所有操作
```bash
grep "AAPL" logs/app.log | jq -r '.message | fromjson | "\(.timestamp) - \(.event)"'
```

#### 8. 统计每种事件的数量
```bash
grep "event" logs/app.log | \
  jq -r '.message | fromjson | .event' | \
  sort | uniq -c | sort -rn
```

---

## 性能分析

### 查找性能瓶颈
```bash
# 查找所有包含duration_ms的事件，按耗时排序
grep "duration_ms" logs/app.log | \
  jq -r '.message | fromjson | "\(.duration_ms)\t\(.event)"' | \
  sort -rn | head -10
```

### 生成性能报告
```bash
# 数据下载平均耗时
echo "=== 数据下载性能 ==="
grep "data.download.success" logs/app.log | \
  jq -r '.message | fromjson | .duration_ms' | \
  awk '{sum+=$1; count++; if($1>max) max=$1; if(min=="" || $1<min) min=$1}
       END {print "平均:", sum/count, "ms"; print "最小:", min, "ms"; print "最大:", max, "ms"}'

# VaR计算平均耗时
echo -e "\n=== VaR计算性能 ==="
grep "risk.var.mc.complete" logs/app.log | \
  jq -r '.message | fromjson | .duration_ms' | \
  awk '{sum+=$1; count++} END {print "平均:", sum/count, "ms"}'
```

---

## 故障排查

### 查找最近的错误
```bash
# 最近10条错误
grep "ERROR" logs/app.log | tail -10 | jq -r '.message | fromjson | "\(.timestamp) - \(.event): \(.error)"'
```

### 查找异常堆栈
```bash
# 包含异常信息的日志
grep "exception" logs/app.log | jq -r '.message | fromjson | .exception'
```

### 追踪单次分析的完整流程
```bash
# 1. 找到最近一次分析的时间戳
TIMESTAMP=$(grep "ui.analysis.start" logs/app.log | tail -1 | jq -r '.asctime')

# 2. 提取该时间附近的所有事件
grep "$TIMESTAMP" logs/app.log -A 50 | jq -r '.message | fromjson | "\(.timestamp) - \(.event)"'
```

---

## 监控和告警

### 实时监控（tail -f）
```bash
# 实时查看所有日志
tail -f logs/app.log | jq -r '.message | fromjson | "\(.timestamp) [\(.level | ascii_upcase)] \(.event)"'

# 只看错误
tail -f logs/app.log | grep ERROR | jq -r '.message | fromjson | "\(.timestamp) - \(.event): \(.error)"'
```

### 生成每日报告
```bash
#!/bin/bash
# daily_report.sh

TODAY=$(date +%Y-%m-%d)
echo "=== 日志报告 $TODAY ==="

echo -e "\n总事件数:"
grep "$TODAY" logs/app.log | wc -l

echo -e "\n错误数:"
grep "$TODAY" logs/app.log | grep ERROR | wc -l

echo -e "\n失败的ticker:"
grep "$TODAY" logs/app.log | grep ticker_failed | \
  jq -r '.message | fromjson | .ticker' | sort | uniq -c

echo -e "\n平均分析耗时:"
grep "$TODAY" logs/app.log | grep "ui.analysis.complete" | \
  jq -r '.message | fromjson | .duration_ms' | \
  awk '{sum+=$1; count++} END {print sum/count, "ms"}'
```

---

## Python API 使用

### 在代码中添加日志

```python
from logging_config import get_logger
import time

logger = get_logger(__name__)

def my_function():
    logger.info("function.start", param1="value1")

    start_time = time.time()
    try:
        # 你的代码
        result = do_something()

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "function.complete",
            result=result,
            duration_ms=round(duration_ms, 2)
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "function.failed",
            error=str(e),
            duration_ms=round(duration_ms, 2),
            exc_info=True  # 包含堆栈跟踪
        )
        raise
```

### 日志级别选择

- **INFO**: 正常操作（数据下载、计算完成）
- **WARNING**: 可恢复的问题（单个ticker失败、缓存失效）
- **ERROR**: 失败的操作（分析失败、网络错误）

### 最佳实践

1. **事件命名规范**：`模块.操作.状态`（例如：`data.fetch.start`, `data.fetch.complete`）
2. **始终记录耗时**：使用 `duration_ms` 字段
3. **上下文信息**：包含足够的字段便于调试（ticker、日期范围等）
4. **错误处理**：失败时记录 `error` 字段和 `exc_info=True`

---

## 日志文件管理

### 轮换策略
- 单文件最大：10MB
- 保留文件数：5个
- 总容量：~50MB

### 清理旧日志
```bash
# 只保留最近7天的日志
find logs/ -name "*.log*" -mtime +7 -delete
```

### 归档
```bash
# 压缩旧日志
tar -czf logs_archive_$(date +%Y%m%d).tar.gz logs/*.log.*
```

---

## 集成到监控系统

### ELK Stack
```bash
# 使用 Filebeat 发送到 Elasticsearch
filebeat -e -c filebeat.yml
```

### Grafana Loki
```bash
# Promtail 配置
- job_name: mindmarket
  static_configs:
  - targets:
      - localhost
    labels:
      job: mindmarket
      __path__: /path/to/logs/app.log
```

### 自定义监控
```python
import json

def parse_logs(log_file):
    """解析日志文件并提取指标"""
    metrics = {
        'total_events': 0,
        'errors': 0,
        'avg_duration': 0,
        'failed_tickers': set()
    }

    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                message = json.loads(entry['message'])

                metrics['total_events'] += 1

                if entry['levelname'] == 'ERROR':
                    metrics['errors'] += 1

                if 'ticker_failed' in message.get('event', ''):
                    metrics['failed_tickers'].add(message.get('ticker'))

            except:
                continue

    return metrics
```

---

## 常见问题

### Q: 日志文件太大怎么办？
A: 日志自动轮换，单文件最大10MB。可以调整 `logging_config.py` 中的 `maxBytes` 参数。

### Q: 如何禁用控制台日志？
A: 在 `logging_config.py` 中注释掉 `console_handler` 相关代码。

### Q: 性能影响？
A: 结构化日志的性能开销 <1%，对生产环境影响微乎其微。

### Q: 如何查看实时日志？
A: 使用 `tail -f logs/app.log`

---

## 示例日志条目

### 成功的数据下载
```json
{
  "asctime": "2026-04-04 22:47:57,311",
  "name": "data_provider",
  "levelname": "INFO",
  "message": {
    "ticker": "AAPL",
    "data_type": "prices",
    "rows": 504,
    "download_duration_ms": 12.55,
    "total_duration_ms": 12.55,
    "cached": false,
    "event": "data.download.success",
    "level": "info",
    "timestamp": "2026-04-05T05:47:57.311000Z",
    "filename": "data_provider.py",
    "lineno": 37
  }
}
```

### 失败的ticker
```json
{
  "asctime": "2026-04-04 22:47:57,742",
  "name": "data_provider",
  "levelname": "WARNING",
  "message": {
    "ticker": "INVALID-TICKER",
    "error": "下载返回空数据",
    "event": "data.fetch_prices.ticker_failed",
    "level": "warning",
    "timestamp": "2026-04-05T05:47:57.742833Z",
    "filename": "data_provider.py",
    "lineno": 163
  }
}
```

### VaR计算完成
```json
{
  "asctime": "2026-04-04 22:47:57,497",
  "name": "risk_engine",
  "levelname": "INFO",
  "message": {
    "var_95": 0.0823,
    "var_99": 0.1245,
    "duration_ms": 105.21,
    "event": "risk.var.mc.complete",
    "level": "info",
    "timestamp": "2026-04-05T05:47:57.496911Z",
    "filename": "risk_engine.py",
    "lineno": 82
  }
}
```
