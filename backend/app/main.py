import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import (  # noqa: F401  (triggers: DDL events before create_all)
    __version__,
    schema,
    triggers,
)
from app.analytics import models as _analytics_models  # noqa: F401  (tables before create_all)
from app.analytics.routes import router as analytics_router
from app.db import SessionLocal, engine
from app.models import AuditEntry
from app.report import models as _report_models  # noqa: F401
from app.report.routes import router as report_router
from app.routes import audit_case_id, router
from app.timeline import models as _timeline_models  # noqa: F401
from app.timeline.routes import router as timeline_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Refuses an outdated database (no migrations yet); creates + stamps a fresh one.
    schema.check_and_init(engine)
    yield


app = FastAPI(title="Nirikshan API", version=__version__, lifespan=lifespan)

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nirikshan-api", "version": app.version}


app.include_router(router)
app.include_router(analytics_router)
app.include_router(timeline_router)
app.include_router(report_router)


@app.middleware("http")
async def audit_trail(request: Request, call_next):
    """Record every /api request (method, path, status, examiner attestation) in audit_log."""
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.url.path != "/api/audit":
        with SessionLocal() as db:
            db.add(
                AuditEntry(
                    examiner=request.headers.get("x-examiner", "").strip(),
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    case_id=audit_case_id(request.url.path),
                )
            )
            db.commit()
    return response
