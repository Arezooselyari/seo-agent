"""دیتابیسِ باتِ تلگرام — پروفایلِ مشتری، سهمیه و مقاله‌ها.

هر مشتری با `chat_id` شناخته می‌شود؛ همین کلید جای «باتِ اختصاصی» را می‌گیرد:
هر کس فقط پروفایل و مقاله‌های خودش را می‌بیند.

وضعیت روی دیسک است نه حافظه — ری‌دیپلویِ Railway نباید سهمیه‌ها را صفر کند یا
مقاله‌های تحویل‌شده را پاک کند. مسیر با `BOT_DB` قابلِ تنظیم است (روی Railway
باید به والیومِ ماندگار اشاره کند، مثلاً `/data/bot.db`).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BOT_DB", str(ROOT / "data" / "bot.db")))

TRIAL_QUOTA = int(os.environ.get("BOT_TRIAL_QUOTA", "1"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    chat_id       INTEGER PRIMARY KEY,
    name          TEXT,
    username      TEXT,
    niche         TEXT,
    keywords      TEXT,                       -- JSON: موضوع‌های ثابتِ مشتری
    ctype         TEXT    DEFAULT 'tutorial',
    daily_enabled INTEGER DEFAULT 0,
    daily_hour    INTEGER DEFAULT 9,
    plan          TEXT    DEFAULT 'trial',
    quota_total   INTEGER NOT NULL,
    quota_used    INTEGER NOT NULL DEFAULT 0,
    period_end    TEXT,
    created_at    TEXT    NOT NULL,
    state         TEXT,                       -- مرحله‌ی ویزارد
    state_data    TEXT                        -- JSON: داده‌ی موقتِ ویزارد
);
CREATE TABLE IF NOT EXISTS articles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    created_at TEXT    NOT NULL,
    niche      TEXT,
    ctype      TEXT,
    keyword    TEXT,
    title      TEXT,
    html       TEXT,
    seo_score  REAL,
    status     TEXT    NOT NULL DEFAULT 'queued',   -- queued|running|done|error
    error      TEXT,
    source     TEXT    DEFAULT 'manual',            -- manual|daily
    msg_id     INTEGER                              -- پیامِ «در حال تولید» برای ویرایشِ زنده
);
CREATE INDEX IF NOT EXISTS idx_articles_chat ON articles(chat_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
"""


# ستون‌هایی که بعداً اضافه شده‌اند — `CREATE TABLE IF NOT EXISTS` آن‌ها را به
# جدولِ از قبل موجود اضافه نمی‌کند، پس دستی مهاجرت می‌دهیم.
_MIGRATIONS = {
    # tokens_* برای گزارشِ مصرفِ هر مشتری در داشبوردِ مدیریتی. NULL یعنی
    # مقاله‌ای که پیش از افزودنِ این ستون‌ها ساخته شده — نه «صفر مصرف».
    "articles": {"msg_id": "INTEGER", "tokens_in": "INTEGER", "tokens_out": "INTEGER"},
    # آخرین یادآوریِ انقضایی که فرستاده شده، به‌شکلِ «<period_end>:<روزِ مانده>».
    # چون کلید شاملِ تاریخِ پایان است، تمدیدِ اشتراک خودبه‌خود اجازه‌ی یادآوریِ
    # دوره‌ی بعد را می‌دهد بدونِ اینکه لازم باشد چیزی پاک شود.
    "clients": {"expiry_notice": "TEXT"},
}


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    for table, cols in _MIGRATIONS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                logger.info(f"ستونِ {table}.{name} اضافه شد.")
    return c


