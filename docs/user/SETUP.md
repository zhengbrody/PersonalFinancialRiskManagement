# Development Environment Setup Guide

## 1. Install development dependencies

```bash
pip install -r requirements-dev.txt
```

## 2. Install pre-commit hooks

```bash
pre-commit install
```

## 3. Run tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov

# Generate an HTML coverage report
pytest --cov --cov-report=html
# Then open htmlcov/index.html
```

## 4. Code formatting and linting

```bash
# Format code
black .

# Check and fix linting issues
ruff check --fix .

# Type checking
mypy risk_engine.py data_provider.py
```

## 5. Running with Docker (optional — local development usually runs uvicorn / npm run dev directly)

> The old root `docker-compose.yml` (the Streamlit version) was deleted on 2026-07-01.
> The production orchestration files are `compose.split.yml` (backend + frontend) plus
> `compose.aws.yml` (Caddy); production **only pulls GHCR images and never builds locally**
> (see `docs/aws/ci-image-deploy.md`). To run the containerized version locally:

```bash
# Build and start backend + frontend locally (local dev machine only; never build on EC2)
docker compose -f compose.split.yml up --build backend frontend

# Stop
docker compose -f compose.split.yml down
```

Two things to note:
1. `compose.split.yml` only `expose`s the container ports; it does not map them to the host
   (production traffic goes through Caddy). To reach them from a browser locally, create your
   own `compose.override.yml` adding `ports: ["8000:8000"]` / `["3000:3000"]` (do not commit
   it; the EC2 deploy command explicitly uses `-f compose.split.yml` and will not load the
   override).
2. The frontend image bakes in `NEXT_PUBLIC_API_BASE_URL` /
   `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` **at build time** — before
   building locally, provide these three values in a `.env` file at the repo root, otherwise
   the frontend will show "Supabase not configured".

## 6. First-time setup checklist

- [ ] Python 3.10+ installed
- [ ] Development dependencies installed: `pip install -r requirements-dev.txt`
- [ ] Pre-commit hooks installed: `pre-commit install`
- [ ] Tests run successfully: `pytest`
- [ ] Docker runs: `docker compose -f compose.split.yml up --build backend frontend` (optional)

## Learning Resources

### pytest
- Official docs: https://docs.pytest.org/
- Video tutorial: https://www.youtube.com/watch?v=bbp_849-RZ4

### Docker
- Getting started: https://docs.docker.com/get-started/
- Video tutorial: https://www.youtube.com/watch?v=fqMOX6JJhGo

### Type Hints
- Official docs: https://docs.python.org/3/library/typing.html
- Practical tutorial: https://realpython.com/python-type-checking/
