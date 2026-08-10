"""اجرای خودکار روزانه + ربات تلگرام همزمان.

یک process واحد:
  • APScheduler هر روز ساعت run_time (config.yaml) pipeline را اجرا می‌کند
  • ربات تلگرام در thread جداگانه همیشه گوش می‌دهد
  • هر خطا فوراً به تلگرام گزارش می‌شود

اجرا:
    pythonw -m src.scheduler     ← بدون پنجره (برای Task Scheduler ویندوز)
    python  -m src.scheduler     ← با خروجی console (برای تست)
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Secrets, TenantConfig
from .notify import notify_error, send_telegram
from . import pipeline
from .bot import run_bot

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scheduler")


def _run_pipeline(cfg: TenantConfig, secrets: Secrets) -> None:
    """Pipeline را اجرا و نتیجه را لاگ می‌کند."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"▶ شروع pipeline — {now}")
    try:
        ids = pipeline.run(cfg=cfg, secrets=secrets)
        if ids:
            log.info(f"✅ {len(ids)} مقاله ساخته شد.")
        else:
            log.warning("⚠️ هیچ مقاله‌ای ساخته نشد.")
            send_telegram(
                "⚠️ Pipeline اجرا شد ولی مقاله‌ای تولید نشد.\n"
                "احتمالاً موضوع جدیدی در RSS نبود یا quota تمام شده.",
                secrets,
            )
    except Exception as e:  # noqa: BLE001
        log.error(f"❌ Pipeline خطا: {e}")
        notify_error("scheduler", str(e), secrets)


def _start_bot_thread(cfg: TenantConfig, secrets: Secrets) -> None:
    """ربات تلگرام را در thread پس‌زمینه با auto-restart اجرا می‌کند."""
    def _loop() -> None:
        while True:
            try:
                run_bot(cfg=cfg, secrets=secrets)
            except Exception as e:  # noqa: BLE001
                log.error(f"[bot] crash — 30 ثانیه دیگر restart: {e}")
                time.sleep(30)

    t = threading.Thread(target=_loop, name="telegram-bot", daemon=True)
    t.start()
    log.info("🤖 ربات تلگرام در پس‌زمینه شروع شد.")


def run(cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> None:
    """Scheduler اصلی — تا وقتی که process زنده است اجرا می‌شود."""
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()

    hour, minute = cfg.run_time.split(":")
    log.info(f"📅 Pipeline هر روز ساعت {cfg.run_time} اجرا می‌شود.")

    # ربات تلگرام در پس‌زمینه
    _start_bot_thread(cfg, secrets)

    # پیام شروع به تلگرام
    send_telegram(
        f"🚀 ایجنت محتوا شروع به کار کرد.\n"
        f"📅 مقاله هر روز ساعت {cfg.run_time} ارسال می‌شود.\n"
        f"❓ /help برای راهنمای ربات",
        secrets,
    )

    # APScheduler — ساعت ایران (Asia/Tehran)
    scheduler = BlockingScheduler(timezone="Asia/Tehran")
    scheduler.add_job(
        _run_pipeline,
        trigger=CronTrigger(
            hour=int(hour),
            minute=int(minute),
            timezone="Asia/Tehran",
        ),
        args=[cfg, secrets],
        id="daily_pipeline",
        name="تولید مقاله‌ی روزانه",
        misfire_grace_time=3600,  # اگر PC خاموش بود و job از دست رفت، تا ۱ ساعت بعد هم اجرا شود
        coalesce=True,            # چند job از‌دست‌رفته = فقط یک اجرا
    )

    log.info("⏰ Scheduler آماده است. Ctrl+C برای توقف.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Scheduler متوقف شد.")
        send_telegram("🛑 ایجنت محتوا متوقف شد.", secrets)


if __name__ == "__main__":
    run()