# ── مشتری ───────────────────────────────────────────────────────────────────
def get_or_create_client(chat_id: int, name: str = "", username: str = "") -> sqlite3.Row:
    with conn() as c:
        c.execute(
            "INSERT INTO clients(chat_id, name, username, quota_total, created_at) "
            "VALUES(?,?,?,?,datetime('now')) ON CONFLICT(chat_id) DO NOTHING",
            (chat_id, name, username, TRIAL_QUOTA))
        # نام ممکن است در تلگرام عوض شده باشد
        if name:
            c.execute("UPDATE clients SET name=?, username=? WHERE chat_id=?",
                      (name, username, chat_id))
        return c.execute("SELECT * FROM clients WHERE chat_id=?", (chat_id,)).fetchone()


def get_client(chat_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM clients WHERE chat_id=?", (chat_id,)).fetchone()


def update_client(chat_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {"name", "username", "niche", "keywords", "ctype", "daily_enabled",
               "daily_hour", "plan", "quota_total", "quota_used", "period_end",
               "state", "state_data"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"فیلدِ ناشناخته: {bad}")
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE clients SET {sets} WHERE chat_id=?",
                  (*fields.values(), chat_id))


def set_state(chat_id: int, state: str | None, data: dict | None = None) -> None:
    update_client(chat_id, state=state or "",
                  state_data=json.dumps(data or {}, ensure_ascii=False))


def get_state(chat_id: int) -> tuple[str, dict]:
    row = get_client(chat_id)
    if not row:
        return "", {}
    try:
        data = json.loads(row["state_data"] or "{}")
    except json.JSONDecodeError:
        data = {}
    return row["state"] or "", data


# ── سهمیه ───────────────────────────────────────────────────────────────────
def consume_quota(chat_id: int) -> bool:
    """یک واحد از سهمیه برمی‌دارد. False یعنی سهمیه تمام است.

    شرط داخلِ خودِ UPDATE است تا دو درخواستِ هم‌زمان نتوانند از یک سهمیه رد شوند
    (چکِ جدا از نوشتن، مسابقه‌ی زمانی می‌سازد و مستقیم به هزینه‌ی LLM می‌خورد).
    اشتراکِ منقضی‌شده هم همین‌جا رد می‌شود.
    """
    try:
        with conn() as c:
            cur = c.execute(
                "UPDATE clients SET quota_used = quota_used + 1 "
                "WHERE chat_id=? AND quota_used < quota_total "
                "  AND (period_end IS NULL OR period_end = '' OR period_end >= date('now'))",
                (chat_id,))
            return cur.rowcount == 1
    except Exception as e:  # noqa: BLE001
        logger.error(f"برداشتِ سهمیه نشد ({e}) — محتاطانه رد می‌کنیم.")
        return False          # fail-closed: در تردید، تولیدِ رایگان نده


def refund_quota(chat_id: int) -> None:
    """اگر تولید شکست خورد سهمیه برگردد — مشتری نباید بابتِ خطای ما هزینه بدهد."""
    try:
        with conn() as c:
            c.execute("UPDATE clients SET quota_used = MAX(0, quota_used - 1) "
                      "WHERE chat_id=?", (chat_id,))
    except Exception as e:  # noqa: BLE001
        logger.error(f"بازگرداندنِ سهمیه نشد ({e}).")


def grant_plan(chat_id: int, days: int, quota: int, plan: str = "monthly") -> None:
    """فعال‌سازیِ دستیِ اشتراک توسطِ مالک. شمارنده‌ی مصرف صفر می‌شود.

    قالبِ `{:+d}` عمدی است: با `f"+{days}"` یک عددِ منفی «+-1 days» می‌سازد که
    SQLite آن را NULL برمی‌گرداند و NULL یعنی «بدونِ انقضا» — یعنی یک اشتباهِ
    تایپی به‌جای رد کردن، اشتراکِ دائمی می‌داد.
    """
    days, quota = int(days), int(quota)
    if days < 1 or quota < 1:
        raise ValueError("روز و تعدادِ مقاله باید دستِ‌کم ۱ باشند.")
    with conn() as c:
        c.execute(
            "UPDATE clients SET plan=?, quota_total=?, quota_used=0, "
            "period_end=date('now', ?) WHERE chat_id=?",
            (plan, quota, f"{days:+d} days", chat_id))


def set_period_end(chat_id: int, days_from_today: int) -> str:
    """تاریخِ پایان را جابه‌جا می‌کند بدونِ دست‌زدن به سهمیه. تاریخِ تازه را برمی‌گرداند.

    `{:+d}` عمدی است — `f"+{days}"` با عددِ منفی «+-1 days» می‌سازد که SQLite
    آن را NULL می‌کند و NULL یعنی «بدونِ انقضا».
    """
    with conn() as c:
        c.execute("UPDATE clients SET period_end=date('now', ?) WHERE chat_id=?",
                  (f"{int(days_from_today):+d} days", chat_id))
        row = c.execute("SELECT period_end FROM clients WHERE chat_id=?",
                        (chat_id,)).fetchone()
    return row["period_end"] if row else ""


def due_expiry_notice(days_before: int) -> list[sqlite3.Row]:
    """مشترکانی که دقیقاً `days_before` روز تا پایانِ اشتراکشان مانده و هنوز
    برای همین نقطه یادآوری نگرفته‌اند.

    `days_before=0` یعنی امروز روزِ آخر است.
    """
    key = f"|{days_before}"
    with conn() as c:
        return c.execute(
            "SELECT * FROM clients "
            "WHERE plan <> 'trial' AND period_end IS NOT NULL AND period_end <> '' "
            "  AND julianday(period_end) - julianday(date('now')) = ? "
            "  AND (expiry_notice IS NULL OR expiry_notice <> period_end || ?)",
            (days_before, key)).fetchall()


def mark_expiry_notified(chat_id: int, period_end: str, days_before: int) -> None:
    with conn() as c:
        c.execute("UPDATE clients SET expiry_notice=? WHERE chat_id=?",
                  (f"{period_end}|{days_before}", chat_id))


def list_clients(limit: int = 100) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM clients ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()


def client_token_usage() -> dict[int, tuple[int, int, int]]:
    """{chat_id: (مقاله‌ی تمام‌شده، توکن ورودی، توکن خروجی)} — برای داشبورد.

    فقط مقاله‌های `done` شمرده می‌شوند؛ کارِ شکست‌خورده سهمیه‌اش برگشته و
    مصرفش هم نباید به پای مشتری نوشته شود.
    """
    with conn() as c:
        rows = c.execute(
            "SELECT chat_id, COUNT(*) n, "
            "       COALESCE(SUM(tokens_in), 0) ti, COALESCE(SUM(tokens_out), 0) to_ "
            "FROM articles WHERE status='done' GROUP BY chat_id").fetchall()
    return {r["chat_id"]: (r["n"], r["ti"], r["to_"]) for r in rows}


def stats() -> dict:
    """شمارشِ کلی برای صفحه‌ی خلاصه‌ی داشبورد."""
    with conn() as c:
        row = c.execute(
            "SELECT (SELECT COUNT(*) FROM clients) clients, "
            "       (SELECT COUNT(*) FROM clients WHERE plan <> 'trial' "
            "          AND period_end IS NOT NULL AND period_end <> '' "
            "          AND period_end >= date('now')) active, "
            "       (SELECT COUNT(*) FROM clients WHERE period_end IS NOT NULL "
            "          AND period_end <> '' AND period_end < date('now')) expired, "
            "       (SELECT COUNT(*) FROM articles WHERE status='done') done, "
            "       (SELECT COUNT(*) FROM articles WHERE status='done' "
            "          AND date(created_at)=date('now')) done_today, "
            "       (SELECT COUNT(*) FROM articles WHERE status IN ('queued','running')) busy, "
            "       (SELECT COUNT(*) FROM articles WHERE status='error') errors, "
            "       (SELECT COALESCE(SUM(tokens_in), 0) FROM articles) ti, "
            "       (SELECT COALESCE(SUM(tokens_out), 0) FROM articles) to_"
        ).fetchone()
    return dict(row)


def last_article_at() -> str | None:
    with conn() as c:
        row = c.execute("SELECT MAX(created_at) t FROM articles "
                        "WHERE status='done'").fetchone()
    return row["t"] if row else None


def recent_errors(limit: int = 5) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT id, chat_id, created_at, keyword, error FROM articles "
            "WHERE status='error' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def list_clients_by_urgency(limit: int = 300) -> list[sqlite3.Row]:
    """برای داشبورد: نزدیک‌ترین‌به‌انقضا اول، بدونِ‌تاریخ (آزمایشی) آخر.

    مدیر هر روز باید اول کسانی را ببیند که در آستانه‌ی از‌دست‌رفتن‌اند، نه
    جدیدترین ثبت‌نام‌ها — created_at برای این کار مرتب‌سازیِ اشتباهی است.
    """
    with conn() as c:
        return c.execute(
            "SELECT * FROM clients ORDER BY "
            "  CASE WHEN period_end IS NULL OR period_end = '' THEN 1 ELSE 0 END, "
            "  period_end ASC LIMIT ?", (limit,)).fetchall()


# ── مقاله ───────────────────────────────────────────────────────────────────
def create_job(chat_id: int, niche: str, ctype: str, keyword: str,
               source: str = "manual") -> int:
    """کار را **قبل** از شروعِ تولید ثبت می‌کند تا ری‌استارت آن را گم نکند."""
    with conn() as c:
        cur = c.execute(
            "INSERT INTO articles(chat_id, created_at, niche, ctype, keyword, "
            "status, source) VALUES(?,datetime('now'),?,?,?,'queued',?)",
            (chat_id, niche, ctype, keyword, source))
        return cur.lastrowid


def set_msg_id(article_id: int, msg_id: int) -> None:
    """شناسه‌ی پیامِ «در حال تولید» تا کارگر بتواند همان را ویرایش کند."""
    with conn() as c:
        c.execute("UPDATE articles SET msg_id=? WHERE id=?", (msg_id, article_id))


def mark_running(article_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE articles SET status='running' WHERE id=?", (article_id,))


def finish_job(article_id: int, title: str, html: str, score: float,
               tokens_in: int = 0, tokens_out: int = 0) -> None:
    with conn() as c:
        c.execute("UPDATE articles SET status='done', title=?, html=?, seo_score=?, "
                  "tokens_in=?, tokens_out=? WHERE id=?",
                  (title, html, score, tokens_in, tokens_out, article_id))


def fail_job(article_id: int, error: str) -> None:
    with conn() as c:
        c.execute("UPDATE articles SET status='error', error=? WHERE id=?",
                  (error[:500], article_id))


def get_article(article_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()


def list_articles(chat_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT id, created_at, title, seo_score, status FROM articles "
            "WHERE chat_id=? AND status='done' ORDER BY id DESC LIMIT ?",
            (chat_id, limit)).fetchall()


def pending_jobs() -> list[sqlite3.Row]:
    """کارهای ناتمام — هنگامِ بالا آمدن دوباره به صف می‌روند.

    `running` هم برمی‌گردد چون یعنی پروسه وسطِ کار مُرده است.
    """
    with conn() as c:
        return c.execute(
            "SELECT * FROM articles WHERE status IN ('queued','running') ORDER BY id"
        ).fetchall()


def due_daily(hour: int) -> list[sqlite3.Row]:
    """مشتریانی که ارسالِ روزانه‌شان برای این ساعت فعال است و امروز چیزی نگرفته‌اند."""
    with conn() as c:
        return c.execute(
            "SELECT * FROM clients WHERE daily_enabled=1 AND daily_hour=? "
            "  AND quota_used < quota_total "
            "  AND (period_end IS NULL OR period_end = '' OR period_end >= date('now')) "
            "  AND chat_id NOT IN ("
            "     SELECT chat_id FROM articles "
            "     WHERE source='daily' AND date(created_at) = date('now'))",
            (hour,)).fetchall()
