"""MindMarket FastAPI service.

Phase 1 of the migration documented in
``docs/adr/0004-fastapi-nextjs-migration.md``.

Top-level layout::

    backend/
        app/
            main.py        FastAPI instance + router wiring
            core/          config, CORS, response envelope, auth dep
            api/v1/        route modules (health, risk, equity, portfolios)
            schemas/       request/response pydantic models
        tests/             pytest, runs without network or Supabase
        requirements-backend.txt
        README.md

Streamlit, ``app.py``, ``pages/``, ``libs/``, ``engine/``, and every
existing import path are unchanged. This package only imports from
those modules; it never modifies them.
"""
