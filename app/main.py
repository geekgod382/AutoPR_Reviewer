from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.webhook import router as webhook_router
from app.payments import router as payments_router
from app.web import router as web_router
from app.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="AutoPR Reviewer",
    description="AI-Powered GitHub Pull Request Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(web_router)
app.include_router(webhook_router)
app.include_router(payments_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
