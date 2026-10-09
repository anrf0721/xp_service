import os
from contextlib import asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from xp_owner_service.app.routers import handoff, internal
from xp_owner_service.app.routers.chat import conversation, messages
from xp_owner_service.common import Rejected
from xp_owner_service.infrastructure.database import sessions
from xp_owner_service.worker.ai.worker import loop


@asynccontextmanager
async def lifespan(app):
    if not os.environ.get("XP_INTERNAL_SERVICE_TOKEN"):
        raise RuntimeError("Internal service token is required")
    stop, thread = Event(), None
    if os.environ.get("XP_AI_WORKER_ENABLED", "true").lower() == "true":
        thread = Thread(target=loop, args=(sessions(), stop), daemon=True, name="owner-ai-worker")
        thread.start()
    yield
    stop.set()
    if thread is not None:
        thread.join(timeout=15)


app = FastAPI(title="XP Owner Service", lifespan=lifespan)
app.include_router(messages.router)
app.include_router(conversation.router)
app.include_router(handoff.router)
app.include_router(internal.router)


@app.exception_handler(Rejected)
async def rejected(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"reason": exc.reason})


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": "invalid request"})


@app.middleware("http")
async def protect_error_details(request, call_next):
    try:
        return await call_next(request)
    except Exception:
        # Consume the exception before the server can log connection strings.
        return JSONResponse(status_code=500, content={"detail": "internal error"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "xp_owner_service"}
