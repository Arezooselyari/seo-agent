"""نقطه‌ی ورودِ مشترک — یک مخزن، دو سرویسِ Railway.

Railway فرمانِ اجرا را از `Procfile` می‌گیرد و Procfile در سطحِ مخزن است، پس
هر دو سرویس یک فرمان می‌گیرند. انتخابِ اپ با متغیرِ `APP_MODE` انجام می‌شود:

    APP_MODE=demo  (پیش‌فرض)  → دموی لینکِ یک‌بارمصرف   (src.client_demo)
    APP_MODE=bot              → باتِ تلگرام             (src.bot_app)

پیش‌فرض عمداً «demo» است تا سرویسِ زنده‌ی فعلی با نبودِ این متغیر تغییر نکند.
"""
from __future__ import annotations

import os

_MODE = (os.environ.get("APP_MODE") or "demo").strip().lower()

if _MODE == "bot":
    from .bot_app import app
else:
    from .client_demo import app

__all__ = ["app"]
