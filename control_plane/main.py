from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from control_plane.db import init_db
from control_plane.routes import internal, public
from control_plane.scheduler import tick
from control_plane.seed import seed
from control_plane.service import ServiceError
from control_plane.tool_proxy import ToolError
from shared.config import get_settings
from shared.logging import setup_logging
from shared.otel import setup_otel


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging("control-plane", settings.log_level)
    setup_otel(settings.otel_service_name, settings.otel_exporter_otlp_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.migrate_on_start:
            _init_with_retry()
        stop = threading.Event()
        thread = None
        if settings.scheduler_enabled:
            thread = threading.Thread(target=_loop, args=(stop,), name="scheduler", daemon=True)
            thread.start()
        yield
        stop.set()
        if thread is not None:
            thread.join(timeout=2)

    app = FastAPI(title="Ajan Çalıştırıcı", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(public)
    app.include_router(internal)

    @app.exception_handler(ServiceError)
    async def _service_error(_request, exc: ServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(ToolError)
    async def _tool_error(_request, exc: ToolError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.get("/")
    def root():
        return {
            "service": "agent-runtime",
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


def _init_with_retry() -> None:
    import logging
    import time

    log = logging.getLogger("control-plane")
    delay = 2.0
    last: Exception | None = None
    for attempt in range(1, 31):
        try:
            init_db()
            seed()
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("veritabanı hazır değil (deneme %s/30): %s", attempt, exc)
            time.sleep(delay)
    raise RuntimeError("veritabanına bağlanılamadı") from last


def _loop(stop: threading.Event) -> None:
    import logging

    log = logging.getLogger("control-plane")
    while not stop.is_set():
        try:
            tick()
        except Exception:
            log.exception("scheduler tick failed")
        stop.wait(get_settings().scheduler_interval_seconds)


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "control_plane.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", settings.port)),
    )


if __name__ == "__main__":
    main()
