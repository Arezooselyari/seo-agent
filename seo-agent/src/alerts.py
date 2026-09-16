"""هشدارِ خطا و موجودی به تلگرام — یک پیامِ خلاصه در پایانِ هر اجرا.

چرا این ماژول لازم شد: بینِ ۱۳ تا ۱۵ سپتامبر ۲۰۲۶ اعتبارِ OpenRouter ته کشید و
سه روزِ پیاپی هیچ مقاله‌ای تولید نشد. خطاها در logs/generate.log بودند ولی کسی
لاگ را نمی‌خواند؛ از بیرون فقط «امروز مقاله نیامد» دیده می‌شد. حالا هر اجرا خودش
خبر می‌دهد.

طراحی عمداً «یک پیام در پایانِ اجرا» است، نه یک پیام به‌ازای هر خطا: در ۱۴ سپتامبر
همان خطای ۴۰۲ چهار بار پشت‌سرهم لاگ شد؛ چهار پیامِ یکسان در تلگرام فقط اعصاب‌خردکن
است. پس خطاها جمع، یکتا و خلاصه می‌شوند.

استفاده:
    with alerts.watch("تولید روزانه"):
        ...

هر WARNING/ERRORِ ثبت‌شده در طولِ بلوک جمع می‌شود؛ اگر چیزی بود (یا استثنایی
بالا آمد) در پایان یک پیام به تلگرام می‌رود.
"""
import html
import logging
import re
import traceback
from contextlib import contextmanager

import httpx

from .config import env

logger = logging.getLogger(__name__)

# زیرِ این مقدار (دلار) هشدارِ شارژ فرستاده می‌شود
LOW_CREDIT_USD = 3.0

# پیام‌های طولانیِ ارائه‌دهنده (JSONِ چندخطی) در تلگرام خوانا نیستند
_MAX_LINE = 220
_MAX_ITEMS = 8


def send(text: str) -> bool:
    """یک پیامِ متنی به چتِ ادمین می‌فرستد. True یعنی رفت."""
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        logger.warning("alerts: توکن یا chat_id تلگرام تنظیم نشده — هشدار ارسال نشد.")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000],
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=25,
        )
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001 — نرسیدنِ هشدار نباید خودش خطا بسازد
        logger.warning(f"alerts: ارسالِ هشدار نشد ({e}).")
        return False


def credit_balance() -> float | None:
    """موجودیِ باقیمانده‌ی OpenRouter به دلار، یا None اگر خوانده نشد."""
    key = (env("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return None
    try:
        r = httpx.get("https://openrouter.ai/api/v1/credits",
                      headers={"Authorization": f"Bearer {key}"}, timeout=20)
        d = r.json()["data"]
        return float(d["total_credits"]) - float(d["total_usage"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"alerts: موجودی خوانده نشد ({e}).")
        return None


def check_credit(threshold: float = LOW_CREDIT_USD) -> float | None:
    """اگر موجودی کم بود هشدار می‌دهد. موجودی را برمی‌گرداند."""
    bal = credit_balance()
    if bal is not None and bal < threshold:
        send(f"⚠️ <b>اعتبار OpenRouter رو به اتمام است</b>\n\n"
             f"باقیمانده: <b>{bal:.2f} دلار</b>\n\n"
             f"با نرخِ مصرفِ فعلی چند روز بیشتر دوام ندارد. وقتی صفر شود، "
             f"موضوع انتخاب می‌شود ولی مقاله ساخته نمی‌شود.\n"
             f"شارژ: https://openrouter.ai/settings/credits")
    return bal


def _tidy(msg: str) -> str:
    """پیامِ خطا را به یک خطِ خوانا خلاصه می‌کند.

    خطاهای ارائه‌دهنده یک JSONِ بلند با URL و metadata برمی‌گردانند؛ همان جمله‌ی
    اولش برای فهمیدنِ ماجرا کافی است.
    """
    msg = re.sub(r"\s+", " ", msg).strip()
    m = re.search(r"'message':\s*'([^']{10,})'", msg)
    if m:
        msg = m.group(1)
    return msg[:_MAX_LINE] + ("…" if len(msg) > _MAX_LINE else "")


class _Collector(logging.Handler):
    """WARNING و بالاتر را در طولِ یک اجرا جمع می‌کند (یکتا، با شمارنده)."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.items: dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            key = _tidy(record.getMessage())
        except Exception:  # noqa: BLE001 — هندلرِ لاگ هرگز نباید بترکد
            return
        if key:
            self.items[key] = self.items.get(key, 0) + 1


@contextmanager
def watch(run_name: str, *, check_credits: bool = True):
    """خطاهای یک اجرا را جمع می‌کند و در پایان یک هشدارِ خلاصه می‌فرستد.

    استثنای بالاآمده دوباره raise می‌شود (رفتارِ خروجیِ اسکریپت عوض نمی‌شود)، فقط
    قبلش گزارش می‌رود.
    """
    collector = _Collector()
    root = logging.getLogger()
    root.addHandler(collector)
    crashed: BaseException | None = None
    try:
        yield collector
    except BaseException as e:   # noqa: BLE001 — گزارش بده، بعد بگذار بالا برود
        crashed = e
        raise
    finally:
        root.removeHandler(collector)
        try:
            _report(run_name, collector, crashed, check_credits)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"alerts: ساختِ گزارش نشد ({e}).")


def _report(run_name: str, collector: _Collector,
            crashed: BaseException | None, check_credits: bool) -> None:
    if not collector.items and crashed is None:
        if check_credits:
            check_credit()          # همه‌چیز خوب بود؛ فقط موجودی را بپا
        return

    head = (f"❌ <b>{html.escape(run_name)} با خطا متوقف شد</b>" if crashed
            else f"⚠️ <b>{html.escape(run_name)} — هشدار</b>")
    lines = [head, ""]

    if crashed is not None:
        tb = traceback.format_exception_only(type(crashed), crashed)[-1].strip()
        lines += [f"<code>{html.escape(_tidy(tb))}</code>", ""]

    if collector.items:
        ranked = sorted(collector.items.items(), key=lambda kv: -kv[1])
        lines.append(f"<b>{len(collector.items)} هشدار</b> در این اجرا:")
        for msg, n in ranked[:_MAX_ITEMS]:
            times = f" (×{n})" if n > 1 else ""
            lines.append(f"• {html.escape(msg)}{times}")
        if len(ranked) > _MAX_ITEMS:
            lines.append(f"… و {len(ranked) - _MAX_ITEMS} مورد دیگر")

    bal = credit_balance() if check_credits else None
    if bal is not None:
        warn = " ⚠️ کم است" if bal < LOW_CREDIT_USD else ""
        lines += ["", f"موجودی OpenRouter: <b>{bal:.2f} دلار</b>{warn}"]

    send("\n".join(lines))
