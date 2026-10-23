"""
Unified Azure OpenAI client helper.
Supports both the Responses API (gpt-5.x) and Chat Completions API (gpt-4o etc.)
depending on what the endpoint URL signals.
"""
from openai import AzureOpenAI
import backend.config as config

_client: AzureOpenAI | None = None
_embed_client: AzureOpenAI | None = None

def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )
    return _client

def get_embed_client() -> AzureOpenAI:
    """Separate client for embeddings — may use a different API version."""
    global _embed_client
    if _embed_client is None:
        _embed_client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_EMBEDDING_API_VERSION,
        )
    return _embed_client

def chat(prompt: str, max_tokens: int = 300, temperature: float = 0.75,
         json_mode: bool = False) -> str:
    """
    Send a prompt to the configured model and return the text response.
    Uses Chat Completions API with max_completion_tokens (required for gpt-5.x).
    """
    client = get_client()
    kwargs = dict(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=max_tokens,
        temperature=temperature,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()
