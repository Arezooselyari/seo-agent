"""لایه‌ی نمره‌دهی نهایی متمرکز — تنها منبع تصمیم انتشار/بررسی (فاز ۱).

ورودی: دیکشنری analysis (خروجی qa_analyzer + merge_semrush + quality_gate) —
هم شکل زنده‌ی حلقه‌ی تحریریه را می‌پذیرد، هم شکل ذخیره‌شده‌ی qa_analysis در DB.

اصول (مصوب کاربر):
1. گیت‌های سخت حفظ می‌شوند — final_score میانگین وزنیِ صرف نیست و جای گیت را نمی‌گیرد.
   approved یعنی: qa_passed و quality_gate_passed و code_checks و SEMrush قابل‌قبول
   و final_score >= آستانه. نمره‌ی بالا هیچ گیت ردشده‌ای را جبران نمی‌کند.
2. فاز ۱ فقط دو verdict دارد: approved | needs_review.
   ردّ خودکار غیرفعال است؛ نامزد ردّ فقط با پرچم would_reject علامت می‌خورد.
3. سازگاری عقب‌رو: این ماژول ورودی را تغییر نمی‌دهد (تابع خالص)، seo_grade دست
   نمی‌خورد؛ خروجی فیلدهای جدید final_score / final_verdict / score_breakdown است.

فاز ۱: هنوز به evaluate_and_sync وصل نیست (settings: final_score.enabled=false).
بدون فراخوانی LLM، بدون I/O دیتابیس — فقط محاسبه.
"""
import logging

from .config import load_settings

logger = logging.getLogger(__name__)

# پیش‌فرض‌ها — اگر بخش final_score در settings نبود، سیستم با همین‌ها کار می‌کند.
# حالتِ ranking-aligned: seo (چک‌لیستِ عواملِ رتبه‌ی گوگل) مؤلفه‌ی غالب است؛
# qa/gate (داورِ سلیقه‌ای) وزنِ کم و نقشِ advisory دارند.
_DEFAULT_WEIGHTS = {"seo": 0.55, "qa": 0.20, "gate": 0.10, "semrush": 0.15}
_DEFAULT_SEMRUSH_MAP = {"GOOD": 100.0, "WEAK": 50.0}
_DEFAULT_THRESHOLD = 90
_DEFAULT_REJECT_BELOW = 60


def _cfg(config: dict | None = None) -> dict:
    if config is not None:
        return config
    return load_settings().get("final_score", {}) or {}


# ── استخراج اجزا از analysis (سازگار با شکل زنده و شکل ذخیره‌شده در DB) ──

def _qa_passed(analysis: dict) -> bool | None:
    """qa_passed از شکل زنده، وگرنه qa_report.passed از شکل ذخیره‌شده. None=نامعلوم."""
    if "qa_passed" in analysis:
        return bool(analysis["qa_passed"])
    qa_report = analysis.get("qa_report")
    if isinstance(qa_report, dict) and "passed" in qa_report:
        return bool(qa_report["passed"])
    return None


def _code_ok(analysis: dict) -> bool | None:
    """همه‌ی چک‌های کد پاس؟ اگر code_checks در دسترس نبود (داده‌ی قدیمی DB) → None."""
    checks = analysis.get("code_checks")
    if not isinstance(checks, dict):
        return None
    return all(v for k, v in checks.items() if not k.startswith("_"))


def _gate_passed(analysis: dict) -> bool | None:
    """عبور دروازه‌ی کیفیت. اگر گیت اجرا نشده (غیرفعال/داده‌ی قدیمی) → None."""
    gate = analysis.get("quality_gate")
    if not isinstance(gate, dict):
        return None
    return bool(gate.get("passed"))


def _semrush_ok(analysis: dict) -> bool | None:
    """SEMrush قابل‌قبول؟ WEAK → ردّ؛ GOOD/UNKNOWN → قبول؛ بدون گزارش → None."""
    if analysis.get("semrush_weak"):
        return False
    sr = analysis.get("semrush")
    if not isinstance(sr, dict):
        return None
    return sr.get("verdict") != "WEAK"


def _seo_passed(analysis: dict) -> bool | None:
    """چک‌لیستِ عواملِ رتبه‌ی گوگل پاس شد؟ نبودِ چک‌لیست → None (داده نیست)."""
    sc = analysis.get("seo_checklist")
    if not isinstance(sc, dict):
        return None
    return bool(sc.get("passed"))


