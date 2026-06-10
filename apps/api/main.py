from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.dependencies.stack import get_stack
from apps.api.routes.admin_config import router as admin_router
from apps.api.routes.admin_traces import router as admin_traces_router
from apps.api.routes.admin_clients import router as admin_clients_router
from apps.api.routes.admin_client_config import router as admin_client_config_router
from apps.api.routes.admin_client_uploads import router as admin_client_uploads_router
from apps.api.routes.admin_client_drive_sources import router as admin_client_drive_sources_router
from apps.api.routes.admin_client_web_sources import router as admin_client_web_sources_router
from apps.api.routes.admin_client_jobs import router as admin_client_jobs_router
from apps.api.routes.admin_client_pipeline import router as admin_client_pipeline_router
from apps.api.routes.chat import router as chat_router
from apps.api.routes.chat_v2 import router as chat_v2_router
from apps.api.routes.admin_preview import router as admin_preview_router
from apps.api.routes.config import router as config_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_stack()
    yield


app = FastAPI(title="Modular Chatbot API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(chat_v2_router)
app.include_router(config_router)
app.include_router(admin_clients_router)
app.include_router(admin_client_config_router)
app.include_router(admin_client_uploads_router)
app.include_router(admin_client_web_sources_router)
app.include_router(admin_client_drive_sources_router)
app.include_router(admin_client_jobs_router)
app.include_router(admin_client_pipeline_router)
app.include_router(admin_preview_router)
app.include_router(admin_traces_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
