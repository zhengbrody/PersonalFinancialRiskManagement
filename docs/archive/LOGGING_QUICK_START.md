# 日志系统快速入门

## 5分钟快速上手

### 1. 查看日志
```bash
# 查看所有日志
cat logs/app.log

# 实时查看
tail -f logs/app.log

# 查看最近20条
tail -20 logs/app.log
```

### 2. 搜索日志
```bash
# 查找错误
grep ERROR logs/app.log

# 查找特定ticker
grep "AAPL" logs/app.log

# 查找数据下载事件
grep "data.fetch" logs/app.log
```

### 3. 使用 jq 解析
```bash
# 提取事件名称
grep "event" logs/app.log | jq -r '.message | fromjson | .event'

# 查看错误详情
grep ERROR logs/app.log | jq -r '.message | fromjson | "\(.event): \(.error)"'

# 统计耗时
grep "duration_ms" logs/app.log | jq -r '.message | fromjson | .duration_ms'
```

---

## 常用命令速查

| 需求 | 命令 |
|------|------|
| 查看实时日志 | `tail -f logs/app.log` |
| 查找错误 | `grep ERROR logs/app.log` |
| 查找警告 | `grep WARNING logs/app.log` |
| 统计日志条数 | `wc -l logs/app.log` |
| 查看文件大小 | `ls -lh logs/app.log` |
| 查找特定时间 | `grep "2026-04-04 22:47" logs/app.log` |
| 查看事件类型 | `grep event logs/app.log \| jq -r '.message \| fromjson \| .event' \| sort \| uniq -c` |

---

## 代码中使用

```python
from logging_config import get_logger
import time

logger = get_logger(__name__)

# 记录开始
logger.info("operation.start", param="value")

# 记录带耗时的操作
start = time.time()
# ... 你的代码 ...
duration_ms = (time.time() - start) * 1000

logger.info("operation.complete", duration_ms=round(duration_ms, 2))

# 记录错误
try:
    # ... 你的代码 ...
except Exception as e:
    logger.error("operation.failed", error=str(e), exc_info=True)
```

---

## 关键日志事件速查

### 数据下载
- `data.fetch_prices.start` - 开始下载
- `data.download.success` - 下载成功
- `data.fetch_prices.ticker_failed` - ticker失败
- `data.cache.hit` - 缓存命中

### 风险计算
- `risk.run.start` - 引擎启动
- `risk.var.mc.complete` - VaR计算完成
- `risk.beta.complete` - Beta计算完成
- `risk.stress.complete` - 压力测试完成

### UI交互
- `ui.analysis.start` - 分析开始
- `ui.analysis.complete` - 分析完成
- `ui.analysis.failed` - 分析失败

---

## 故障排查

### 问题：找不到日志文件
```bash
# 检查目录是否存在
ls -la logs/

# 运行演示生成日志
python demo_logging.py
```

### 问题：日志太多
```bash
# 清空日志（谨慎！）
> logs/app.log

# 只保留最近100行
tail -100 logs/app.log > logs/app_temp.log
mv logs/app_temp.log logs/app.log
```

### 问题：无法解析JSON
```bash
# 验证JSON格式
cat logs/app.log | head -1 | python3 -m json.tool

# 查找格式错误的行
cat logs/app.log | while read line; do
  echo "$line" | python3 -m json.tool > /dev/null 2>&1 || echo "错误行: $line"
done
```

---

## 运行测试

```bash
# 运行日志测试
pytest tests/unit/test_logging.py -v

# 运行演示
python demo_logging.py

# 查看生成的日志
tail -20 logs/app.log
```

---

## 更多帮助

- 详细文档: `docs/LOGGING_GUIDE.md`
- 实施总结: `docs/LOGGING_SUMMARY.md`
- 演示脚本: `demo_logging.py`
- 测试文件: `tests/unit/test_logging.py`