def _components(analysis: dict, cfg: dict) -> dict:
    """اجزای نمره در مقیاس ۰-۱۰۰. جزء غایب → None (از میانگین حذف می‌شود)."""
    out = {"seo": None, "qa": None, "gate": None, "semrush": None}

    sc = analysis.get("seo_checklist")
    if isinstance(sc, dict) and isinstance(sc.get("seo_score"), (int, float)):
        out["seo"] = float(sc["seo_score"])   # چک‌لیستِ عینیِ عواملِ رتبه (۰-۱۰۰)

    score = analysis.get("overall_score")
    if isinstance(score, (int, float)):
        out["qa"] = float(score)

    gate = analysis.get("quality_gate")
    if isinstance(gate, dict):
        w = gate.get("weighted_score")
        if isinstance(w, (int, float)):
            out["gate"] = float(w) * 10.0     # ۰-۱۰ → ۰-۱۰۰

    sr = analysis.get("semrush")
    if isinstance(sr, dict):
        verdict = sr.get("verdict")
        sr_map = {**_DEFAULT_SEMRUSH_MAP, **(cfg.get("semrush_component") or {})}
        if verdict in sr_map:
            out["semrush"] = float(sr_map[verdict])
        # UNKNOWN یا verdict ناشناخته → None → از میانگین حذف (داده نداریم، جریمه نکن)

    return out


# ── API اصلی ──────────────────────────────────────────────────────

