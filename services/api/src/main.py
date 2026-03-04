from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.agent.router import router as agent_router
from src.auth.middleware import AuthMiddleware
from src.catalogue.router import router as catalogue_router
from src.db.connection import close_connection, init_connection
from src.db.init import bootstrap
from src.integrations.router import router as integrations_router
from src.transforms.router import router as transforms_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)

app.include_router(catalogue_router, prefix="/api/v1/catalogue", tags=["catalogue"])
app.include_router(
    integrations_router, prefix="/api/v1/integrations", tags=["integrations"]
)
app.include_router(transforms_router, prefix="/api/v1/transforms", tags=["transforms"])
app.include_router(agent_router, prefix="/api/v1/agent", tags=["agent"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
