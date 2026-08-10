#!/usr/bin/env python3
"""تست سیستم ارزیابی مقالات.

این اسکریپت برای تست کردن ارزیابی کننده استفاده می‌شود:
1. مقالات pending را نمایش می‌دهد
2. ارزیابی آن‌ها را نشان می‌دهد
3. نتایج را درخواست می‌کند
"""

import json
from src import db, evaluator

# Connect to database
conn = db.connect()

print("=" * 60)
print("تست سیستم ارزیابی مقالات")
print("=" * 60)

# Get pending articles
pending = db.pending_articles(conn)

if not pending:
    print("\n❌ هیچ مقاله‌ی pending وجود ندارد.")
    conn.close()
    exit(0)

print(f"\n📊 تعداد مقالات pending: {len(pending)}")
print("-" * 60)

# Evaluate each article
approved_count = 0
needs_review_count = 0

for article in pending:
    result = evaluator.evaluate_article(article, threshold=90)

    print(f"\n🆔 مقاله #{result['article_id']}")
    print(f"   📌 عنوان: {result['title']}")
    print(f"   ⭐ امتیاز SEO: {result['seo_grade']}/100")
    print(f"   🎯 توصیه: {result['recommendation']}")
    print(f"   📝 پیش‌نمایش: {result['preview'][:100]}...")

    if result["recommendation"] == "approve":
        approved_count += 1
        print(f"   ✅ آماده برای ارسال به تلگرام")
    else:
        needs_review_count += 1
        print(f"   ⚠️ نیاز به بررسی بیشتر")

print("\n" + "=" * 60)
print(f"📊 نتایج ارزیابی:")
print(f"   ✅ تایید شده (score >= 90): {approved_count}")
print(f"   ⚠️ نیاز به بررسی (score < 90): {needs_review_count}")
print("=" * 60)

conn.close()
