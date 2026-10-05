import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.db import Base, SessionLocal, engine
from app.models import AuditEntry
from app.routes import audit_case_id, router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Schema bootstrap for now; swap for migrations once the schema starts changing.
    Base.metadata.create_all(engine)
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
