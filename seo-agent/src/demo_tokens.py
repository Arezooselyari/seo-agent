"""ساختِ لینک‌های یک‌بارمصرفِ دمو (برای ارسال در دایرکت اینستاگرام).

هر لینک یک توکنِ یکتا دارد و با اولین تولیدِ مقاله می‌سوزد.

    python -m src.demo_tokens --count 5 --label "کلاینت اینستاگرام"
    python -m src.demo_tokens --list
"""
from __future__ import annotations

import argparse
import os
import secrets

from .client_demo import tokens_conn

# آدرسِ عمومیِ سرویس — روی Railway با متغیرِ DEMO_BASE_URL ست می‌شود
BASE_URL = os.environ.get("DEMO_BASE_URL", "http://localhost:8078").rstrip("/")


def mint(count: int = 1, label: str = "") -> list[str]:
    """`count` توکنِ تازه می‌سازد و لینک‌های کاملشان را برمی‌گرداند."""
    tokens = []
    with tokens_conn() as conn:
        for _ in range(count):
            # ۱۶ کاراکترِ url-safe ≈ ۹۶ بیت آنتروپی — حدس‌زدنش عملاً ناممکن است
            tok = secrets.token_urlsafe(12)
            conn.execute(
                "INSERT INTO demo_tokens(token, label, created_at) "
                "VALUES(?,?,datetime('now'))", (tok, label))
            tokens.append(tok)
    return [f"{BASE_URL}/?t={t}" for t in tokens]


def listing() -> list[tuple]:
    with tokens_conn() as conn:
        return conn.execute(
            "SELECT token, label, created_at, used_at, title FROM demo_tokens "
            "ORDER BY created_at DESC").fetchall()


def main() -> None:
    ap = argparse.ArgumentParser(description="ساختِ لینکِ یک‌بارمصرفِ دمو")
    ap.add_argument("--count", type=int, default=1, help="چند لینک ساخته شود")
    ap.add_argument("--label", default="", help="یادداشت (مثلاً نامِ کلاینت)")
    ap.add_argument("--list", action="store_true", help="فقط لینک‌های موجود را نشان بده")
    args = ap.parse_args()

    if args.list:
        rows = listing()
        if not rows:
            print("هنوز هیچ لینکی ساخته نشده است.")
            return
        print(f"{'وضعیت':<10} {'برچسب':<22} لینک / مقاله")
        print("─" * 78)
        for tok, label, _created, used_at, title in rows:
            state = "✗ سوخته" if used_at else "✓ آماده"
            extra = (title or "")[:46] if used_at else f"{BASE_URL}/?t={tok}"
            print(f"{state:<10} {(label or '—')[:22]:<22} {extra}")
        return

    for url in mint(args.count, args.label):
        print(url)


if __name__ == "__main__":
    main()
