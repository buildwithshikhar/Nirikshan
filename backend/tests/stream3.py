"""Mount the Stream 3 routers (events, correlation, validation center) on the test app.

Importing this module registers the new tables on Base.metadata before the `client` fixture runs
create_all. A router is added only if app.main does not already serve its paths, so the tests
keep working after the lead wires them into app.main.
"""

from app.correlation import models as _correlation_models  # noqa: F401
from app.correlation.routes import router as correlation_router
from app.events import models as _event_models  # noqa: F401
from app.events.routes import router as events_router
from app.main import app

ROUTERS = [events_router, correlation_router]


def mount() -> None:
    served = {getattr(r, "path", "") for r in app.routes}
    for router in ROUTERS:
        if any(getattr(r, "path", "") not in served for r in router.routes):
            app.include_router(router)


mount()
