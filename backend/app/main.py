import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Schema bootstrap for now; swap for migrations once the schema starts changing.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Nirikshan API", version="0.1.0", lifespan=lifespan)

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
