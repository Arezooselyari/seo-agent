"""فراخوانی embedding مدل Gemini — برای ایندکس کردن محتوا (document) و
برای جست‌وجوی کاربر (query). Gemini این دو task_type را جدا بهینه می‌کند.
"""
from __future__ import annotations

import time

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, TooManyRequests

from .config import Secrets, TenantConfig

_configured = False
_MAX_RETRIES = 5


def _embed_with_retry(**kwargs):
    for attempt in range(_MAX_RETRIES):
        try:
            return genai.embed_content(**kwargs)
        except (ResourceExhausted, TooManyRequests):
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(20 * (attempt + 1))  # backoff برای سقف rate limit رایگان


def ensure_configured(secrets: Secrets) -> None:
    global _configured
    if not _configured:
        if not secrets.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY در chatbot/.env تنظیم نشده است.")
        # transport="rest": شبکه‌ی برخی کاربران gRPC را مسدود می‌کند ولی REST عادی کار می‌کند.
        genai.configure(api_key=secrets.gemini_api_key, transport="rest")
        _configured = True


def embed_text(text: str, *, task_type: str = "retrieval_document",
               cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> list[float]:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    ensure_configured(secrets)
    result = _embed_with_retry(
        model=cfg.embedding_model, content=text, task_type=task_type,
        output_dimensionality=cfg.embedding_dim,
    )
    return result["embedding"]


def embed_texts(texts: list[str], *, task_type: str = "retrieval_document",
                cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> list[list[float]]:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    ensure_configured(secrets)
    if not texts:
        return []
    result = _embed_with_retry(
        model=cfg.embedding_model, content=texts, task_type=task_type,
        output_dimensionality=cfg.embedding_dim,
    )
    return result["embedding"]
