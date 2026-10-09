"""Mount the Round D stream-2 routers on the app for tests (until main.py includes them).

Importing this module also imports the stream-2 table models so create_all sees them. Mounting is
idempotent and is skipped for routers whose paths main.py already serves.
"""

from app.acquire import models as _acq_models  # noqa: F401
from app.acquire.routes import router as acquire_router
from app.explorer import models as _explorer_models  # noqa: F401
from app.explorer.routes import router as explorer_router
from app.identify import models as _id_models  # noqa: F401
from app.identify.routes import router as identify_router
from app.main import app
from app.oem.routes import router as oem_router
from app.recover.routes import router as recover_router

ROUTERS = (acquire_router, identify_router, explorer_router, recover_router, oem_router)


def mount() -> None:
    have = {getattr(r, "path", None) for r in app.router.routes}
    for r in ROUTERS:
        if not any(getattr(x, "path", None) in have for x in r.routes):
            app.include_router(r)


mount()
