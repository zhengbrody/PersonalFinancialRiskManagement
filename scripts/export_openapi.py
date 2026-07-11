#!/usr/bin/env python
"""Export the FastAPI OpenAPI schema to the committed ``openapi.json``.

``openapi.json`` is the single bridge between the backend contract and the
frontend types: the frontend's ``npm run gen:api`` reads THIS file (offline,
no live server) to regenerate ``frontend/src/lib/api-types.ts``. Committing it
lets CI regenerate + ``git diff --exit-code`` to fail on undocumented drift.

Output is ``sort_keys``-stable so the diff reflects real contract changes, not
dict-ordering noise. Run from the repo root::

    python scripts/export_openapi.py            # writes ./openapi.json
    python scripts/export_openapi.py --check     # exit 1 if stale (CI gate)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "openapi.json"


def build_spec() -> dict:
    # Minimal env so create_app() imports without real secrets.
    os.environ.setdefault("SUPABASE_URL", "https://export.supabase.co")
    os.environ.setdefault("SUPABASE_JWT_SECRET", "x" * 40)
    sys.path.insert(0, str(ROOT))
    from backend.app.main import create_app

    return create_app().openapi()


def render(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if openapi.json is stale")
    args = ap.parse_args()

    text = render(build_spec())
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print(
                "openapi.json is stale — run `python scripts/export_openapi.py` "
                "and `cd frontend && npm run gen:api`, then commit.",
                file=sys.stderr,
            )
            return 1
        print("openapi.json is up to date.")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
