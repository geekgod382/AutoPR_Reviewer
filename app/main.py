from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
import os

from app.webhook import router as webhook_router
from app.payments import router as payments_router
from app.web import router as web_router
from app.oauth import router as oauth_router
from app.database import create_tables, get_session


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
app.include_router(oauth_router)
app.include_router(webhook_router)
app.include_router(payments_router)


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    try:
        db = get_session()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "ok", "db": "error", "detail": str(e)}
