"""بارگذاری تنظیمات و متغیرهای محیطی پروژه."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
LOGS_DIR = ROOT / "logs"
PROMPTS_DIR = ROOT / "prompts"

# .env پروژه‌ی اصلی (D:\prjcluade\.env) — توکن تلگرام مشترک آن‌جاست
PARENT_ENV = ROOT.parent / ".env"

# اول .env محلی seo-agent، سپس .env پروژه‌ی اصلی به‌عنوان fallback
load_dotenv(CONFIG_DIR / ".env")
load_dotenv(PARENT_ENV)

for d in (DATA_DIR, OUTPUT_DIR, LOGS_DIR):
    d.mkdir(exist_ok=True)


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> list[dict]:
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def env(name: str, required: bool = False) -> str | None:
    val = os.getenv(name)
    if required and not val:
        raise RuntimeError(f"متغیر محیطی {name} در config/.env تنظیم نشده است")
    return val
