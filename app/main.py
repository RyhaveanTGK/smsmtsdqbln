from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .api.routes import router
from .config import get_settings
from .database import init_db
from .workers.sms_worker import SMSWorker

logging.basicConfig(level=logging.INFO)
settings = get_settings()
worker = SMSWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    task = asyncio.create_task(worker.start())
    yield
    await worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        try:
            if content_length and int(content_length) > settings.max_request_bytes:
                return JSONResponse({"detail": "Sorğu çox böyükdür."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Content-Length etibarsızdır."}, status_code=400)
        return await call_next(request)


app = FastAPI(title="Toplu SMS Admin Panel", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.state.sms_worker = worker
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="sms_admin_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=settings.cookie_secure,
)
app.add_middleware(RequestSizeLimitMiddleware)
app.include_router(router)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
