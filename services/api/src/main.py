import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler  # type: ignore[attr-defined]
from slowapi.errors import RateLimitExceeded

from src.agent.router import router as agent_router
from src.audit.router import router as audit_router
from src.auth.middleware import AuthMiddleware
from src.auth.openapi import docs_bearer_auth
from src.auth.router import router as auth_router
from src.catalogue.router import router as catalogue_router
from src.config import settings
from src.dashboards.router import router as dashboards_router
from src.db.connection import close_connection, init_connection
from src.db.init import bootstrap
from src.integrations.router import router as integrations_router
from src.limiter import limiter
from src.logging_config import configure_logging
from src.query.router import router as query_router
from src.scheduler import scheduler as job_scheduler
from src.superuser.router import router as superuser_router
from src.tenant.router import router as tenant_router
from src.transforms.router import router as transforms_router

configure_logging()
logger = structlog.get_logger(__name__)

_WEAK_SECRET = "change_me_in_production"
_WEAK_PASSWORD = "admin123"


def _check_production_secrets() -> None:
    """Refuse to start in non-debug mode with known-weak secrets."""
    if settings.debug:
        return
    errors = []
    if settings.api_secret_key == _WEAK_SECRET:
        errors.append(
            "API_SECRET_KEY is still the default placeholder — set a strong random value in .env"
        )
    if settings.admin_password == _WEAK_PASSWORD:
        errors.append(
            "ADMIN_PASSWORD is still 'admin123' — set a strong password in .env"
        )
    if errors:
        for msg in errors:
            logger.error("startup_refused", reason=msg)
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _check_production_secrets()
    logger.info("startup", host=settings.api_host, port=settings.api_port)
    await init_connection()
    bootstrap()
    job_scheduler.start(app)
    yield
    logger.info("shutdown")
    job_scheduler.stop()
    await close_connection()


app = FastAPI(
    title="Jonas Data Platform API",
    version="0.1.0",
    description="AI-native multi-tenant data platform",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(PermissionError)
async def permission_error_handler(_: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": "Forbidden"})


_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Token"],
)

app.add_middleware(AuthMiddleware)

# Auth router has no docs_bearer_auth dependency — it's the login endpoint itself
app.include_router(
    auth_router,
    prefix="/api/v1/auth",
    tags=["auth"],
)

app.include_router(
    catalogue_router,
    prefix="/api/v1/catalogue",
    tags=["catalogue"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    integrations_router,
    prefix="/api/v1/connectors",
    tags=["connectors"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    transforms_router,
    prefix="/api/v1/transforms",
    tags=["transforms"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    agent_router,
    prefix="/api/v1/agent",
    tags=["agent"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    audit_router,
    prefix="/api/v1/audit",
    tags=["audit"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    tenant_router,
    prefix="/api/v1/tenant",
    tags=["tenant"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    dashboards_router,
    prefix="/api/v1/dashboards",
    tags=["dashboards"],
    dependencies=[Depends(docs_bearer_auth)],
)

from src.collections.router import router as collections_router  # noqa: E402

app.include_router(
    collections_router,
    prefix="/api/v1/collections",
    tags=["collections"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    query_router,
    prefix="/api/v1/query",
    tags=["query"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    superuser_router,
    prefix="/api/v1/superuser",
    tags=["superuser"],
    dependencies=[Depends(docs_bearer_auth)],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
