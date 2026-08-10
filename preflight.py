"""چک پیش‌پروازی — همه‌ی اتصالات حیاتی را تست می‌کند و به preflight.log می‌نویسد.
از طریق یک Task آزمایشی (با تزریق پروکسی) اجرا می‌شود تا دقیقاً شرایط اجرای
خودکار فردا صبح را بسنجد: IP/کشور، Gemini، Pexels، تلگرام، Supabase.
"""
import json
import os
import urllib.request
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preflight.log")


def w(line: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def main() -> None:
    w("=" * 55)
    w(f"چک پیش‌پروازی — {datetime.now():%Y-%m-%d %H:%M:%S}")
    w(f"پروکسی در محیط: HTTPS_PROXY={os.environ.get('HTTPS_PROXY', '(ندارد!)')}")
    w("-" * 55)

    # ۱) IP/کشور
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "curl/8"})
        d = json.load(urllib.request.urlopen(req, timeout=20))
        w(f"۱) شبکه:    IP={d.get('ip')}  کشور={d.get('country')}")
    except Exception as e:  # noqa: BLE001
        w(f"۱) شبکه:    ❌ {str(e)[:60]}")

    # ۲) Gemini
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        r = genai.GenerativeModel("gemini-2.5-flash").generate_content("ping")
        w(f"۲) Gemini:  ✅ کار می‌کند ({r.text[:12]!r})")
    except Exception as e:  # noqa: BLE001
        w(f"۲) Gemini:  ❌ {str(e)[:70]}")

    # ۳) Pexels
    try:
        from src.config import Secrets
        from src.images import fetch_pexels_images
        imgs = fetch_pexels_images("artificial intelligence", Secrets(), count=1)
        w(f"۳) Pexels:  {'✅ عکس آمد' if imgs else '❌ عکس نیامد'}")
    except Exception as e:  # noqa: BLE001
        w(f"۳) Pexels:  ❌ {str(e)[:60]}")

    # ۴) تلگرام (getMe — بدون فرستادن پیام)
    try:
        import httpx
        tok = os.getenv("TELEGRAM_BOT_TOKEN")
        ok = httpx.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json().get("ok")
        tok2 = os.getenv("TELEGRAM_BOT_TOKEN_2")
        ok2 = True
        if tok2:
            ok2 = httpx.get(f"https://api.telegram.org/bot{tok2}/getMe", timeout=15).json().get("ok")
        w(f"۴) تلگرام:  {'✅ هر دو بات' if (ok and ok2) else ('✅ بات اول' if ok else '❌ ناموفق')}")
    except Exception as e:  # noqa: BLE001
        w(f"۴) تلگرام:  ❌ {str(e)[:60]}")

    # ۵) Supabase + شمارش مقاله‌های امروز
    try:
        from src.config import Secrets, TenantConfig
        from src import db
        cfg = TenantConfig.load()
        c = db.get_client(Secrets())
        t = date.today().isoformat()
        res = (c.table("articles").select("id").eq("tenant_id", cfg.tenant_id)
               .gte("created_at", f"{t}T00:00:00Z").lt("created_at", f"{t}T23:59:59Z").execute())
        n = len(res.data) if res.data else 0
        w(f"۵) Supabase: ✅ وصل — امروز {n} مقاله (هدف روزانه: {cfg.articles_per_run})")
    except Exception as e:  # noqa: BLE001
        w(f"۵) Supabase: ❌ {str(e)[:60]}")

    w("=" * 55)
    w("")


if __name__ == "__main__":
    main()
