"""تست ساخت پیش‌نویس آزمایشی روی وردپرس."""
import base64
import httpx

WP_URL = "https://sagharnazari.ir"
WP_USER = "sagharnazari"
WP_PASS = "ria@1274930091"

token = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
headers = {"Authorization": f"Basic {token}"}

payload = {
    "title": "تست اتصال ایجنت محتوا — این را حذف کنید",
    "content": "<p>این یک پیش‌نویس آزمایشی است که توسط ایجنت ساخته شده تا اتصال بررسی شود.</p>",
    "status": "draft",
}

print("درحال ساخت پیش‌نویس آزمایشی...")
try:
    r = httpx.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        json=payload,
        headers=headers,
        timeout=30,
    )
    if r.status_code in (200, 201):
        data = r.json()
        post_id = data["id"]
        edit_url = f"{WP_URL}/wp-admin/post.php?post={post_id}&action=edit"
        print("✅ پیش‌نویس ساخته شد!")
        print(f"   شناسه پست: {post_id}")
        print(f"   لینک ویرایش: {edit_url}")
    else:
        print(f"❌ خطا: {r.status_code}")
        print(f"   پاسخ: {r.text[:300]}")
except Exception as e:
    print(f"❌ خطا: {e}")
