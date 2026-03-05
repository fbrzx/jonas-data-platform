import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler  # type: ignore[attr-defined]
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.agent.router import router as agent_router
from src.auth.openapi import docs_bearer_auth
from src.auth.middleware import AuthMiddleware
from src.catalogue.router import router as catalogue_router
from src.config import settings
from src.db.connection import close_connection, init_connection
from src.db.init import bootstrap
from src.integrations.router import router as integrations_router
from src.transforms.router import router as transforms_router

logger = logging.getLogger(__name__)

_WEAK_SECRET = "change_me_in_production"


def _get_user_id(request: Request) -> str:
    """Rate-limit key: use authenticated user_id, fall back to remote IP."""
    user = getattr(request.state, "user", None) or {}
    return str(user.get("user_id") or get_remote_address(request))


limiter = Limiter(key_func=_get_user_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if settings.api_secret_key == _WEAK_SECRET and not settings.debug:
        warnings.warn(
            "API_SECRET_KEY is still the default placeholder — set a strong secret in .env",
            stacklevel=1,
        )
    await init_connection()
    bootstrap()
    yield
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Token"],
)

app.add_middleware(AuthMiddleware)

app.include_router(
    catalogue_router,
    prefix="/api/v1/catalogue",
    tags=["catalogue"],
    dependencies=[Depends(docs_bearer_auth)],
)
app.include_router(
    integrations_router,
    prefix="/api/v1/integrations",
    tags=["integrations"],
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
