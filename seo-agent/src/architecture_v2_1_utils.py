"""ابزارهای مشترک پچ v2.1 + v2.1.1 — Soft Claims دقیق، Rejection Semantics، Cleanup.

v2.1.1: exact_span/asserted_outcome/confidence در Schema؛ تفکیک hard_policy_reject
از publish_reject (would_reject = alias publish_reject)؛ merge اتحاد کنترل‌شده با
Span Validation؛ اهداف Mandatory Cleanup. همه‌چیز Fail-Closed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

VALIDATOR_VERSION = "2.1.1"

SOFT_QUANTITATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # زمان و مدت
    (r"معمولاً", "duration_or_frequency_generalization"),
    (r"اغلب", "frequency_generalization"),
    (r"اکثراً", "frequency_generalization"),
    (r"در بیشتر موارد", "frequency_generalization"),
    (r"بسیاری از", "frequency_generalization"),
    (r"بخش بزرگی از", "frequency_generalization"),
    (r"چندین هفته", "duration_generalization"),
    (r"چند هفته", "duration_generalization"),
    (r"چند روز", "duration_generalization"),
    (r"در مدت کوتاه", "duration_generalization"),
    (r"در زمان کوتاه", "duration_generalization"),
    # عملکرد و دقت
    (r"دقت بسیار بالا", "performance_generalization"),
    (r"دقت بالا", "performance_generalization"),
    (r"عملکرد بسیار بهتر", "performance_generalization"),
    (r"عملکرد بهتر", "performance_generalization"),
    (r"به شکل چشمگیری", "performance_generalization"),
    (r"به‌طور چشمگیری", "performance_generalization"),
    (r"به طور چشمگیری", "performance_generalization"),
    (r"به شکل قابل[‌ ]?توجهی", "performance_generalization"),
    (r"به‌طور قابل[‌ ]?توجهی", "performance_generalization"),
    (r"به طور قابل[‌ ]?توجهی", "performance_generalization"),
    (r"رشد چشمگیر", "performance_generalization"),
    (r"افزایش چشمگیر", "performance_generalization"),
    (r"کاهش چشمگیر", "performance_generalization"),
    (r"رشد محسوس", "performance_generalization"),
    (r"افزایش محسوس", "performance_generalization"),
    (r"کاهش محسوس", "performance_generalization"),
    (r"افزایش قابل[‌ ]?توجه", "performance_generalization"),
    # هزینه و سرعت
    (r"هزینه کمتر", "cost_generalization"),
    (r"هزینه‌های کمتر", "cost_generalization"),
    (r"صرفه[‌ ]?جویی قابل[‌ ]?توجه", "cost_generalization"),
    (r"بسیار سریع‌تر", "speed_generalization"),
    (r"سریع‌تر", "speed_generalization"),
    (r"زمان کمتر", "duration_generalization"),
)

SAFE_NEUTRAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"به .* بستگی دارد"),
    re.compile(r"باید .* آزمایش شود"),
    re.compile(r"بدون .* قابل تعیین نیست"),
    re.compile(r"ممکن است"),
    re.compile(r"می‌تواند"),
)

# ── کالیبراسیون confidence (v2.1.1 calibration patch) ──────────────
# الگوهای «شدت/نتیجه‌محور»: خودشان یک نتیجه‌ی سنجش‌پذیر (دقت/سرعت/هزینه/رشد/مدت)
# را Assert می‌کنند → ذاتاً high (اگر span معتبر، بی‌منبع و غیرشرطی باشد).
_INTENSITY_PATTERNS: frozenset[str] = frozenset({
    "دقت بسیار بالا", "دقت بالا", "عملکرد بسیار بهتر", "عملکرد بهتر",
    "رشد چشمگیر", "افزایش چشمگیر", "کاهش چشمگیر", "رشد محسوس", "افزایش محسوس",
    "کاهش محسوس", "افزایش قابل[‌ ]?توجه", "هزینه کمتر", "هزینه‌های کمتر",
    "صرفه[‌ ]?جویی قابل[‌ ]?توجه", "بسیار سریع‌تر", "سریع‌تر", "زمان کمتر",
    "چندین هفته", "چند هفته", "چند روز", "در مدت کوتاه", "در زمان کوتاه",
})
# «نشانه‌ی نتیجه‌ی واقعی»: فعل/اسمِ تغییرِ سنجش‌پذیر. تعمیم‌دهنده‌ی فراوانی
# (بسیاری/اغلب/معمولاً/به‌طور چشمگیری) فقط در حضور یکی از این‌ها high می‌شود.
# عمداً «سریع» و «دقت» را اینجا نمی‌آوریم (پوشش‌شان با الگوهای شدت است) تا
# «اهمیت به پاسخ سریع» به‌اشتباه high نشود.
_RESULT_CUE_RE = re.compile(
    r"کاهش|افزایش|صرفه[‌ ]?جوی|خودکار|بهبود|بهینه|رشد|بازده|تبدیل|"
    r"طول می‌کش|زمان می‌بر|خرید|بازگشت|درآمد|فروش|سود می|سودآور"
)

_CONFIDENCE_PRIORITY = {"high": 3, "medium": 2, "low": 1}

HARD_POLICY_CODES: frozenset[str] = frozenset({
    "unsupported_quantitative_claim",
    "unsupported_soft_quantitative_claim_high",
    "unapproved_cta",
    "fabricated_first_person_experience",
    "fabricated_case_study",
    "new_unapproved_number",
    "new_unapproved_percentage",
    "new_unapproved_price",
    "new_unapproved_url",
    "new_unapproved_entity",
    "verified_fact_changed",
    "locked_number_changed",
    "validator_failed",
    "schema_error",
    "missing_required_evaluation_fields",
    "validator_event_persistence_failed",
    "hard_forbidden_phrase",
})


@dataclass(frozen=True)
class SoftQuantitativeClaim:
    claim: str
    exact_span: str
    category: str
    asserted_outcome: str
    supported: bool
    verified_fact_id: str | None
    confidence: str          # high | medium | low
    required_action: str     # keep | remove | neutralize
    reason: str

    source: str = "deterministic"       # deterministic | llm
    exact_span_valid: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "exact_span": self.exact_span,
            "category": self.category,
            "asserted_outcome": self.asserted_outcome,
            "supported": self.supported,
            "verified_fact_id": self.verified_fact_id,
            "confidence": self.confidence,
            "required_action": self.required_action,
            "reason": self.reason,
            "source": self.source,
            "exact_span_valid": self.exact_span_valid,
        }


def normalize_text_for_hash(text: str) -> str:
    """نرمال‌سازی محافظه‌کارانه برای Cache — محتوا/H2/عدد/Marker را تغییر نمی‌دهد."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip()


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        payload = normalize_text_for_hash(value)
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def split_into_claim_units(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text or "")
    parts = re.split(r"(?<=[.!؟؛])\s+|\n+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _contains_safe_neutralization(claim: str) -> bool:
    return any(pattern.search(claim) for pattern in SAFE_NEUTRAL_PATTERNS)


def _match_verified_fact(
    claim: str, verified_facts: Sequence[Mapping[str, Any]],
) -> str | None:
    """Matching محافظه‌کارانه — در شک، None (یعنی unsupported)."""
    normalized_claim = normalize_text_for_hash(claim)
    for fact in verified_facts:
        fact_id = str(fact.get("id") or "").strip()
        fact_claim = normalize_text_for_hash(str(fact.get("claim") or ""))
        allowed_scope = fact.get("allowed_scope")
        if not fact_id or not fact_claim:
            continue
        if allowed_scope in (None, "", [], {}):
            continue
        if fact_claim in normalized_claim or normalized_claim in fact_claim:
            return fact_id
    return None


def deduplicate_soft_claims(
    claims: Sequence[SoftQuantitativeClaim],
) -> list[SoftQuantitativeClaim]:
    unique: dict[tuple[str, str, str], SoftQuantitativeClaim] = {}
    for item in claims:
        key = (item.claim, item.exact_span, item.category)
        if key not in unique:
            unique[key] = item
            continue
        previous = unique[key]
        if _CONFIDENCE_PRIORITY.get(item.confidence, 0) > _CONFIDENCE_PRIORITY.get(previous.confidence, 0):
            unique[key] = item
            continue
        # Fail-Closed: Unsupported بر Supported غلبه می‌کند
        if previous.supported and not item.supported:
            unique[key] = item
    return list(unique.values())


def deduplicate_soft_claim_dicts(claims: Sequence[Mapping[str, Any]]) -> list[dict]:
    unique: dict[tuple[str, str, str], dict] = {}
    for item in claims:
        d = dict(item)
        key = (str(d.get("claim") or ""), str(d.get("exact_span") or ""),
               str(d.get("category") or "unknown"))
        if not key[0]:
            continue
        if key not in unique:
            unique[key] = d
            continue
        previous = unique[key]
        if _CONFIDENCE_PRIORITY.get(d.get("confidence"), 0) > _CONFIDENCE_PRIORITY.get(previous.get("confidence"), 0):
            unique[key] = d
            continue
        if bool(previous.get("supported")) and not bool(d.get("supported")):
            unique[key] = d
    return list(unique.values())


def _soft_confidence(pattern: str, unit: str) -> str:
    """confidence قطعی (calibration patch):
    - الگوی شدت/نتیجه‌محور → high (ذاتاً یک نتیجه‌ی سنجش‌پذیر را Assert می‌کند).
    - تعمیم‌دهنده‌ی فراوانی → high فقط با «نشانه‌ی نتیجه» در همان جمله، وگرنه medium.
    """
    if pattern in _INTENSITY_PATTERNS:
        return "high"
    return "high" if _RESULT_CUE_RE.search(unit) else "medium"


def detect_soft_quantitative_claims(
    text: str,
    verified_facts: Sequence[Mapping[str, Any]] | None = None,
) -> list[SoftQuantitativeClaim]:
    """آشکارساز قطعی — Span واقعی با finditer؛ confidence کالیبره‌شده (high/medium).

    تعمیم‌دهنده‌ی فراوانی بدون نتیجه‌ی سنجش‌پذیر → medium (نه hard reject).
    جمله‌ی شرطی/احتمالی → هیچ ادعایی (خنثی).
    """
    verified_facts = verified_facts or []
    results: list[SoftQuantitativeClaim] = []
    for unit in split_into_claim_units(text):
        if _contains_safe_neutralization(unit):
            continue
        for pattern, category in SOFT_QUANTITATIVE_PATTERNS:
            for match in re.finditer(pattern, unit):
                exact_span = match.group(0)
                fact_id = _match_verified_fact(unit, verified_facts)
                supported = fact_id is not None
                conf = _soft_confidence(pattern, unit)
                results.append(SoftQuantitativeClaim(
                    claim=unit,
                    exact_span=exact_span,
                    category=category,
                    asserted_outcome=unit,
                    supported=supported,
                    verified_fact_id=fact_id,
                    confidence=conf,
                    required_action="keep" if supported else "neutralize",
                    reason=("Matched an approved verified_fact." if supported
                            else f"Soft quantitative phrase ({conf}) with no approved verified_fact."),
                    source="deterministic",
                    exact_span_valid=True,
                ))
    return deduplicate_soft_claims(results)


def count_unsupported_soft_claims(
    claims: Iterable[SoftQuantitativeClaim | Mapping[str, Any]],
) -> int:
    total = 0
    for claim in claims:
        supported = (claim.supported if isinstance(claim, SoftQuantitativeClaim)
                     else bool(claim.get("supported", False)))
        if not supported:
            total += 1
    return total


def validate_llm_soft_claim(
    *, item: Mapping[str, Any], article_text: str,
) -> tuple[bool, str | None]:
    """داور حق اختراع Span ندارد — هر ادعای LLM باید عیناً در متن باشد."""
    claim = str(item.get("claim") or "").strip()
    exact_span = str(item.get("exact_span") or "").strip()
    confidence = str(item.get("confidence") or "").strip()
    action = str(item.get("required_action") or "").strip()
    if not claim or not exact_span:
        return False, "missing_claim_or_exact_span"
    if exact_span not in claim:
        return False, "exact_span_not_in_claim"
    if exact_span not in article_text:
        return False, "exact_span_not_in_article"
    if claim not in article_text:
        return False, "claim_not_in_article"
    if confidence not in {"high", "medium", "low"}:
        return False, "invalid_confidence"
    if action not in {"keep", "remove", "neutralize"}:
        return False, "invalid_required_action"
    return True, None


def merge_soft_claims(
    *,
    deterministic_claims: Sequence[Mapping[str, Any]],
    llm_claims: Sequence[Mapping[str, Any]],
    article_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """اتحاد کنترل‌شده (calibration patch): قطعی مبنا؛ LLM فقط تایید/تنزل/طبقه‌بندی.

    - LLM نمی‌تواند یک high مستقل بسازد؛ Claim فقط-LLM حداکثر medium می‌گیرد.
    - LLM می‌تواند یک Candidate قطعی را تنزل دهد (نه ارتقا).
    - Span جعلی (نبود در مقاله) → فقط حذف Claim + گزارش warning (نه hard reject).
    """
    det: list[dict[str, Any]] = [dict(i) for i in deterministic_claims]
    for d in det:
        d.setdefault("source", "deterministic")
        d.setdefault("exact_span_valid", True)
    index = {(str(d.get("exact_span") or ""), str(d.get("category") or "")): d for d in det}
    invalid_claims: list[dict[str, Any]] = []
    for item in llm_claims or []:
        ok, error = validate_llm_soft_claim(item=item, article_text=article_text)
        if not ok:
            invalid_claims.append({"item": dict(item), "error": error,
                                   "code": "gate_claim_invalid_span",
                                   "source": "llm_gate", "severity": "evaluator_warning"})
            continue
        key = (str(item.get("exact_span") or ""), str(item.get("category") or ""))
        llm_conf = str(item.get("confidence") or "medium")
        matched = index.get(key)
        if matched is not None:
            # تایید/تنزل: LLM فقط می‌تواند confidence قطعی را پایین بیاورد
            if _CONFIDENCE_PRIORITY.get(llm_conf, 2) < _CONFIDENCE_PRIORITY.get(matched.get("confidence"), 3):
                matched["confidence"] = llm_conf
                matched["required_action"] = item.get("required_action") or matched.get("required_action")
        else:
            # LLM-only: هرگز high مستقل → سقف medium
            c = dict(item)
            c["confidence"] = "low" if llm_conf == "low" else "medium"
            c["source"] = "llm"
            c["exact_span_valid"] = True
            det.append(c)
    return deduplicate_soft_claim_dicts(det), invalid_claims


def count_soft_by_confidence(merged: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for item in merged:
        if item.get("supported") is True:
            continue
        c = item.get("confidence")
        if c in counts:
            counts[c] += 1
    return counts


# ── Rejection Semantics (v2.1.1) ─────────────────────────────────

def _issue_code(issue: Any) -> str:
    if isinstance(issue, str):
        return issue.strip()
    if isinstance(issue, Mapping):
        return str(issue.get("code") or "").strip()
    return ""


def compute_hard_policy_reject(evaluation: Mapping[str, Any]) -> bool:
    """Fail-Closed — فقط تخلف‌های سیاستی سخت (نه امتیاز پایین)."""
    if evaluation.get("validator_passed") is not True:
        return True
    if evaluation.get("schema_valid") is False:
        return True
    if evaluation.get("validator_event_persisted") is False:
        return True
    if int(evaluation.get("unsupported_claim_count") or 0) > 0:
        return True
    if int(evaluation.get("high_confidence_soft_unsupported_count") or 0) > 0:
        return True
    if int(evaluation.get("forbidden_found") or 0) > 0:
        return True
    for collection in (evaluation.get("hard_errors") or [],
                       evaluation.get("policy_violations") or [],
                       evaluation.get("validator_reasons") or []):
        for issue in collection:
            if _issue_code(issue) in HARD_POLICY_CODES:
                return True
    return False


def compute_publish_reject(
    *, hard_policy_reject: bool, final_score: float,
    publish_threshold: float, unresolved_source_gap: bool,
) -> bool:
    return bool(hard_policy_reject
                or final_score < publish_threshold
                or unresolved_source_gap)


def apply_rejection_semantics(
    evaluation: dict[str, Any], *, publish_threshold: float,
) -> dict[str, Any]:
    """یک منبع حقیقت: hard_policy_reject / publish_reject (would_reject = alias)."""
    hard_reject = compute_hard_policy_reject(evaluation)
    source_gap = bool(evaluation.get("unresolved_source_gap", False))
    score = float(evaluation.get("final_score") or 0.0)
    publish_reject = compute_publish_reject(
        hard_policy_reject=hard_reject, final_score=score,
        publish_threshold=publish_threshold, unresolved_source_gap=source_gap,
    )
    evaluation["hard_policy_reject"] = hard_reject
    evaluation["publish_reject"] = publish_reject
    evaluation["would_reject"] = publish_reject
    evaluation["passed"] = not publish_reject
    return evaluation


# ── QA Cache ────────────────────────────────────────────────────

def build_qa_cache_key(
    *, text: str, model_name: str, qa_prompt_version: str,
    editorial_rules: Any, verified_facts: Any,
) -> str:
    payload = {
        "content_hash": stable_hash(text),
        "model_name": model_name,
        "qa_prompt_version": qa_prompt_version,
        "editorial_rules_hash": stable_hash(editorial_rules),
        "verified_facts_hash": stable_hash(verified_facts),
    }
    return stable_hash(payload)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── انتخاب نسخه‌ی برنده (v2.1.1) ─────────────────────────────────

def build_version_rank(result: Mapping[str, Any]) -> tuple:
    """بزرگ‌تر = بهتر. soft با confidence=low فقط گزارشی است و در Rank نیست."""
    return (
        -safe_int(result.get("hard_error_count")),
        -safe_int(result.get("unsupported_claim_count")),
        -safe_int(result.get("high_confidence_soft_unsupported_count")),
        -safe_int(result.get("medium_confidence_soft_unsupported_count")),
        -safe_int(result.get("rewrite_warning_count")),
        safe_float(result.get("final_score")),
    )


def should_save_candidate(
    *, candidate_result: Mapping[str, Any], previous_result: Mapping[str, Any],
) -> tuple[bool, str]:
    """نسخه‌ی میانی می‌تواند publish_reject باشد (امتیاز زیر آستانه)؛
    ولی نسخه‌ی دارای Hard Policy Violation هرگز ذخیره نمی‌شود."""
    if candidate_result.get("hard_policy_reject") is not False:
        return False, "candidate_hard_policy_reject"
    if candidate_result.get("validator_passed") is not True:
        return False, "candidate_validator_failed_or_missing"
    candidate_rank = build_version_rank(candidate_result)
    previous_rank = build_version_rank(previous_result)
    if candidate_rank > previous_rank:
        return True, "candidate_strictly_better"
    if candidate_rank == previous_rank:
        return False, "rank_tied_keep_previous"
    return False, "candidate_rank_worse"


# ── اهداف Mandatory Cleanup (v2.1.1) ─────────────────────────────

def deduplicate_cleanup_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in targets:
        exact_span = str(item.get("exact_span") or "").strip()
        category = str(item.get("category") or "unknown").strip()
        if not exact_span:
            continue  # بدون Span دقیق، پچ خودکار امن نیست
        key = (exact_span, category)
        if key not in unique:
            unique[key] = item
            continue
        current = unique[key]
        if _CONFIDENCE_PRIORITY.get(item.get("confidence"), 0) > _CONFIDENCE_PRIORITY.get(current.get("confidence"), 0):
            unique[key] = item
    return list(unique.values())


def collect_cleanup_targets(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]:
    """اهداف پاک‌سازی از ارزیابی: ادعای کمی صریح/نرم (high|medium) و عبارات ممنوعه."""
    targets: list[dict[str, Any]] = []
    for item in evaluation.get("unsupported_claims") or []:
        if item.get("required_action") in {"remove", "neutralize", "remove_or_neutralize"}:
            targets.append({**item, "source_group": "unsupported_claims"})
    for item in evaluation.get("soft_quantitative_claims") or []:
        # Calibration patch: فقط high قطعیِ deterministic با span معتبر → Cleanup.
        # medium/low هرگز Cleanup را فعال نمی‌کنند (بدون مصرف توکن اضافه).
        if (item.get("supported") is not True
                and item.get("confidence") == "high"
                and item.get("exact_span_valid") is not False
                and "deterministic" in str(item.get("source") or "deterministic")
                and item.get("required_action") in {"remove", "neutralize",
                                                    "remove_or_neutralize"}):
            targets.append({**item, "source_group": "soft_quantitative_claims"})
    for item in evaluation.get("forbidden_phrase_issues") or []:
        if item.get("required_action") in {"remove", "neutralize", "remove_or_neutralize"}:
            targets.append({**item, "source_group": "forbidden_phrase_issues"})
    return deduplicate_cleanup_targets(targets)
