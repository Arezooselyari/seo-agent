"""تست اتصال Supabase."""
from src.config import Secrets

s = Secrets()

if not s.supabase_url or not s.supabase_key:
    print("❌ SUPABASE_URL یا SUPABASE_KEY تنظیم نشده")
else:
    print("✅ کلیدها موجود هستند")
    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_key)
        print("✅ Client ساخته شد")

        # جدول‌های موجود
        result = (
            client.from_("information_schema.tables")
            .select("table_name")
            .eq("table_schema", "public")
            .execute()
        )
        tables = sorted([r["table_name"] for r in result.data])
        print(f"✅ {len(tables)} جدول پیدا شد:")
        for t in tables:
            print(f"   - {t}")

        # بررسی specific tables
        expected = {"sources", "topics", "research_briefs", "articles", "publishing", "settings"}
        found = set(tables)
        if expected <= found:
            print(f"\n✅ تمام جدول‌های مورد نیاز موجود هستند!")
        else:
            missing = expected - found
            print(f"\n❌ جدول‌های گمشده: {missing}")

    except Exception as e:  # noqa: BLE001
        print(f"❌ خطا: {type(e).__name__}")
        print(f"   {str(e)[:200]}")
