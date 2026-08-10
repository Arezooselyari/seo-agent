"""گزارش مقایسه‌ی فاز ۱ — final_score جدید در برابر وضعیت فعلی مقالات (فقط خواندن).

برای هر مقاله‌ی دارای qa_analysis در agent.db:
وضعیت فعلی DB، seo_grade فعلی، final_score/verdict محاسبه‌شده، اختلاف، و وضعیت گیت‌ها.
هیچ چیزی در DB نوشته نمی‌شود؛ هیچ تماس LLM زده نمی‌شود.
اجرا:  python compare_final_score.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import db, final_score

# نگاشت وضعیت DB به verdict قابل‌مقایسه — approved/published = تایید؛ بقیه = بررسی
_STATUS_AS_VERDICT = {"approved": "approved", "published": "approved"}


def _fmt_gate(v):
    return {True: "پاس", False: "ردّ", None: "—"}[v]


def main():
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, status, title_seo, payload FROM articles ORDER BY id"
    ).fetchall()
    conn.close()

    print("=" * 100)
    print("گزارش مقایسه‌ی فاز ۱ — لایه‌ی final_score (فقط محاسبه؛ DB دست‌نخورده)")
    print("=" * 100)

    match = diff = 0
    for row in rows:
        payload = json.loads(row["payload"])
        qa = payload.get("qa_analysis")
        if not qa:
            print(f"\n#{row['id']} | {row['status']} | بدون qa_analysis — قابل‌محاسبه نیست (داده‌ی قدیمی)")
            continue

        r = final_score.compute(qa)
        b = r["score_breakdown"]
        g = b["hard_gates"]
        seo_grade = payload.get("seo_grade", "-")
        current_verdict = _STATUS_AS_VERDICT.get(row["status"], "needs_review")
        same = current_verdict == r["final_verdict"]
        if same:
            match += 1
        else:
            diff += 1

        comps = b["components"]
        comp_str = ", ".join(
            f"{k}={v if v is not None else '—'}" for k, v in comps.items()
        )
        print(f"\n#{row['id']} | {row['title_seo'][:55]}")
        print(f"   وضعیت فعلی DB: {row['status']}  (seo_grade={seo_grade})")
        print(f"   نمره‌ی نهایی جدید: {r['final_score']}  →  verdict جدید: {r['final_verdict']}"
              + ("  ✔ همسو" if same else "  ⚠ متفاوت"))
        print(f"   اختلاف نمره: seo_grade {seo_grade} → final {r['final_score']} "
              f"({round(r['final_score'] - seo_grade, 1):+} امتیاز)"
              if isinstance(seo_grade, (int, float)) else "   اختلاف نمره: —")
        print(f"   اجزا: {comp_str}")
        print(f"   گیت‌ها: QA={_fmt_gate(g['qa_passed'])} | "
              f"کیفیت={_fmt_gate(g['quality_gate_passed'])} | "
              f"کد={_fmt_gate(g['code_checks_ok'])} | "
              f"SEMrush={_fmt_gate(g['semrush_ok'])} | "
              f"آستانه={_fmt_gate(g['score_ok'])}")
        if b["would_reject"]:
            print("   🚩 نامزد ردّ (فاز ۱: فقط برچسب — needs_review می‌ماند)")
        if b["reasons"]:
            for reason in b["reasons"]:
                print(f"   • {reason}")

    print("\n" + "=" * 100)
    print(f"جمع‌بندی: {match} مقاله همسو با وضعیت فعلی، {diff} مقاله متفاوت")
    print("نکته: وضعیت فعلی DB شامل تصمیم‌های دستی تلگرام است؛ verdict جدید فقط تصمیم خودکار را نشان می‌دهد.")
    print("=" * 100)


if __name__ == "__main__":
    main()
