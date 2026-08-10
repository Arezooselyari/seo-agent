"""بارگذاری config (مخصوص صاحب) و secrets (.env).

اصل SaaS-ready: کد موتور هیچ‌وقت نباید بداند «سایتِ من کدام است».
هر چیز مخصوص یک tenant از اینجا می‌آید، نه هاردکد در منطق.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Source(BaseModel):
    name: str
    rss: str


class TenantConfig(BaseModel):
    """پیکربندی یک tenant. الان از config.yaml می‌آید؛
    در SaaS آینده از یک ردیف دیتابیس می‌آید — بدون تغییر در کد موتور."""

    tenant_id: int = 1
    sources: list[Source] = Field(default_factory=list)
    articles_per_run: int = 3
    target_language: str = "fa"
    run_time: str = "09:00"
    ai_keywords: list[str] = Field(default_factory=list)
    ai_provider: str = "gemini"
    ai_model: str = "gemini-2.0-flash-exp"
    site_name: str = ""
    site_url: str = ""
    site_category_url: str = ""
    site_category_name: str = "هوش مصنوعی"

    @classmethod
    def load(cls, path: Path | None = None) -> "TenantConfig":
        path = path or (ROOT / "config.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)


class Secrets(BaseSettings):
    """کلیدها و رمزها — همیشه بیرون از کد، از .env بارگذاری می‌شوند."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    supabase_url: str = ""
    supabase_key: str = ""

    wp_url: str = ""
    wp_user: str = ""
    wp_app_password: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # تلگرام دوم (اختیاری) — مقاله به هر دو مقصد ارسال می‌شود
    telegram_bot_token_2: str = ""
    telegram_chat_id_2: str = ""

    pexels_api_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    review_email_to: str = ""

    app_base_url: str = "http://localhost:8000"
    approval_secret: str = "change-me"
