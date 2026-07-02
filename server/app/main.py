import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.config import QDRANT_URL, NODE_ENV
from .core.db import init_db
from .core.logger import logger
from .retrieval.qdrant_client import ensure_all_collections
from .routes import chats, upload, query, agent_chat, ide_agent, fs_route, nova_route, health, translate, interview_coach, documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info("request", {
        "method": request.method,
        "route": request.url.path,
        "status": response.status_code,
        "latencyMs": round((time.time() - start) * 1000),
    })
    return response


# TODO(security): this is a no-op placeholder hook for future auth/authz and
# rate-limiting. Everything today runs as DEFAULT_USER_ID with no session
# concept — before multi-tenant/production use, replace the pass-through
# below with real request authentication (e.g. verify a bearer token / API
# key, attach the resolved user to request.state.user) and a rate limiter
# (e.g. token bucket per API key/IP), and reject unauthenticated/
# over-quota requests before they reach route handlers.
@app.middleware("http")
async def auth_and_rate_limit_stub(request: Request, call_next):
    return await call_next(request)


app.include_router(chats.router)
app.include_router(upload.router)
app.include_router(query.router)
app.include_router(agent_chat.router)
app.include_router(ide_agent.router)
app.include_router(fs_route.router)
app.include_router(nova_route.router)
app.include_router(health.router)
app.include_router(translate.router)
app.include_router(interview_coach.router)
app.include_router(documents.router)

DIST_PATH = os.path.join(os.path.dirname(__file__), "../../dist")
if os.path.isdir(DIST_PATH):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_PATH, "assets")), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    from fastapi import HTTPException

    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    # Mirrors express.static(distPath): any real file in dist/ (logo.png,
    # favicon.svg, ...) is served directly; anything else falls back to
    # index.html for client-side routing.
    candidate = os.path.join(DIST_PATH, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)

    index_path = os.path.join(DIST_PATH, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not built")


@app.on_event("startup")
async def on_startup():
    if NODE_ENV == "test":
        return
    await init_db()
    if QDRANT_URL:
        try:
            await ensure_all_collections()
            logger.info("Qdrant collections ready.")
        except Exception as err:
            logger.warn("Qdrant unreachable, falling back to in-Python search", {"error": str(err)})
