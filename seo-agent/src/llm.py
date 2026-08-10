"""کلاینت مدل (Anthropic یا Gemini) با خروجی JSON و ثبت مصرف توکن.

ارائه‌دهنده با کلید `provider` در settings.yaml تعیین می‌شود: anthropic | gemini
هر دو از تابع ask() یکسان استفاده می‌کنند.
"""
import json
import re

from .config import PROMPTS_DIR, env, load_settings
from . import db

_client = None
_gemini_ready = False
_openai_client = None
_openrouter_client = None
_settings = load_settings()


def _provider() -> str:
    return (_settings.get("provider") or "anthropic").lower()


def client():
    """کلاینت Anthropic (فقط وقتی provider=anthropic)."""
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return _client


def _gemini():
    global _gemini_ready
    import google.generativeai as genai
    if not _gemini_ready:
        genai.configure(api_key=env("GEMINI_API_KEY", required=True))
        _gemini_ready = True
    return genai


def _openai():
    """کلاینت OpenAI (فقط وقتی provider=openai). کلید: OPEN_AI_API_KEY."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=env("OPEN_AI_API_KEY", required=True))
    return _openai_client


def _openrouter():
    """کلاینت OpenRouter (دروازه‌ی چندمدلی، OpenAI-compatible). کلید: OPENROUTER_API_KEY."""
    global _openrouter_client
    if _openrouter_client is None:
        from openai import OpenAI
        _openrouter_client = OpenAI(
            api_key=env("OPENROUTER_API_KEY", required=True),
            base_url="https://openrouter.ai/api/v1",
        )
    return _openrouter_client


def system_prompt_xml() -> str:
    return (PROMPTS_DIR / "seo-content-agent-prompt.xml").read_text(encoding="utf-8")


def _escape_unescaped_newlines(s: str) -> str:
    """newlineهای خام داخل رشته‌های JSON را escape می‌کند (خطای مدل رایج)."""
    out = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _close_truncated_json(s: str) -> str:
    """JSON بریده‌شده را می‌بندد: رشته‌ی باز، سپس براکت/آکولادهای باز (به ترتیب معکوس).

    برای پاسخ‌هایی که به سقف توکن خورده‌اند یا ناقص برگشته‌اند.
    """
    in_str = False
    escaped = False
    stack = []
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    repaired = s.rstrip()
    if in_str:                       # رشته‌ی نیمه‌باز را ببند
        repaired += '"'
    repaired = repaired.rstrip().rstrip(",")   # کامای انتهاییِ معلق
    for opener in reversed(stack):   # آکولاد/براکت‌های باز را به ترتیب معکوس ببند
        repaired += "}" if opener == "{" else "]"
    return repaired


def _repair_json(candidate: str):
    """چند استراتژی repair را روی JSON خراب امتحان می‌کند. اگر همه شکست خورد raise می‌کند."""
    strategies = (
        lambda s: json.loads(s),                                      # خام
        lambda s: json.loads(_escape_unescaped_newlines(s)),          # newline خام
        lambda s: json.loads(_close_truncated_json(s)),               # بریده‌شده
        lambda s: json.loads(_close_truncated_json(_escape_unescaped_newlines(s))),  # هر دو
    )
    last_err = None
    for strat in strategies:
        try:
            return strat(candidate)
        except json.JSONDecodeError as e:
            last_err = e
    raise last_err


def _extract_json(text: str):
    """JSON را از پاسخ مدل بیرون می‌کشد (با یا بدون بلوک کد، با repair چندلایه)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError(f"پاسخ مدل JSON ندارد: {text[:200]}")
    return _repair_json(text[start:])


