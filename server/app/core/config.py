import os
from dotenv import load_dotenv

_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
_ENV_PATH = os.path.join(_ROOT_DIR, ".env")
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=True)
else:
    load_dotenv(override=True)


def _int(name, default):
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://postgres:postgres@127.0.0.1:54329/postgres?sslmode=disable",
)
DB_NAME = "nova_ai"
PORT = _int("PORT", 5001)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "all-minilm:latest")
OLLAMA_CODE_MODEL = os.environ.get("OLLAMA_CODE_MODEL", "qwen2.5-coder:1.5b")
OLLAMA_NUM_THREAD = _int("OLLAMA_NUM_THREAD", os.cpu_count() or 4)
OLLAMA_NUM_CTX = _int("OLLAMA_NUM_CTX", 4096)


def get_ollama_options(extra_options: dict | None = None) -> dict:
    opts = {
        "num_gpu": 0,
        "num_thread": OLLAMA_NUM_THREAD,
        "num_ctx": OLLAMA_NUM_CTX,
    }
    if extra_options:
        opts.update(extra_options)
    return opts


CODE_LLM_REVIEW = os.environ.get("CODE_LLM_REVIEW", "false").lower() == "true"
CODE_NUM_PREDICT = _int("CODE_NUM_PREDICT", 4096)
MAX_CONTINUATIONS = _int("MAX_CONTINUATIONS", 3)
MAX_OUTPUT_TOKENS = _int("MAX_OUTPUT_TOKENS", 4096)
DAILY_TOKEN_LIMIT = _int("DAILY_TOKEN_LIMIT", 100000)


RAG_TOP_K = _int("RAG_TOP_K", 8)
RAG_SIMILARITY_THRESHOLD = float(os.environ.get("RAG_SIMILARITY_THRESHOLD", 0.25))
RAG_MAX_CONTEXT_CHARS = _int("RAG_MAX_CONTEXT_CHARS", 6000)

RETRIEVAL_CACHE_TTL_MS = _int("RETRIEVAL_CACHE_TTL_MS", 60000)
EMBEDDING_CACHE_TTL_MS = _int("EMBEDDING_CACHE_TTL_MS", 86400000)

QDRANT_URL = os.environ.get("QDRANT_URL")

# Web retrieval provider: ddgs (default, no API key), tavily, exa, firecrawl
WEB_RETRIEVER_PROVIDER = os.environ.get("WEB_RETRIEVER_PROVIDER", "ddgs")

# Which VectorStore implementation the retrieval layer should use.
# See app/retrieval/vector_store.py for the abstraction and factory.
#
# ChromaDB is the default: it is a fully local, embedded, persistent vector
# store (no server process, no network, no API key), which matches Nova's
# "everything runs locally / offline" requirement. Qdrant remains fully
# implemented and selectable via VECTOR_STORE_BACKEND=qdrant (it additionally
# needs QDRANT_URL pointing at a running Qdrant instance).
#
# NOTE: switching backends does NOT migrate existing vectors. Documents that
# were indexed into Qdrant must be re-indexed to appear in Chroma (see
# server/scripts/backfill_qdrant.py for the equivalent Qdrant-side script).
VECTOR_STORE_BACKEND = os.environ.get("VECTOR_STORE_BACKEND", "chroma").lower()

# On-disk location for the embedded ChromaDB persistent client.
CHROMA_PATH = os.environ.get(
    "CHROMA_PATH", os.path.join(_ROOT_DIR, "server", "data", "chroma")
)

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"

# Authentication & Session Settings
JWT_SECRET = os.environ.get("JWT_SECRET", "nova-ai-jwt-super-secret-key-change-in-production-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_DAYS = _int("JWT_EXPIRES_DAYS", 30)
AUTH_COOKIE_NAME = "nova_session"
CSRF_COOKIE_NAME = "csrf_token"

# Whether auth/CSRF cookies get the `Secure` flag (HTTPS-only). Cookies with
# Secure set are silently dropped by browsers over plain HTTP, so this
# defaults to False for local dev and turns on automatically in production,
# or can be forced via COOKIE_SECURE=true (e.g. HTTPS behind a proxy in a
# non-"production" NODE_ENV).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() == "true" or os.environ.get("NODE_ENV", "development") == "production"

# Google OAuth Settings
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:5001/api/auth/google/callback")

NODE_ENV = os.environ.get("NODE_ENV", "development")
