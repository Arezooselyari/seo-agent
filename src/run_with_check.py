"""اسکریپت هوشمند — هر ۱۵ دقیقه اجرا شود.

چک می‌کند: "آیا امروز مقاله‌های روز فرستاده شدند؟"
- اگر بله: خروج (تکراری نشود)
- اگر نه: شروع pipeline و تولید مقاله‌ها

اگر اجرا به‌خاطر قطعیِ VPN/دسترسی به Gemini شکست خورد، یک هشدار فارسیِ
واضح به تلگرام می‌فرستد (در صورتی که تلگرام در دسترس باشد) تا کاربر باخبر شود.
"""
from datetime import date
from .config import Secrets, TenantConfig
from . import db, pipeline
from .notify import send_telegram


def _looks_like_network_block(err: str) -> bool:
    """تشخیص اینکه خطا از قطعیِ شبکه/VPN است (Gemini یا تلگرام بلاک شده)."""
    markers = [
        "403", "permissiondenied", "http2 header",
        "connecterror", "connecttimeout", "connectionerror",
        "failed to establish", "getaddrinfo", "sslerror",
        "connection aborted", "remotedisconnected", "max retries",
        "timed out", "name or service not known", "unreachable",
        "server disconnected", "remoteprotocolerror", "remoteerror",
        "http2", "protocol error",
    ]
    low = err.lower()
    return any(m in low for m in markers)


def run_if_needed():
    """Check if today's articles already sent. If not, run pipeline."""
    cfg = TenantConfig.load()
    secrets = Secrets()
    db.init_db(secrets)

    today_date = date.today().isoformat()

    with db.connect(secrets) as client:
        # چک: امروز چند مقاله ساخته شده؟
        result = (
            client.table("articles")
            .select("id", count="exact")
            .eq("tenant_id", cfg.tenant_id)
            .gte("created_at", f"{today_date}T00:00:00Z")
            .lt("created_at", f"{today_date}T23:59:59Z")
            .execute()
        )

        today_count = len(result.data) if result.data else 0
        target_count = cfg.articles_per_run

        if today_count >= target_count:
            print(
                f"✅ امروز {today_count} مقاله فرستاده شدند "
                f"(هدف: {target_count}). اسکیپ."
            )
            return

    print(
        f"❌ امروز فقط {today_count} مقاله ساخته شده "
        f"(هدف: {target_count}). شروع pipeline..."
    )

    try:
        pipeline.run()
    except Exception as e:  # noqa: BLE001
        err = str(e)
        low = err.lower().replace(" ", "")
        if "perday" in low or "requestsperday" in low:
            # سهمیه‌ی روزانه‌ی Gemini رایگان (۲۰/روز) تمام شده — تا فردا آزاد نمی‌شود.
            send_telegram(
                "⚠️ <b>سهمیه‌ی روزانه‌ی Gemini تمام شد</b>\n\n"
                "نسخه‌ی رایگان Gemini روزانه سقفِ محدودی دارد و امروز پر شد.\n\n"
                "👉 سهمیه فردا خودکار آزاد می‌شود و مقاله‌ها ساخته می‌شوند. "
                "برای استفاده‌ی نامحدود می‌توانید صورت‌حساب (Billing) را در حساب Gemini فعال کنید.",
                secrets,
            )
            print("⚠️ سهمیه‌ی روزانه‌ی Gemini تمام شد — هشدار به تلگرام فرستاده شد.")
        elif _looks_like_network_block(err):
            # احتمالاً VPN قطع است یا Gemini در دسترس نیست.
            # اگر تلگرام در دسترس باشد، هشدار می‌رسد؛ اگر VPN کاملاً قطع باشد،
            # تلگرام هم بلاک است و این پیام بی‌صدا رد می‌شود — ولی اجرای بعدی
            # (هر ۱۵ دقیقه تا ساعت ۱۱) خودش دوباره تلاش می‌کند.
            send_telegram(
                "⚠️ <b>اجرای امروز ناموفق بود</b>\n\n"
                "به نظر می‌رسد <b>VPN قطع است</b> یا اتصال به Gemini برقرار نشد "
                "(خطای دسترسی شبکه).\n\n"
                "👉 لطفاً VPN را روشن و پایدار کنید. سیستم تا ساعت ۱۱ صبح هر ۱۵ دقیقه "
                "دوباره تلاش می‌کند و به محض وصل‌شدن، مقاله‌ها ساخته و فرستاده می‌شوند.",
                secrets,
            )
            print("⚠️ خطای شبکه/VPN تشخیص داده شد — هشدار به تلگرام فرستاده شد.")
        else:
            send_telegram(
                "❌ <b>اجرای امروز با خطا متوقف شد</b>\n"
                f"<code>{err[:400]}</code>",
                secrets,
            )
            print(f"❌ خطای غیرشبکه‌ای: {err[:200]}")
        raise


if __name__ == "__main__":
    run_if_needed()
