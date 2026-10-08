"""FastAPI application — Fractional AI Architecture Office prototype. OpenAPI docs at /docs."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT, settings
from app.routers import agents, core, domains, kg


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            payload = json.loads(msg)
        except (ValueError, TypeError):
            payload = {"msg": msg}
        return json.dumps({"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, **payload})


_h = logging.StreamHandler()
_h.setFormatter(JsonFormatter())
for name in ("arch_office.agents", "arch_office.llm", "arch_office.api"):
    lg = logging.getLogger(name)
    lg.handlers = [_h]
    lg.setLevel(logging.INFO)
    lg.propagate = False
log = logging.getLogger("arch_office.api")

app = FastAPI(title="Fractional AI Architecture Office", version="1.0.0",
              description="Agents propose, humans decide. Demo-grade prototype with synthetic Utilities and Telecom tenants.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PREFIX = "/api/v1"
for r in (core.router, kg.router, domains.router, agents.router):
    app.include_router(r, prefix=PREFIX)


@app.middleware("http")
async def timing(request: Request, call_next):  # noqa: ANN001, ANN201
    t0 = time.time()
    resp = await call_next(request)
    if request.url.path.startswith(PREFIX) and request.method != "GET":
        log.info(json.dumps({"event": "request", "method": request.method, "path": request.url.path, "status": resp.status_code,
                             "ms": int((time.time() - t0) * 1000)}))
    return resp


@app.exception_handler(KeyError)
async def key_error(_: Request, exc: KeyError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": settings.llm_mode}


# Serve the built UI (make demo) when present
DIST = Path(REPO_ROOT) / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(404, "not found")
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
