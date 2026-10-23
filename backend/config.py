import os
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv()

def _base_url(raw: str) -> str:
    """Extract just the scheme+host from a full Azure endpoint URL."""
    p = urlparse(raw)
    return f"{p.scheme}://{p.netloc}/"

def _api_version_from_url(raw: str, fallback: str) -> str:
    """Pull api-version from query string if embedded in the endpoint URL."""
    qs = parse_qs(urlparse(raw).query)
    return qs.get("api-version", [fallback])[0]

_raw_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")

AZURE_OPENAI_ENDPOINT = _base_url(_raw_endpoint) if _raw_endpoint else ""
AZURE_OPENAI_API_KEY  = os.getenv("AZURE_OPENAI_API_KEY", "")

# Support both AZURE_OPENAI_DEPLOYMENT and AZURE_OPENAI_MODEL
AZURE_OPENAI_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_DEPLOYMENT")
    or os.getenv("AZURE_OPENAI_MODEL")
    or "gpt-4o"
)

# Support AZURE_OPENAI_TEXT_EMBEDDING as alias for embedding deployment name
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    or os.getenv("AZURE_OPENAI_TEXT_EMBEDDING")
    or "text-embedding-ada-002"
)

# Embedding may use a different API version than chat (e.g. 2023-05-15)
AZURE_OPENAI_EMBEDDING_API_VERSION = (
    os.getenv("AZURE_OPENAI_EMBEDDING_VERSION")
    or os.getenv("AZURE_OPENAI_API_VERSION")
    or "2023-05-15"
)

# Prefer version embedded in the endpoint URL (e.g. ?api-version=2025-04-01-preview)
AZURE_OPENAI_API_VERSION = _api_version_from_url(
    _raw_endpoint,
    fallback=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
)

# Detect whether this resource uses the Responses API (/openai/responses)
# vs the classic Chat Completions API (/openai/deployments/.../chat/completions)
USE_RESPONSES_API = "/openai/responses" in _raw_endpoint

def validate():
    missing = [k for k, v in {
        "AZURE_OPENAI_ENDPOINT": AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY":  AZURE_OPENAI_API_KEY,
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")
    print(f"[Config] Endpoint : {AZURE_OPENAI_ENDPOINT}")
    print(f"[Config] Model    : {AZURE_OPENAI_DEPLOYMENT}")
    print(f"[Config] API ver  : {AZURE_OPENAI_API_VERSION}")
    print(f"[Config] API mode : {'Responses API' if USE_RESPONSES_API else 'Chat Completions'}")
    print(f"[Config] Embedding: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT} (api-version: {AZURE_OPENAI_EMBEDDING_API_VERSION})")
