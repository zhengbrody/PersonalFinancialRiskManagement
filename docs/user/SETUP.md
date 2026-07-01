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

## 5. Docker 运行（可选 — 本地开发通常直接跑 uvicorn / npm run dev）

> 旧的根目录 `docker-compose.yml`（Streamlit 版）已于 2026-07-01 删除。
> 生产用的编排文件是 `compose.split.yml`（backend + frontend）+
> `compose.aws.yml`（Caddy）；生产环境**只拉取 GHCR 镜像、从不本地构建**
> （见 `docs/aws/ci-image-deploy.md`）。本地想跑容器版可以：

```bash
# 本地构建并启动 backend + frontend（仅本地开发机；不要在 EC2 上构建）
docker compose -f compose.split.yml up --build backend frontend

# 停止
docker compose -f compose.split.yml down
```

注意两点：
1. `compose.split.yml` 只 `expose` 容器端口、不映射到宿主机（生产流量走
   Caddy）。本地想用浏览器访问，需要自建一个 `compose.override.yml` 加
   `ports: ["8000:8000"]` / `["3000:3000"]`（不要提交；EC2 的部署命令显式
   `-f compose.split.yml`，不会加载 override）。
2. 前端镜像在**构建时**烘焙 `NEXT_PUBLIC_API_BASE_URL` /
   `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`——本地构建前
   先在仓库根目录 `.env` 提供这三个值，否则前端会显示 "Supabase not
   configured"。

## 6. 首次设置检查清单

- [ ] Python 3.10+ 已安装
- [ ] 已安装开发依赖: `pip install -r requirements-dev.txt`
- [ ] Pre-commit hooks已安装: `pre-commit install`
- [ ] 测试可以运行: `pytest`
- [ ] Docker可以运行: `docker compose -f compose.split.yml up --build backend frontend`（可选）

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
