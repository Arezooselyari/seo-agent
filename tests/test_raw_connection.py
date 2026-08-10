"""تست خام Supabase API."""
import httpx
from src.config import Secrets

s = Secrets()

if not s.supabase_url or not s.supabase_key:
    print("❌ کلیدها موجود نیستند")
else:
    base = s.supabase_url.rstrip("/")
    headers = {"Authorization": f"Bearer {s.supabase_key}"}

    # GET موارد از جدول sources
    url = f"{base}/rest/v1/sources?select=id"
    try:
        r = httpx.get(url, headers=headers, timeout=20)
        print(f"Status: {r.status_code}")
        print(f"Headers sent: Authorization + Content-Type")
        print(f"Response: {r.text[:300]}")
        if r.status_code == 200:
            print("✅ اتصال موفق!")
    except Exception as e:
        print(f"❌ خطا: {e}")
