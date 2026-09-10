"""SQLite: صف مقالات، تاریخچه و جلوگیری از پردازش تکراری.

وضعیت‌های جدول articles:
    pending   -> منتظر تأیید کاربر
    approved  -> تأییدشده، آماده‌ی انتشار ساعت ۱۲
    rejected  -> ردشده
    published -> منتشرشده در وردپرس
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .config import DATA_DIR

# از دیتابیس اصلی پروژه استفاده کن (جایی که SEO-agent مقالات ذخیره می‌کند)
DB_PATH = DATA_DIR.parent / "agent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    title_seo TEXT,
    payload TEXT NOT NULL,        -- JSON کامل مقاله‌ی تولیدی (متن، متا، تصاویر)
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    published_at TEXT,
    wp_post_url TEXT
);
CREATE TABLE IF NOT EXISTS token_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    model TEXT NOT NULL,
    step TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER
);
CREATE TABLE IF NOT EXISTS pipeline_validation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'rejected',
    rejection_reasons TEXT NOT NULL DEFAULT '[]',
    candidate_content_hash TEXT NOT NULL,
    restored_content_hash TEXT NOT NULL,
    validator_version TEXT NOT NULL,
    candidate_saved INTEGER NOT NULL DEFAULT 0,
    debug_candidate_text TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pve_article
    ON pipeline_validation_events(article_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pve_stage
    ON pipeline_validation_events(stage, status);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """ستون‌هایی که بعد از ساختِ اولیه‌ی جدول اضافه شده‌اند (CREATE IF NOT EXISTS آنها را نمی‌آورد)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
    if "notified_at" not in have:
        conn.execute("ALTER TABLE articles ADD COLUMN notified_at TEXT")
        conn.commit()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def is_seen(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_urls WHERE url_hash = ?", (url_hash(url),)
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, url: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_urls (url_hash, url, seen_at) VALUES (?, ?, ?)",
        (url_hash(url), url, _now()),
    )
    conn.commit()


def save_article(conn: sqlite3.Connection, topic: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO articles (topic, title_seo, payload, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (topic, payload.get("title_seo", ""), json.dumps(payload, ensure_ascii=False), _now()),
    )
    conn.commit()
    return cur.lastrowid


def update_payload(conn: sqlite3.Connection, article_id: int, payload: dict) -> None:
    """payload یک مقاله را به‌روزرسانی می‌کند (مثلاً بعد از بازنویسی توسط ارزیاب)."""
    conn.execute(
        "UPDATE articles SET payload = ?, title_seo = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), payload.get("title_seo", ""), article_id),
    )
    conn.commit()


def set_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    conn.execute(
        "UPDATE articles SET status = ?, decided_at = ? WHERE id = ?",
        (status, _now(), article_id),
    )
    conn.commit()


def mark_published(conn: sqlite3.Connection, article_id: int, post_url: str) -> None:
    conn.execute(
        "UPDATE articles SET status = 'published', published_at = ?, wp_post_url = ? WHERE id = ?",
        (_now(), post_url, article_id),
    )
    conn.commit()


def get_article(conn: sqlite3.Connection, article_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def approved_articles(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM articles WHERE status = 'approved'").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def record_validation_event(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    stage: str,
    round_number: int,
    rejection_reasons: list,
    candidate_content_hash: str,
    restored_content_hash: str,
    validator_version: str,
    debug_candidate_text: str | None = None,
    debug_mode: bool = False,
) -> None:
    """ثبت رویداد ردّ Validator (پچ v2.1). Fail-Closed در فراخواننده مدیریت می‌شود."""
    conn.execute(
        "INSERT INTO pipeline_validation_events "
        "(article_id, stage, round_number, status, rejection_reasons, "
        " candidate_content_hash, restored_content_hash, validator_version, "
        " candidate_saved, debug_candidate_text, created_at) "
        "VALUES (?, ?, ?, 'rejected', ?, ?, ?, ?, 0, ?, ?)",
        (
            article_id, stage, round_number,
            json.dumps(list(rejection_reasons), ensure_ascii=False),
            candidate_content_hash, restored_content_hash, validator_version,
            debug_candidate_text if debug_mode else None,
            _now(),
        ),
    )
    conn.commit()


def log_tokens(conn: sqlite3.Connection, model: str, step: str, usage) -> None:
    conn.execute(
        "INSERT INTO token_log (at, model, step, input_tokens, output_tokens, cache_read_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            _now(),
            model,
            step,
            getattr(usage, "input_tokens", 0),
            getattr(usage, "output_tokens", 0),
            getattr(usage, "cache_read_input_tokens", 0) or 0,
        ),
    )
    conn.commit()


def today_token_summary(conn: sqlite3.Connection) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        "SELECT model, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read_tokens) c "
        "FROM token_log WHERE at LIKE ? GROUP BY model",
        (f"{today}%",),
    ).fetchall()
    lines = [f"{r['model']}: in={r['i']} out={r['o']} cached={r['c']}" for r in rows]
    return "\n".join(lines) if lines else "بدون مصرف توکن"


def mark_notified(conn: sqlite3.Connection, article_id: int) -> None:
    """ثبت می‌کند که مقاله برای تایید به تلگرام رفته است.

    بدون این علامت، هر اجرای روزانه‌ی ارزیابی همه‌ی مقاله‌های pending را دوباره
    ارزیابی و دوباره ارسال می‌کرد — مقاله‌ی #۵۷ سه روز پیاپی فرستاده شد و هزینه‌ی
    LLMاش هم سه بار پرداخت شد. عمداً فقط پس از ارسالِ *موفق* ست می‌شود تا اگر
    تلگرام در دسترس نبود، دفعه‌ی بعد دوباره تلاش شود.
    """
    conn.execute("UPDATE articles SET notified_at = datetime('now') WHERE id = ?",
                 (article_id,))
    conn.commit()


def pending_articles(conn: sqlite3.Connection) -> list[dict]:
    """تمام مقالات pending را برمی‌گرداند."""
    rows = conn.execute("SELECT * FROM articles WHERE status = 'pending' ORDER BY created_at DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def rejected_articles(conn: sqlite3.Connection) -> list[dict]:
    """تمام مقالات rejected را برمی‌گرداند."""
    rows = conn.execute("SELECT * FROM articles WHERE status = 'rejected' ORDER BY created_at DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out
