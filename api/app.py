"""
MenaBot FastAPI application entry point.

Composes the FastAPI app from:
  - lifespan handler (telemetry + graph singleton init)
  - CORS middleware
  - optional rate limiter (slowapi, graceful if missing)
  - route modules under api/routes/

SSE event types emitted by /chat are documented in api/streaming.py.

Run with:
    uvicorn api.app:app --host 0.0.0.0 --port 8000
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api import _runtime
from api.routes import chat, conversations, exports, feedback, health
from core.telemetry import setup_azure_telemetry
from orchestrator.supervisor import get_graph

logger = logging.getLogger(__name__)

# ── Optional rate limiting (graceful if slowapi not installed) ──
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    _rate_limiting_available = True
except ImportError:
    limiter = None
    _rate_limiting_available = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    setup_azure_telemetry(app)
    if _runtime.graph is None:
        _runtime.graph = await get_graph()
    yield


# ── FastAPI App ──
app = FastAPI(
    lifespan=lifespan,
    title="MenaBot RAG Service - M365 Agents SDK + LangGraph",
    description=(
        "Backend service for MenaBot using LangGraph for RAG orchestration. "
        "Endpoints: /health, /chat, /feedback, /conversations."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=("*" not in _ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register rate limiter if available
if _rate_limiting_available and limiter:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Mount routers ──
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(exports.router)
app.include_router(feedback.router)
app.include_router(conversations.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
