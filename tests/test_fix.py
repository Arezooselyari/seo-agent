"""تست اتصال درست."""
import httpx
from src.config import Secrets

s = Secrets()
base = s.supabase_url.rstrip("/")
headers = {
    "apikey": s.supabase_key,
    "Authorization": f"Bearer {s.supabase_key}",
}

url = f"{base}/rest/v1/sources?select=id"
r = httpx.get(url, headers=headers, timeout=20)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    print("✅ درست شد!")
else:
    print(f"Response: {r.text[:200]}")
