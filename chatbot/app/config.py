"""بارگذاری config (مخصوص تنانت) و secrets (.env) — مستقل از src/config.py ریشه.

اصل SaaS-ready: کد موتور هیچ‌وقت نباید بداند «سایتِ من کدام است».
هر چیز مخصوص یک tenant از اینجا می‌آید، نه هاردکد در منطق.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent  # chatbot/


class WidgetSite(BaseModel):
    key: str
    origin: str


class BookingDayHours(BaseModel):
    start: str  # "09:00"
    end: str    # "17:00"


class BookingConfig(BaseModel):
    """⚠️ دیگر منبع حقیقتِ ساعت کاری نیست — فقط پشتیبان اضطراری.

    ساعت کاری، مرخصی و تعطیلات حالا از دیتابیس خوانده می‌شوند
    (جدول‌های availability_rules / availability_exceptions /
    booking_settings) و از پنل CRM تنظیم می‌شوند. جزئیات در
    app/availability.py.

    این کلاس فقط برای حالتی مانده که مایگریشن 004_crm.sql هنوز اجرا
    نشده باشد؛ در آن صورت booking.py به این مقادیر برمی‌گردد تا صفحه‌ی
    رزرو نخوابد. بعد از اجرای مایگریشن دیگر استفاده نمی‌شود.
    """

    enabled: bool = True
    slot_minutes: int = 30
    timezone: str = "Asia/Tehran"
    min_notice_hours: int = 2
    weekly_hours: dict[str, BookingDayHours] = Field(default_factory=dict)
    blackout_dates: list[str] = Field(default_factory=list)


class TenantConfig(BaseModel):
    """پیکربندی یک tenant. الان از config.yaml می‌آید؛
    در SaaS آینده می‌تواند از یک ردیف دیتابیس بیاید — بدون تغییر در کد موتور."""

    tenant_id: int = 1
    site_name: str = ""
    site_url: str = ""
    wp_url: str = ""

    chat_model: str = "gemini-2.5-flash"
    embedding_model: str = "models/gemini-embedding-001"
    embedding_dim: int = 768

    system_persona: str = ""

    rag_top_k: int = 5
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150

    short_term_turns: int = 10
    long_term_refresh_every: int = 6

    widget_sites: list[WidgetSite] = Field(default_factory=list)
    booking: BookingConfig = Field(default_factory=BookingConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "TenantConfig":
        path = path or (ROOT / "config.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)

    def widget_site_for_key(self, site_key: str) -> WidgetSite | None:
        for site in self.widget_sites:
            if site.key == site_key:
                return site
        return None


class Secrets(BaseSettings):
    """کلیدها و رمزها — همیشه بیرون از کد، از .env بارگذاری می‌شوند."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str = ""

    supabase_url: str = ""
    supabase_key: str = ""

    chatbot_telegram_bot_token: str = ""
    telegram_webhook_secret: str = "change-me"
    admin_telegram_chat_id: str = ""

    wp_url: str = ""

    widget_allowed_origins: str = ""

    app_base_url: str = "http://localhost:8000"

    def widget_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.widget_allowed_origins.split(",") if o.strip()]
