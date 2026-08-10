"""فراخوانی structured مشترک LLM برای هر سه provider.

هر سه مرحله‌ی LLM پایپ‌لاین (Topic Selector، Research Brief، Writer) از همین
یک تابع استفاده می‌کنند: prompt + JSON schema می‌گیرد، dict معتبر می‌دهد.
provider و model از config.yaml می‌آیند — بدون لمس کد.
"""
from __future__ import annotations

import json
import re
import time

from .config import Secrets, TenantConfig


def _is_retryable_network_error(exc: Exception) -> bool:
    """آیا این خطا از قطعیِ موقتِ شبکه/VPN است (ارزش تلاش مجدد دارد)؟"""
    s = str(exc).lower()
    markers = [
        "403", "permissiondenied", "http2 header",
        "503", "unavailable", "deadline", "timeout", "timed out",
        "connection", "reset", "temporarily", "max retries",
        "getaddrinfo", "ssl", "unreachable", "aborted",
    ]
    return any(m in s for m in markers)


def _is_quota_error(exc: Exception) -> bool:
    """آیا خطا از پُرشدنِ سهمیه‌ی نرخِ Gemini است (429)؟"""
    s = str(exc).lower()
    markers = [
        "429", "resource_exhausted", "resourceexhausted",
        "quota", "rate limit", "exceeded your current quota",
    ]
    return any(m in s for m in markers)


def _is_daily_quota_error(exc: Exception) -> bool:
    """آیا این سهمیه‌ی *روزانه* است (نه دقیقه‌ای)؟

    سهمیه‌ی روزانه تا نیمه‌شبِ UTC آزاد نمی‌شود — صبر/retry امروز بی‌فایده است،
    پس باید بلافاصله raise شود تا هزاران ثانیه بیهوده هدر نرود.
    """
    s = str(exc).lower().replace(" ", "")
    return "perday" in s or "requestsperday" in s


