"""Smoke test زنده — هر جزء pipeline یک بار با Gemini واقعی. بدون تغییر کد موجود.
کیوردها دستی داده می‌شوند تا SEMrush صدا زده نشود (مینیمال).
"""
import sys, time
sys.stdout.reconfigure(encoding="utf-8")

from src import db, llm, writer, qa_analyzer, revision_planner, quality_gate
from src.config import load_settings

cfg = load_settings()
results = {}

def tok_since(baseline_id):
    conn = db.connect()
    rows = conn.execute(
        "SELECT step, model, input_tokens, output_tokens FROM token_log WHERE id > ? ORDER BY id",
        (baseline_id,)).fetchall()
    conn.close()
    return rows

conn = db.connect()
base = conn.execute("SELECT COALESCE(MAX(id),0) FROM token_log").fetchone()[0]
conn.close()

print("="*60)
print(f"SMOKE TEST — provider={cfg.get('provider')} | "
      f"cheap={cfg['gemini_models']['cheap']} | main={cfg['gemini_models']['main']}")
print("="*60)

# [1] llm.ask مستقیم
print("\n[1] llm.ask() مستقیم...")
try:
    r = llm.ask("smoke_llm", "فقط بنویس: OK", model_tier="cheap", json_output=False, max_tokens=50)
    results["llm.ask"] = ("PASS", r.strip()[:40])
except Exception as e:
    results["llm.ask"] = ("FAIL", str(e)[:120])
print("  ", results["llm.ask"])

# [2] Writer (کیورد دستی → بدون SEMrush)
print("\n[2] writer.write_article()...")
brief = {
    "topic": "چت‌بات پشتیبانی مشتری",
    "source_urls": ["https://www.zendesk.com/blog/ai-customer-service/"],
    "summary": "چت‌بات AI پشتیبانی ۲۴ ساعته و کاهش هزینه.",
    "content_gaps": ["مثال ایرانی"], "citable_facts": ["کاهش ۳۰٪ هزینه طبق Zendesk."],
}
kw = {"primary": "ai chatbot", "primary_fa": "چت‌بات هوش مصنوعی", "secondary": ["customer support"], "fa_map": {}}
payload = None
try:
    t = time.time()
    payload = writer.write_article(brief, keywords=kw)
    body = payload.get("body_html", "")
    results["writer"] = ("PASS", f"{len(body.split())} کلمه، {round(time.time()-t)}s")
except Exception as e:
    results["writer"] = ("FAIL", str(e)[:120])
print("  ", results["writer"])

if payload:
    # [3] QA Analyzer
    print("\n[3] qa_analyzer.analyze_article()...")
    analysis = None
    try:
        t = time.time()
        analysis = qa_analyzer.analyze_article(payload, threshold=90)
        results["qa_analyzer"] = ("PASS", f"نمره={analysis['overall_score']}, "
                                  f"issues={len(analysis.get('issues',[]))}, {round(time.time()-t)}s")
    except Exception as e:
        results["qa_analyzer"] = ("FAIL", str(e)[:120])
    print("  ", results["qa_analyzer"])

    # [4] Revision Planner (با issues واقعی QA)
    print("\n[4] revision_planner.build_plan()...")
    try:
        issues = (analysis or {}).get("issues") or [
            {"category":"weak_hook","severity":"medium","location":"مقدمه",
             "exact_quote":"...","problem":"...","rewrite_instruction":"..."}]
        t = time.time()
        plan = revision_planner.build_plan(payload, issues, score=analysis.get("overall_score",80) if analysis else 80, revision_no=1)
        patch0 = plan.get("patches",[{}])[0] if plan.get("patches") else {}
        results["revision_planner"] = ("PASS", f"{len(plan.get('patches',[]))} پچ، "
                                       f"rule={'✓' if patch0.get('rule') else '✗'}, {round(time.time()-t)}s")
    except Exception as e:
        results["revision_planner"] = ("FAIL", str(e)[:120])
    print("  ", results["revision_planner"])

    # [5] Quality Gate
    print("\n[5] quality_gate.review()...")
    try:
        t = time.time()
        gate = quality_gate.review(payload)
        rc = gate.get("rules_compliance", {})
        results["quality_gate"] = ("PASS", f"وزنی={gate['weighted_score']}, لحن={gate['scores'].get('human_tone')}, "
                                   f"rules_compliance={'✓' if rc else '✗'}, {round(time.time()-t)}s")
    except Exception as e:
        results["quality_gate"] = ("FAIL", str(e)[:120])
    print("  ", results["quality_gate"])

# ── گزارش نهایی ──
print("\n" + "="*60)
print("خلاصه")
print("="*60)
for step, (status, detail) in results.items():
    mark = "✅" if status == "PASS" else "❌"
    print(f"  {mark} {step:18s} {detail}")

print("\nمصرف توکن per step:")
rows = tok_since(base)
total_in = total_out = 0
for step, model, ti, to in rows:
    total_in += ti or 0; total_out += to or 0
    print(f"  {step:22s} {model:24s} in={ti} out={to}")
print(f"  {'—'*50}")
print(f"  مجموع: input={total_in} output={total_out} tokens ({len(rows)} تماس)")