def compute(analysis: dict, config: dict | None = None) -> dict:
    """نمره‌ی نهایی و verdict را از یک analysis محاسبه می‌کند (تابع خالص).

    Returns:
        {
          "final_score": float ۰-۱۰۰,
          "final_verdict": "approved" | "needs_review",
          "score_breakdown": {
              "components": {qa, gate, semrush},        # ۰-۱۰۰ یا None اگر غایب
              "weights_used": {...},                    # وزن‌های نرمال‌شده‌ی اجزای موجود
              "hard_gates": {qa_passed, quality_gate_passed, code_checks_ok,
                             semrush_ok, score_ok},     # True/False/None (None=داده نبود)
              "would_reject": bool,                     # فقط برچسب — ردّ خودکار فعال نیست
              "reasons": [...],                         # دلایل عدم approved (خالی اگر approved)
          },
        }
    """
    cfg = _cfg(config)
    threshold = float(cfg.get("approval_threshold", _DEFAULT_THRESHOLD))
    weights = {**_DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}

    # نمره‌ی وزنی — وزن اجزای غایب بین اجزای موجود بازتوزیع می‌شود
    comps = _components(analysis, cfg)
    total, wsum = 0.0, 0.0
    for key, w in weights.items():
        v = comps.get(key)
        if v is not None:
            total += v * float(w)
            wsum += float(w)
    final = round(total / wsum, 1) if wsum else 0.0
    weights_used = {
        k: round(float(weights[k]) / wsum, 3)
        for k in weights if comps.get(k) is not None and wsum
    }

    # گیت‌های سخت — None یعنی داده در دسترس نیست؛ فقط False صریح مانع approved می‌شود
    gates = {
        "seo_ok": _seo_passed(analysis),
        "qa_passed": _qa_passed(analysis),
        "quality_gate_passed": _gate_passed(analysis),
        "code_checks_ok": _code_ok(analysis),
        "semrush_ok": _semrush_ok(analysis),
        "score_ok": final >= threshold,
    }

    # حالتِ ranking-aligned (مصوب کاربر): «از گوگل سخت‌گیرتر نباش.» تصمیم بر پایه‌ی
    # عواملِ عینیِ رتبه (seo_ok) + آنتی‌جعل (hard_policy) است؛ داورِ سلیقه‌ایِ لحن
    # (qa_passed/quality_gate_passed) فقط advisory است و مانعِ رسیدن به تلگرام نمی‌شود.
    ranking_mode = bool(cfg.get("ranking_aligned_mode"))

    reasons = []
    if gates["seo_ok"] is False:
        sc = analysis.get("seo_checklist") or {}
        miss = sc.get("critical_misses") or []
        reasons.append(
            f"عواملِ رتبه‌ی گوگل کامل رعایت نشد (نمره‌ی چک‌لیست {sc.get('seo_score','?')}"
            + (f"، شکستِ بحرانی: {miss}" if miss else "") + ")"
        )
    _advisory = " (advisory — مسدودکننده نیست)" if ranking_mode else ""
    if gates["qa_passed"] is False:
        reasons.append("QA سلیقه‌ای پایین" + _advisory if ranking_mode
                       else "QA پاس نشد (qa_report.passed=false)")
    if gates["quality_gate_passed"] is False:
        reasons.append("لحن/E-E-A-Tِ سلیقه‌ای پایین" + _advisory if ranking_mode
                       else "دروازه‌ی کیفیت (لحن انسانی/E-E-A-T) پاس نشد")
    if gates["code_checks_ok"] is False:
        reasons.append("چک‌های قطعی کد ناموفق")
    if gates["semrush_ok"] is False:
        reasons.append("کیوردهای هدف طبق SEMrush ضعیف/پررقابت‌اند (WEAK)")
    if not gates["score_ok"]:
        reasons.append(f"نمره‌ی نهایی {final} < آستانه {threshold:g}")

    # ── v2.1.1: دو مفهوم مستقل — hard_policy_reject (تخلف سیاستی سخت) و
    # publish_reject (تصمیم انتشار). would_reject فقط alias دومی است.
    details = (analysis.get("code_checks") or {}).get("_details", {}) or {}
    forbidden = list(details.get("found_forbidden") or []) + list(
        details.get("found_unapproved_cta") or []
    )
    gate_rep = analysis.get("quality_gate") or {}
    unsupported = [
        c for c in (gate_rep.get("quantitative_claims") or [])
        if (c.get("status") or "").lower() == "unsupported"
    ]
    high_soft = int(gate_rep.get("high_confidence_soft_unsupported_count", 0) or 0)
    medium_soft = int(gate_rep.get("medium_confidence_soft_unsupported_count", 0) or 0)
    soft_total = int(gate_rep.get("soft_unsupported_claim_count", 0) or 0)
    if not gate_rep:
        # Fail-Closed: بدون گزارش گیت، ایرادات قطعی QA (همگی high-confidence)
        high_soft = sum(1 for i in (analysis.get("issues") or [])
                        if i.get("category") == "unsupported_soft_claim")
        soft_total = high_soft

    hard_policy_reject = bool(
        len(unsupported) > 0
        or high_soft > 0
        or len(forbidden) > 0
        or gate_rep.get("schema_valid") is False
        or analysis.get("validator_persist_failed")
    )
    # Calibration patch: medium دیگر source_gap مسدودکننده نمی‌سازد (فقط warning)
    unresolved_source_gap = bool(gate_rep.get("unresolved_source_gap"))

    if hard_policy_reject:
        reasons.append("تخلف سیاستی سخت (hard_policy_reject)")
    if medium_soft > 0:
        reasons.append(f"{medium_soft} ادعای کمی نرم medium (warning — بدون ردّ)")

    if ranking_mode:
        # عواملِ عینیِ رتبه + چک‌های کد + SEMrush + نمره + آنتی‌جعل.
        # qa_passed و quality_gate_passed عمداً حذف شده‌اند (advisory).
        approved = (
            gates["seo_ok"] is not False
            and gates["code_checks_ok"] is not False
            and gates["semrush_ok"] is not False
            and gates["score_ok"]
            and not hard_policy_reject
            and not unresolved_source_gap
        )
    else:
        approved = (
            all(g is not False for g in gates.values())
            and gates["score_ok"]
            and not hard_policy_reject
            and not unresolved_source_gap
        )
    publish_reject = not approved

    return {
        "final_score": final,
        "final_verdict": "approved" if approved else "needs_review",
        "score_breakdown": {
            "components": comps,
            "weights_used": weights_used,
            "hard_gates": gates,
            "hard_policy_reject": hard_policy_reject,
            "publish_reject": publish_reject,
            "would_reject": publish_reject,   # alias — منبع حقیقت publish_reject است
            "unresolved_source_gap": unresolved_source_gap,
            "unsupported_claims": len(unsupported),
            "soft_unsupported_claims": soft_total,
            "high_confidence_soft_unsupported_count": high_soft,
            "medium_confidence_soft_unsupported_count": medium_soft,
            "forbidden_found": len(forbidden),
            "reasons": reasons,
        },
    }


def rank_key(analysis: dict, config: dict | None = None) -> tuple:
    """کلید مقایسه‌ی نسخه‌ها در حلقه‌ی تحریریه (جایگزین آتی _rank در evaluate_and_sync).

    ترتیب: عبور همه‌ی گیت‌های سخت > نمره‌ی نهایی > نمره‌ی فنی QA.
    فاز ۲ از این استفاده خواهد کرد؛ فاز ۱ فقط در تست‌ها.
    """
    result = compute(analysis, config)
    gates = result["score_breakdown"]["hard_gates"]
    # score_ok عمداً در سطح‌بندی نیست: نسخه‌ی زیر آستانه ولی با گیت‌های کیفی پاس،
    # بالاتر از نسخه‌ی ردِ گیت رتبه می‌گیرد (همان فلسفه‌ی _rank فعلی)
    gates_ok = all(
        gates[k] is not False
        for k in ("qa_passed", "quality_gate_passed", "code_checks_ok", "semrush_ok")
    )
    return (
        gates_ok,
        result["final_score"],
        float(analysis.get("overall_score") or 0),
    )