def call_with_retry(fn, *, retries: int = 6, base_delay: int = 5):
    """fn را اجرا می‌کند؛ روی خطای موقت چند بار با backoff تلاش می‌کند.

    دو نوع خطای موقت را تحمل می‌کند:
    - قطعیِ شبکه/VPN (403/timeout/…): backoff کوتاه ۵، ۱۰، ۱۵ ثانیه.
    - پُرشدنِ سهمیه‌ی دقیقه‌ای Gemini (429): صبرِ بلندِ ۳۵ ثانیه تا دقیقه‌ی بعد
      که سهمیه آزاد می‌شود.
    خطای دائمی (مثلاً JSON خراب، کلید غلط) بلافاصله raise می‌شود.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            # سهمیه‌ی روزانه تا فردا آزاد نمی‌شود — صبر بی‌فایده، فوراً raise
            if _is_daily_quota_error(e):
                raise
            is_quota = _is_quota_error(e)
            is_net = _is_retryable_network_error(e)
            if not (is_quota or is_net) or attempt == retries - 1:
                raise
            if is_quota:
                delay = 35  # سهمیه‌ی tier رایگان هر دقیقه ریست می‌شود
                reason = "سقفِ سهمیه‌ی Gemini پر شد"
            else:
                delay = base_delay * (attempt + 1)
                reason = "قطعیِ شبکه/VPN"
            print(
                f"[retry] تلاش {attempt + 1}/{retries} ناموفق ({reason}). "
                f"{delay} ثانیه صبر و دوباره..."
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc

DEFAULT_MODELS = {
    "openrouter": "google/gemini-2.0-flash-001",
    "gemini": "gemini-2.0-flash",
    "claude": "claude-sonnet-4-6",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_JSON_INSTRUCTION = (
    "\n\nخروجی را دقیقاً به صورت یک JSON object معتبر مطابق این schema برگردان. "
    "هیچ متن اضافه‌ای قبل یا بعد از JSON ننویس. فقط JSON خالص.\n"
    "Schema:\n{schema}"
)


def _strip_code_fence(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text)


def _call_openrouter(prompt: str, schema: dict, model: str, api_key: str,
                     max_tokens: int) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
    full_prompt = prompt + _JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))
    response = call_with_retry(lambda: client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": full_prompt}],
        max_tokens=max_tokens,
        temperature=0.4,
    ))
    return json.loads(_strip_code_fence(response.choices[0].message.content))


def _call_gemini(prompt: str, schema: dict, model: str, api_key: str,
                 max_tokens: int) -> dict:
    import google.generativeai as genai  # type: ignore[import]
    from google.generativeai.types import GenerationConfig  # type: ignore[import]

    genai.configure(api_key=api_key)
    full_prompt = prompt + _JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))

    gemini = genai.GenerativeModel(
        model,
        generation_config=GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=0.4,
        ),
    )
    response = call_with_retry(lambda: gemini.generate_content(full_prompt))

    # Extract JSON from response
    text = _strip_code_fence(response.text)
    return _parse_json_lenient(text)


def _parse_json_lenient(text: str) -> dict:
    """JSON خروجی مدل را مقاوم پارس می‌کند.

    مدل‌ها گاهی داخل رشته‌ها newline خام می‌گذارند (JSON نامعتبر) یا خروجی
    در سقف توکن نصفه قطع می‌شود. این تابع چند لایه‌ی ترمیم دارد.
    """
    # ۱) خام، با اجازه‌ی کاراکترهای کنترلی داخل رشته‌ها
    candidate = text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        candidate = json_match.group()
    for attempt in (candidate, text):
        try:
            return json.loads(attempt, strict=False)
        except json.JSONDecodeError:
            continue

    # ۲) ترمیم: newlineهای خام داخل رشته‌ها را escape کن
    repaired = _escape_unescaped_newlines(candidate)
    try:
        return json.loads(repaired, strict=False)
    except json.JSONDecodeError:
        pass

    # ۳) خروجی نصفه‌قطع‌شده: تا آخرین رشته‌ی کامل ببند
    closed = _close_truncated_json(repaired)
    return json.loads(closed, strict=False)


def _escape_unescaped_newlines(text: str) -> str:
    """newlineها/tabهای خام داخل رشته‌های JSON را \\n/\\t می‌کند."""
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch == "\n":
            out.append("\\n")
        elif in_string and ch == "\t":
            out.append("\\t")
        elif in_string and ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


def _close_truncated_json(text: str) -> str:
    """خروجی قطع‌شده را به نزدیک‌ترین JSON معتبر می‌رساند.

    رشته‌ی باز را می‌بندد، سپس براکت‌ها/آکولادهای باز را به ترتیب درست می‌بندد.
    """
    in_string = False
    escaped = False
    stack: list[str] = []
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    result = text
    if in_string:
        result += '"'
    for opener in reversed(stack):
        result += "}" if opener == "{" else "]"
    return result


def _call_claude(prompt: str, schema: dict, model: str, api_key: str,
                 max_tokens: int, tool_name: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        tools=[{
            "name": tool_name,
            "description": "خروجی ساختاریافته را در این قالب برگردان.",
            "input_schema": schema,
        }],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input


def structured_call(
    prompt: str,
    schema: dict,
    *,
    cfg: TenantConfig | None = None,
    secrets: Secrets | None = None,
    tool_name: str = "structured_output",
    max_tokens: int = 4096,
) -> dict:
    """یک فراخوانی LLM با خروجی structured مطابق schema. provider از config می‌آید."""
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    provider = cfg.ai_provider.lower()
    model = cfg.ai_model or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["gemini"])

    if provider == "openrouter":
        return _call_openrouter(prompt, schema, model, secrets.openrouter_api_key, max_tokens)
    if provider == "gemini":
        return _call_gemini(prompt, schema, model, secrets.gemini_api_key, max_tokens)
    if provider == "claude":
        return _call_claude(prompt, schema, model, secrets.anthropic_api_key, max_tokens, tool_name)
    raise ValueError(
        f"ai_provider نامعتبر: {provider!r}. مقادیر مجاز: 'openrouter'، 'gemini' یا 'claude'"
    )