def ask(
    step: str,
    user_content: str,
    *,
    model_tier: str = "cheap",
    system: str | None = None,
    cache_system: bool = False,
    json_output: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0,
):
    """یک فراخوانی مدل. model_tier: 'cheap' یا 'main'. ارائه‌دهنده از settings تعیین می‌شود."""
    provider = _provider()
    if provider in ("gemini", "openai", "openrouter"):
        _fn = {"gemini": _ask_gemini, "openai": _ask_openai,
               "openrouter": _ask_openrouter}[provider]
        try:
            return _fn(
                step, user_content, model_tier=model_tier, system=system,
                json_output=json_output, max_tokens=max_tokens, temperature=temperature,
            )
        except (json.JSONDecodeError, ValueError) as e:
            # repair چندلایه شکست خورد → تولید کامل مجدد (گران، پس لاگ می‌شود).
            # با repair قوی‌تر، این مسیر باید تقریباً هیچ‌وقت فعال نشود.
            import logging
            logging.getLogger(__name__).warning(
                f"JSON مدل حتی بعد از repair خراب بود (step={step}): {str(e)[:80]} — تولید مجدد."
            )
            return _fn(
                step, user_content, model_tier=model_tier, system=system,
                json_output=json_output, max_tokens=max_tokens, temperature=temperature,
            )

    model = _settings["models"][model_tier]
    kwargs = {"model": model, "max_tokens": max_tokens}
    if system:
        if cache_system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            kwargs["system"] = system
    kwargs["messages"] = [{"role": "user", "content": user_content}]

    resp = client().messages.create(**kwargs)

    conn = db.connect()
    db.log_tokens(conn, model, step, resp.usage)
    conn.close()

    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json(text) if json_output else text


def _ask_gemini(
    step: str,
    user_content: str,
    *,
    model_tier: str = "cheap",
    system: str | None = None,
    json_output: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0,
):
    """فراخوانی Gemini با همان رابط ask()."""
    genai = _gemini()
    model_name = _settings["gemini_models"][model_tier]

    # پیش‌فرض temperature=0 → خروجی قطعی (حیاتی برای ارزیاب: نمره نباید نوسان کند).
    # نویسندگی/انسانی‌سازی temperature بالاتر می‌فرستند تا متن قالبی نشود.
    gen_config = {"max_output_tokens": max_tokens, "temperature": temperature}
    if json_output:
        gen_config["response_mime_type"] = "application/json"

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system if system else None,
        generation_config=gen_config,
    )
    resp = model.generate_content(user_content)

    # ثبت مصرف توکن (اگر usage_metadata موجود بود)
    try:
        um = resp.usage_metadata
        conn = db.connect()
        db.log_tokens(conn, model_name, step, type("U", (), {
            "input_tokens": um.prompt_token_count,
            "output_tokens": um.candidates_token_count,
            "cache_read_input_tokens": 0,
        })())
        conn.close()
    except Exception:
        pass

    # چک truncation: اگر پاسخ به سقف توکن خورده باشد، JSON ناقص است (طبق نکته‌ی مستر پرامپت)
    try:
        finish = resp.candidates[0].finish_reason
        # 2 == MAX_TOKENS در google.generativeai
        if getattr(finish, "name", str(finish)) in ("MAX_TOKENS", "2"):
            raise RuntimeError(
                f"پاسخ مدل truncate شد (MAX_TOKENS در step={step}, سقف={max_tokens}). "
                "max_tokens را بالاتر ببر."
            )
    except (IndexError, AttributeError):
        pass

    text = resp.text
    return _extract_json(text) if json_output else text


