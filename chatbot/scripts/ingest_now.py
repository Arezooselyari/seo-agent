"""اجرای دستی ایندکس‌گذاری محتوای وردپرس برای RAG.

اجرا: python -m chatbot.scripts.ingest_now
"""
from __future__ import annotations

from ..app.ingest_wp import ingest_all


def main() -> None:
    counts = ingest_all()
    print(
        f"ایندکس‌گذاری تمام شد — اسناد جدید/به‌روزشده: {counts['documents']}، "
        f"chunkها: {counts['chunks']}، رد شده (بدون تغییر): {counts['skipped']}"
    )


if __name__ == "__main__":
    main()
