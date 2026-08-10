# بکاپ پیش از پذیرشِ subagentِ `fa-seo-writer` (۲۸ ژوئیه ۲۰۲۶)

کاربر مقاله‌ی #۴۱/#۴۲ (تولیدشده با `gemini-3.1-pro-preview` از طریقِ `src/writer.py`) را
«اصلا خوب نبود» ارزیابی کرد و تصمیم گرفت مسیرِ متفاوتی را امتحان کند: به‌جای فراخوانیِ
API (پایتون → Gemini/OpenRouter JSON)، از یک **subagentِ Claude Code** استفاده شود که
مستقیماً با مدلِ Claude (opus) و بدونِ خروجیِ JSONِ خام، فایل می‌نویسد.

## فایل‌های بکاپ‌شده
- `src/writer.py.presubagentbak` — نسخه‌ی کاملِ `writer.py` قبل از این تغییر (شاملِ
  `WRITE_PROMPT`، `_TUTORIAL_BLOCK`، `write_article`).
- `config/settings.yaml.presubagentbak` — تنظیماتِ کامل، شاملِ:
  - `provider: "gemini"`
  - `gemini_models.main: "gemini-3.1-pro-preview"`
  - `openrouter_models.main: "anthropic/claude-sonnet-5"` (شارژ ندارد — ۴۰۲)

## وضعیت در لحظه‌ی بکاپ
- خطِ لوله‌ی پایتونی (`generate_daily.py` → `writer.py` → `llm.ask`) دست‌نخورده و کامل
  کار می‌کند (تستِ end-to-end با مقاله‌ی #۴۲ موفق بود، فقط کیفیتِ لحن رضایت‌بخش نبود).
- تمامِ ماژول‌های جانبی (`references.py`, `internal_links.py`, `images.py`,
  `tool_queue.py`, `tool_discovery.py`) دست‌نخورده می‌مانند — این‌ها مستقل از نویسنده‌اند
  و در صورتِ بازگشت به مسیرِ پایتونی، بدونِ تغییر کار می‌کنند.

## بازگردانی (در صورتِ نیاز)
```bash
cp src/writer.py.presubagentbak src/writer.py
cp config/settings.yaml.presubagentbak config/settings.yaml
```

## گامِ بعد
subagentِ `fa-seo-writer` در `D:\prjcluade\.claude\agents\fa-seo-writer.md` (+ اسکریپتِ
اعتبارسنجی در `D:\prjcluade\scripts\validate_article.js` + خروجی در `D:\prjcluade\content\`)
مستقر شد. این یک **مسیرِ موازی/دستی** است (نه جایگزینِ خودکارِ زمان‌بندِ ۱۰ صبح) — تا
کیفیتش تایید نشود، خطِ لوله‌ی خودکار عوض نمی‌شود.