def _openai_chat(client, model_name, step, user_content, *,
                 system=None, json_output=True, max_tokens=4096, temperature=0,
                 extra_body=None):
    """هسته‌ی مشترکِ Chat Completions — برای OpenAI و OpenRouter (هر دو OpenAI-compatible)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    # حالت JSON در OpenAI نیازمندِ وجودِ واژه‌ی «json» در پیام است؛ اگر نبود، صریح اضافه کن
    if json_output and "json" not in (((system or "") + " " + user_content).lower()):
        messages[-1]["content"] += "\n\nپاسخ را فقط به‌صورتِ یک شیءِ JSON معتبر برگردان."

    # سقفِ خروجی: مدل‌های نسلِ جدید (claude-sonnet-5، gpt-5.x) تا ۶۴k خروجی می‌دهند،
    # ولی مدل‌های قدیمی‌تر (gpt-4o = 16384) کمتر. سقف را روی ۳۲۰۰۰ می‌گذاریم تا مراحلِ
    # سنگین (نگارش ۲۰۰۰۰، بازنویسی/انسانی‌سازی ۳۲۰۰۰) truncate نشوند؛ اگر مدلی این
    # مقدار را نپذیرد، منطقِ retry پایین‌تر (بلوکِ except) آن را جبران می‌کند.
    max_out = min(int(max_tokens), 32000)
    kwargs = {
        "model": model_name,
        "messages": messages,
        "max_completion_tokens": max_out,   # مدل‌های جدید max_tokens را نمی‌پذیرند
        "temperature": temperature,
    }
    if json_output:
        kwargs["response_format"] = {"type": "json_object"}
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        msg = str(e).lower()
        # سازگارسازیِ خودکار با تفاوت‌های مدل‌ها
        if "temperature" in msg:               # o-series/استدلالی فقط temperature پیش‌فرض
            kwargs.pop("temperature", None)
            resp = client.chat.completions.create(**kwargs)
        elif "max_completion_tokens" in msg or "max_tokens" in msg:
            kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
            resp = client.chat.completions.create(**kwargs)
        else:
            raise

    try:
        u = resp.usage
        conn = db.connect()
        db.log_tokens(conn, model_name, step, type("U", (), {
            "input_tokens": u.prompt_tokens,
            "output_tokens": u.completion_tokens,
            "cache_read_input_tokens": 0,
        })())
        conn.close()
    except Exception:
        pass

    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError(
            f"پاسخ مدل truncate شد (length در step={step}, سقف={max_out}). "
            "max_tokens را بالاتر ببر."
        )
    text = choice.message.content or ""
    return _extract_json(text) if json_output else text


def _ask_openai(step, user_content, *, model_tier="cheap", system=None,
                json_output=True, max_tokens=4096, temperature=0):
    """OpenAI (ChatGPT) مستقیم. کلید: OPEN_AI_API_KEY."""
    return _openai_chat(_openai(), _settings["openai_models"][model_tier], step, user_content,
                        system=system, json_output=json_output, max_tokens=max_tokens,
                        temperature=temperature)


def _ask_openrouter(step, user_content, *, model_tier="cheap", system=None,
                    json_output=True, max_tokens=4096, temperature=0):
    """OpenRouter (یک کلید، همه‌ی مدل‌ها). کلید: OPENROUTER_API_KEY. مدل‌ها: openrouter_models.

    reasoning پیش‌فرض **خاموش** است. با روشن‌بودنش، claude-sonnet-5 توکنِ استدلال را
    از همان سقفِ خروجی مصرف می‌کند: در تستِ زنده یک پاراگرافِ ۸۰ کلمه‌ای ۲۲۸۷ توکن و
    ۲۵ ثانیه گرفت، در برابر ۳۱۳ توکن و ۸ ثانیه با reasoning خاموش — و مرحله‌ی نگارشِ
    مقاله به سقفِ ۲۰۰۰۰ می‌خورد و truncate می‌شد. برای روشن‌کردن: OPENROUTER_REASONING=1
    """
    reasoning_on = (env("OPENROUTER_REASONING") or "").strip().lower() in ("1", "true", "yes")
    return _openai_chat(_openrouter(), _settings["openrouter_models"][model_tier], step, user_content,
                        system=system, json_output=json_output, max_tokens=max_tokens,
                        temperature=temperature,
                        extra_body=None if reasoning_on else {"reasoning": {"enabled": False}})
