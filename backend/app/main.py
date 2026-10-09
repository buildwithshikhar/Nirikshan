import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import (  # noqa: F401  (triggers: DDL events before create_all)
    __version__,
    schema,
    triggers,
)
from app.acquire import models as _acquire_models  # noqa: F401
from app.acquire.routes import router as acquire_router
from app.analytics import models as _analytics_models  # noqa: F401  (tables before create_all)
from app.analytics.routes import router as analytics_router
from app.approvals import models as _approval_models  # noqa: F401
from app.approvals.routes import router as approvals_router
from app.auth import models as _auth_models  # noqa: F401
from app.auth.deps import audit_identity
from app.auth.policy import authorize
from app.auth.routes import router as auth_router
from app.correlation import models as _correlation_models  # noqa: F401
from app.correlation.routes import router as correlation_router
from app.db import SessionLocal, engine
from app.events import fts as _event_fts  # noqa: F401  (drops ai_events_fts with ai_events)
from app.events import models as _event_models  # noqa: F401
from app.events.routes import router as events_router
from app.explorer import models as _explorer_models  # noqa: F401
from app.explorer.routes import router as explorer_router
from app.identify import models as _identify_models  # noqa: F401
from app.identify.routes import router as identify_router
from app.jobs import models as _jobs_models  # noqa: F401
from app.jobs.manager import manager as job_manager
from app.jobs.routes import router as jobs_router
from app.models import AuditEntry
from app.oem.routes import router as oem_router
from app.package import models as _package_models  # noqa: F401
from app.package.routes import router as package_router
from app.perf import models as _perf_models  # noqa: F401
from app.perf.routes import router as perf_router
from app.recover.routes import router as recover_router
from app.report import models as _report_models  # noqa: F401
from app.report.routes import router as report_router
from app.routes import audit_case_id, router
from app.timeline import models as _timeline_models  # noqa: F401
from app.timeline.routes import router as timeline_router
from app.validation_center import models as _vc_models  # noqa: F401
from app.validation_center.routes import router as validation_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Refuses an outdated database (no migrations yet); creates + stamps a fresh one.
    schema.check_and_init(engine)
    with SessionLocal() as db:  # jobs/runs left running by a previous process cannot be running
        job_manager.recover(db)
    yield
    job_manager.shutdown()


# Every route passes app.auth.policy.authorize (fail closed for routes without a rule).
app = FastAPI(
    title="Nirikshan API",
    version=__version__,
    lifespan=lifespan,
    dependencies=[Depends(authorize)],
)

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
app.include_router(jobs_router)
for _r in (
    events_router,
    correlation_router,
    validation_router,
    acquire_router,
    identify_router,
    explorer_router,
    recover_router,
    oem_router,
):
    app.include_router(_r)
app.include_router(auth_router)
app.include_router(approvals_router)
app.include_router(package_router)
app.include_router(perf_router)


@app.middleware("http")
async def audit_trail(request: Request, call_next):
    """Record every /api request (method, path, status, authenticated principal) in audit_log."""
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.url.path != "/api/audit":
        with SessionLocal() as db:
            db.add(
                AuditEntry(
                    examiner=audit_identity(request),
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    case_id=audit_case_id(request.url.path),
                )
            )
            db.commit()
    return response
