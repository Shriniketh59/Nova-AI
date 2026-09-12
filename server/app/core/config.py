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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "all-minilm:latest")
OLLAMA_CODE_MODEL = os.environ.get("OLLAMA_CODE_MODEL", "qwen2.5-coder:1.5b")

CODE_LLM_REVIEW = os.environ.get("CODE_LLM_REVIEW", "false").lower() == "true"
CODE_NUM_PREDICT = _int("CODE_NUM_PREDICT", 2048)
MAX_CONTINUATIONS = _int("MAX_CONTINUATIONS", 3)

RAG_API_URL = os.environ.get("RAG_API_URL", f"http://127.0.0.1:{PORT}")
RAG_TOP_K = _int("RAG_TOP_K", 8)
RAG_SIMILARITY_THRESHOLD = float(os.environ.get("RAG_SIMILARITY_THRESHOLD", 0.25))
RAG_MAX_CONTEXT_CHARS = _int("RAG_MAX_CONTEXT_CHARS", 6000)

RETRIEVAL_CACHE_TTL_MS = _int("RETRIEVAL_CACHE_TTL_MS", 60000)
EMBEDDING_CACHE_TTL_MS = _int("EMBEDDING_CACHE_TTL_MS", 86400000)

QDRANT_URL = os.environ.get("QDRANT_URL")

# Which VectorStore implementation the retrieval layer should use.
# See app/retrieval/vector_store.py for the abstraction and factory.
VECTOR_STORE_BACKEND = os.environ.get("VECTOR_STORE_BACKEND", "qdrant").lower()

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"

NODE_ENV = os.environ.get("NODE_ENV", "development")
