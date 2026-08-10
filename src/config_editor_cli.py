"""منوی تنظیمات تعاملی — ویرایش config.yaml از طریق ترمینال."""
from __future__ import annotations
import sys
import os
import re
from pathlib import Path

# مسیر پروژه
PROJECT_DIR = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_DIR / "config.yaml"
ENV_FILE = PROJECT_DIR / ".env"

# رنگ‌ها برای ویندوز
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)
    COLORS = True
except Exception:
    COLORS = False

def c(text, code=""):
    if not COLORS or not code:
        return text
    codes = {"red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
             "cyan": "\033[96m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{codes.get(code,'')}{text}{codes['reset']}"


def read_config() -> str:
    return CONFIG_FILE.read_text(encoding="utf-8")


def write_config(content: str) -> None:
    CONFIG_FILE.write_text(content, encoding="utf-8")


def get_value(cfg: str, key: str) -> str:
    """استخراج مقدار یک کلید از YAML."""
    m = re.search(rf'^{re.escape(key)}:\s*["\']?([^"\'\n]+)["\']?', cfg, re.MULTILINE)
    return m.group(1).strip() if m else ""


def set_value(cfg: str, key: str, value: str) -> str:
    """تغییر مقدار یک کلید در YAML."""
    pattern = rf'^({re.escape(key)}:\s*).*$'
    replacement = f'{key}: "{value}"'
    new_cfg, n = re.subn(pattern, replacement, cfg, flags=re.MULTILINE)
    if n == 0:
        new_cfg = cfg.rstrip() + f'\n{key}: "{value}"\n'
    return new_cfg


def get_sources(cfg: str) -> list[dict]:
    """استخراج منابع RSS از YAML."""
    sources = []
    in_sources = False
    current = {}
    for line in cfg.splitlines():
        if line.strip().startswith("sources:"):
            in_sources = True
            continue
        if in_sources:
            if line and not line.startswith(" ") and not line.startswith("\t"):
                if ":" in line and not line.strip().startswith("-"):
                    break
            if re.match(r'\s+- name:', line):
                if current:
                    sources.append(current)
                current = {"name": re.sub(r'.*- name:\s*["\']?([^"\'\n]+)["\']?', r'\1', line).strip()}
            elif re.match(r'\s+rss:', line):
                current["rss"] = re.sub(r'.*rss:\s*["\']?([^"\'\n]+)["\']?', r'\1', line).strip()
    if current and "name" in current:
        sources.append(current)
    return sources


def rebuild_sources_yaml(cfg: str, sources: list[dict]) -> str:
    """بازسازی بخش sources در YAML."""
    lines = cfg.splitlines()
    new_lines = []
    in_sources = False
    skip = False
    for i, line in enumerate(lines):
        if line.strip().startswith("sources:"):
            in_sources = True
            new_lines.append("sources:")
            for s in sources:
                new_lines.append(f'  - name: "{s["name"]}"')
                new_lines.append(f'    rss: "{s["rss"]}"')
            skip = True
            continue
        if in_sources and skip:
            if line and not line.startswith(" ") and not line.startswith("\t") and ":" in line and not line.strip().startswith("-"):
                in_sources = False
                skip = False
                new_lines.append(line)
            continue
        new_lines.append(line)
    return "\n".join(new_lines) + "\n"


def get_keywords(cfg: str) -> list[str]:
    """استخراج کلیدواژه‌ها."""
    keywords = []
    in_kw = False
    for line in cfg.splitlines():
        if "ai_keywords:" in line:
            in_kw = True
            continue
        if in_kw:
            m = re.match(r'\s+- ["\']?(.+?)["\']?\s*$', line)
            if m:
                keywords.append(m.group(1).strip())
            elif line and not line.startswith(" "):
                break
    return keywords


def rebuild_keywords_yaml(cfg: str, keywords: list[str]) -> str:
    lines = cfg.splitlines()
    new_lines = []
    in_kw = False
    for line in lines:
        if "ai_keywords:" in line:
            in_kw = True
            new_lines.append("ai_keywords:")
            for kw in keywords:
                new_lines.append(f'  - "{kw}"')
            continue
        if in_kw:
            if line and not line.startswith(" ") and not line.startswith("\t"):
                in_kw = False
                new_lines.append(line)
            continue
        new_lines.append(line)
    return "\n".join(new_lines) + "\n"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def header(title: str):
    clear()
    print()
    print(c("  ╔══════════════════════════════════════════════════════════╗", "cyan"))
    print(c(f"  ║  {title:<54}║", "cyan"))
    print(c("  ╚══════════════════════════════════════════════════════════╝", "cyan"))
    print()


def pause():
    input(c("\n  Enter برای ادامه...", "yellow"))


# ──────────────────────────────────────────────
# منوها
# ──────────────────────────────────────────────

def menu_site_info():
    cfg = read_config()
    header("تنظیمات سایت")
    print(f"  نام سایت فعلی:    {c(get_value(cfg, 'site_name'), 'yellow')}")
    print(f"  آدرس سایت:        {c(get_value(cfg, 'site_url'), 'yellow')}")
    print(f"  آدرس دسته‌بندی:   {c(get_value(cfg, 'site_category_url'), 'yellow')}")
    print(f"  نام دسته‌بندی:    {c(get_value(cfg, 'site_category_name'), 'yellow')}")
    print()

    name = input("  نام سایت (Enter برای حفظ فعلی): ").strip()
    url = input("  آدرس سایت (مثلاً https://example.ir): ").strip()
    cat_url = input("  آدرس دسته‌بندی AI: ").strip()
    cat_name = input("  نام دسته‌بندی (مثلاً هوش مصنوعی): ").strip()

    if name: cfg = set_value(cfg, "site_name", name)
    if url: cfg = set_value(cfg, "site_url", url)
    if cat_url: cfg = set_value(cfg, "site_category_url", cat_url)
    if cat_name: cfg = set_value(cfg, "site_category_name", cat_name)

    write_config(cfg)
    print(c("\n  ✅ تنظیمات سایت ذخیره شد.", "green"))
    pause()


def menu_sources():
    while True:
        cfg = read_config()
        sources = get_sources(cfg)
        header("منابع RSS")
        if sources:
            for i, s in enumerate(sources, 1):
                print(f"  {c(str(i), 'yellow')}. {s.get('name','؟')}  —  {s.get('rss','')}")
        else:
            print(c("  (هیچ منبعی تنظیم نشده)", "red"))
        print()
        print("  [A] افزودن منبع جدید")
        print("  [D] حذف منبع")
        print("  [0] بازگشت")
        print()
        choice = input("  انتخاب: ").strip().upper()

        if choice == "0":
            break
        elif choice == "A":
            name = input("  نام منبع (مثلاً TechCrunch): ").strip()
            rss = input("  آدرس RSS (مثلاً https://techcrunch.com/feed/): ").strip()
            if name and rss:
                sources.append({"name": name, "rss": rss})
                cfg = rebuild_sources_yaml(cfg, sources)
                write_config(cfg)
                print(c(f"\n  ✅ منبع «{name}» اضافه شد.", "green"))
                pause()
        elif choice == "D":
            idx = input("  شماره منبعی که می‌خواهید حذف کنید: ").strip()
            try:
                i = int(idx) - 1
                if 0 <= i < len(sources):
                    removed = sources.pop(i)
                    cfg = rebuild_sources_yaml(cfg, sources)
                    write_config(cfg)
                    print(c(f"\n  ✅ منبع «{removed['name']}» حذف شد.", "green"))
                    pause()
            except ValueError:
                pass


def menu_keywords():
    while True:
        cfg = read_config()
        keywords = get_keywords(cfg)
        header("کلیدواژه‌های موضوعی (فیلتر اخبار)")
        print(c("  این کلمات تعیین می‌کنند چه اخباری برای تولید مقاله انتخاب شوند.", "yellow"))
        print()
        for i, kw in enumerate(keywords, 1):
            print(f"  {i}. {kw}")
        print()
        print("  [A] افزودن کلیدواژه")
        print("  [D] حذف کلیدواژه")
        print("  [R] جایگزینی همه (حوزه جدید)")
        print("  [0] بازگشت")
        print()
        choice = input("  انتخاب: ").strip().upper()

        if choice == "0":
            break
        elif choice == "A":
            kw = input("  کلیدواژه جدید (انگلیسی یا فارسی): ").strip()
            if kw and kw not in keywords:
                keywords.append(kw)
                cfg = rebuild_keywords_yaml(cfg, keywords)
                write_config(cfg)
                print(c(f"\n  ✅ کلیدواژه «{kw}» اضافه شد.", "green"))
                pause()
        elif choice == "D":
            idx = input("  شماره کلیدواژه‌ای که حذف می‌شود: ").strip()
            try:
                i = int(idx) - 1
                if 0 <= i < len(keywords):
                    removed = keywords.pop(i)
                    cfg = rebuild_keywords_yaml(cfg, keywords)
                    write_config(cfg)
                    print(c(f"\n  ✅ «{removed}» حذف شد.", "green"))
                    pause()
            except ValueError:
                pass
        elif choice == "R":
            print()
            print("  نمونه‌های حوزه:")
            niches = {
                "1": ("هوش مصنوعی (پیش‌فرض)", ["AI", "artificial intelligence", "LLM", "ChatGPT", "Gemini", "Claude", "machine learning", "automation", "agent"]),
                "2": ("سلامت و پزشکی",          ["health", "medicine", "medical", "fitness", "nutrition", "mental health", "drug", "clinical"]),
                "3": ("مالی و سرمایه‌گذاری",    ["finance", "investment", "stock", "crypto", "economy", "startup", "funding", "fintech"]),
                "4": ("کسب‌وکار و مدیریت",      ["business", "management", "marketing", "sales", "leadership", "startup", "entrepreneur"]),
                "5": ("وارد کردن دستی",          []),
            }
            for k, (label, _) in niches.items():
                print(f"  {k}. {label}")
            n = input("\n  انتخاب: ").strip()
            if n in niches:
                label, kws = niches[n]
                if n == "5":
                    raw = input("  کلیدواژه‌ها را با کاما جدا کنید: ")
                    kws = [k.strip() for k in raw.split(",") if k.strip()]
                cfg = rebuild_keywords_yaml(cfg, kws)
                write_config(cfg)
                print(c(f"\n  ✅ کلیدواژه‌های حوزه «{label}» تنظیم شدند.", "green"))
                pause()


def menu_schedule():
    cfg = read_config()
    header("تنظیمات زمانبندی")
    print(f"  تعداد مقاله در روز:   {c(get_value(cfg, 'articles_per_run'), 'yellow')}")
    print(f"  ساعت اجرای روزانه:    {c(get_value(cfg, 'run_time'), 'yellow')}")
    print()

    count = input("  تعداد مقاله در روز (Enter برای حفظ): ").strip()
    time_ = input("  ساعت اجرا (مثلاً 09:00 یا 22:00): ").strip()

    if count:
        cfg = set_value(cfg, "articles_per_run", count)
        # حذف quotes از عدد
        cfg = cfg.replace(f'articles_per_run: "{count}"', f'articles_per_run: {count}')
    if time_:
        cfg = set_value(cfg, "run_time", time_)

    write_config(cfg)

    if time_:
        hour = time_.split(":")[0].zfill(2) + ":" + time_.split(":")[-1].zfill(2)
        import subprocess
        subprocess.run(
            f'schtasks /create /tn "PersianAI-Agent" /tr "{PROJECT_DIR}\\run_agent.bat" '
            f'/sc daily /st {hour} /ri 15 /du 01:00 /rl highest /f',
            shell=True, capture_output=True
        )
        print(c(f"\n  ✅ Task Scheduler به‌روز شد: هر روز ساعت {hour}", "green"))
    print(c("  ✅ تنظیمات ذخیره شد.", "green"))
    pause()


def menu_db_setup():
    header("راه‌اندازی دیتابیس Supabase")
    print(c("  هر مشتری باید یک دیتابیس Supabase رایگان برای خودش داشته باشد.", "yellow"))
    print()
    print("  مراحل:")
    print("  ─────────────────────────────────────────────────────")
    print()
    print("  1️⃣  به  supabase.com  بروید و حساب رایگان بسازید")
    print()
    print("  2️⃣  New Project بزنید — نام و رمز انتخاب کنید")
    print()
    print("  3️⃣  در داشبورد: SQL Editor → New Query")
    print("      محتوای فایل زیر را کپی و اجرا کنید:")
    print(c(f"      {PROJECT_DIR / 'migrations' / '001_init.sql'}", "cyan"))
    print()
    print("  4️⃣  در داشبورد: Project Settings → API")
    print("      Project URL و service_role key را کپی کنید")
    print()
    print("  5️⃣  در تنظیمات API زیر (گزینه ۵) این مقادیر را وارد کنید")
    print()
    print("  ─────────────────────────────────────────────────────")
    print()
    print(c("  نکته: Supabase رایگان است و نیاز به کارت اعتباری ندارد.", "green"))
    pause()


def menu_api_keys():
    header("تنظیم کلیدهای API")
    env_content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""

    def get_env(key):
        m = re.search(rf'^{key}=(.+)$', env_content, re.MULTILINE)
        return m.group(1).strip() if m else ""

    def mask(v):
        return v[:6] + "..." + v[-4:] if len(v) > 10 else ("تنظیم نشده" if not v else v)

    print(f"  Gemini API Key:    {c(mask(get_env('GEMINI_API_KEY')), 'yellow')}")
    print(f"  Telegram Token:    {c(mask(get_env('TELEGRAM_BOT_TOKEN')), 'yellow')}")
    print(f"  Telegram Chat ID:  {c(mask(get_env('TELEGRAM_CHAT_ID')), 'yellow')}")
    print(f"  Pexels API Key:    {c(mask(get_env('PEXELS_API_KEY')), 'yellow')}")
    print(f"  Supabase URL:      {c(mask(get_env('SUPABASE_URL')), 'yellow')}")
    print(f"  Supabase Key:      {c(mask(get_env('SUPABASE_KEY')), 'yellow')}")
    print()
    print("  کدام کلید را می‌خواهید تغییر دهید؟")
    print("  1. Gemini API Key    4. Pexels API Key")
    print("  2. Telegram Token    5. Supabase URL")
    print("  3. Telegram Chat ID  6. Supabase Key")
    print("  0. بازگشت")
    print()
    choice = input("  انتخاب: ").strip()

    key_map = {
        "1": "GEMINI_API_KEY",
        "2": "TELEGRAM_BOT_TOKEN",
        "3": "TELEGRAM_CHAT_ID",
        "4": "PEXELS_API_KEY",
        "5": "SUPABASE_URL",
        "6": "SUPABASE_KEY",
    }
    if choice in key_map:
        env_key = key_map[choice]
        new_val = input(f"  مقدار جدید {env_key}: ").strip()
        if new_val:
            if f"{env_key}=" in env_content:
                new_env = re.sub(rf'^{env_key}=.*$', f'{env_key}={new_val}', env_content, flags=re.MULTILINE)
            else:
                new_env = env_content.rstrip() + f"\n{env_key}={new_val}\n"
            ENV_FILE.write_text(new_env, encoding="utf-8")
            print(c(f"\n  ✅ {env_key} به‌روز شد.", "green"))
            pause()


def main():
    while True:
        cfg = read_config()
        header("تنظیمات ایجنت تولید محتوا")
        print(f"  سایت: {c(get_value(cfg, 'site_name'), 'yellow')} — {c(get_value(cfg, 'site_url'), 'yellow')}")
        sources = get_sources(cfg)
        keywords = get_keywords(cfg)
        print(f"  منابع RSS: {c(str(len(sources)), 'yellow')} منبع  |  کلیدواژه: {c(str(len(keywords)), 'yellow')} مورد")
        print(f"  مقاله/روز: {c(get_value(cfg, 'articles_per_run'), 'yellow')}  |  ساعت: {c(get_value(cfg, 'run_time'), 'yellow')}")
        print()
        print("  ─────────────────────────────────────────────────────")
        print("  1.  تنظیمات سایت (نام، آدرس، دسته‌بندی)")
        print("  2.  منابع RSS (افزودن / حذف خبرگزاری‌ها)")
        print("  3.  کلیدواژه‌های موضوعی (تغییر حوزه)")
        print("  4.  زمانبندی (تعداد مقاله و ساعت اجرا)")
        print("  5.  کلیدهای API (Gemini, Telegram, Supabase...)")
        print("  6.  راه‌اندازی دیتابیس (Supabase)")
        print()
        print("  0.  خروج")
        print()
        choice = input("  انتخاب: ").strip()

        if choice == "1": menu_site_info()
        elif choice == "2": menu_sources()
        elif choice == "3": menu_keywords()
        elif choice == "4": menu_schedule()
        elif choice == "5": menu_api_keys()
        elif choice == "6": menu_db_setup()
        elif choice == "0": break


if __name__ == "__main__":
    main()
