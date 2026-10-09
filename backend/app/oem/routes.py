from fastapi import APIRouter

from app.oem import registry

router = APIRouter(prefix="/api")


@router.get("/oem-registry")
def oem_registry() -> dict:
    d = registry.load()
    problems = registry.check(d)
    return d | {
        "consistent_with_code": not problems,
        "consistency_problems": problems,
        "targets": len(d["oems"]),
    }
