# 开发环境设置指南

## 1. 安装开发依赖

```bash
pip install -r requirements-dev.txt
```

## 2. 安装 pre-commit hooks

```bash
pre-commit install
```

## 3. 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并显示覆盖率
pytest --cov

# 生成HTML覆盖率报告
pytest --cov --cov-report=html
# 然后打开 htmlcov/index.html
```

## 4. 代码格式化和检查

```bash
# 格式化代码
black .

# 检查和修复linting问题
ruff check --fix .

# 类型检查
mypy risk_engine.py data_provider.py
```

## 5. Docker 运行

```bash
# 构建并启动
docker-compose up

# 后台运行
docker-compose up -d

# 停止
docker-compose down
```

## 6. 首次设置检查清单

- [ ] Python 3.10+ 已安装
- [ ] 已安装开发依赖: `pip install -r requirements-dev.txt`
- [ ] Pre-commit hooks已安装: `pre-commit install`
- [ ] 测试可以运行: `pytest`
- [ ] Docker可以运行: `docker-compose up`（可选）

## 学习资源

### pytest
- 官方文档: https://docs.pytest.org/
- 视频教程: https://www.youtube.com/watch?v=bbp_849-RZ4

### Docker
- 快速入门: https://docs.docker.com/get-started/
- 视频教程: https://www.youtube.com/watch?v=fqMOX6JJhGo

### Type Hints
- 官方文档: https://docs.python.org/3/library/typing.html
- 实用教程: https://realpython.com/python-type-checking/
