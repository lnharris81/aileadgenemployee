"""ICP-fit scoring. Explainable: every point has a reason string. Also picks the primary contact per company."""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .util import is_offsite_crawl_email, parse_json, text_has_any

DEFAULT_WEIGHTS: Dict[str, float] = {
    "has_email": 25, "personal_email": 10, "verified_email": 15, "catch_all_email": 5, "mx_ok_email": 5,
    "has_phone": 10, "has_website": 10, "keyword_match": 10, "title_match": 10, "has_social": 3,
    "rating_ok": 5, "no_email": -15, "third_party_email_only": -10, "pattern_email_only": -5,
    "rating_below_min": -20, "reviews_below_min": -10,
}
VERIFY_RANK = {"valid": 5, "catch_all": 4, "unknown": 3, "risky": 2, "unverified": 1, "invalid": 0}
TYPE_RANK = {"personal": 4, "personal_webmail": 3, "role": 2, "third_party": 0}


def _title_match(title: str, wanted: List[str]) -> bool:
    t = (title or "").lower()
    return any(w.lower() in t for w in wanted if w)


def rank_contact(c: Dict[str, Any], icp: Dict[str, Any]) -> Tuple:
    prefer_personal = icp["contacts"].get("prefer_personal_email", True)
    type_rank = TYPE_RANK.get(c.get("email_type") or "", 1)
    if not prefer_personal and c.get("email_type") == "role":
        type_rank = 4
    vs = c.get("verify_status") or "unverified"
    return (
        1 if c.get("email") else 0,
        0 if c.get("status") == "do_not_contact" else 1,
        -1 if vs == "invalid" else 0,
        1 if vs in ("valid", "catch_all") else 0,
        1 if _title_match(c.get("title") or "", icp["contacts"].get("titles") or []) else 0,
        type_rank,
        0 if c.get("email_source") == "pattern" else 1,
        VERIFY_RANK.get(vs, 1),
        int(c.get("email_confidence") or 0),
    )


def score_company(company: Dict[str, Any], contacts: List[Dict[str, Any]], icp: Dict[str, Any],
                  suppressed_domains: Optional[set] = None) -> Tuple[float, List[str], bool, Optional[int]]:
    """Return (score, reasons, qualified, primary_contact_id)."""
    w = dict(DEFAULT_WEIGHTS)
    w.update(icp["scoring"].get("weights") or {})
    comp = icp["company"]
    reasons: List[str] = []
    disq: List[str] = []
    score = 0.0

    hay = " ".join(str(company.get(k) or "") for k in ("name", "category", "industry", "description", "tags"))
    hit = text_has_any(hay, comp.get("exclude_keywords"))
    if hit:
        disq.append(f"excluded keyword '{hit}'")
    if suppressed_domains and company.get("domain") in suppressed_domains:
        disq.append("domain suppressed")
    if comp.get("require_website") and not company.get("website"):
        disq.append("no website")
    emp = company.get("employees")
    if emp:
        m = re.search(r"\d+", str(emp))
        if m:
            n = int(m.group())
            lo, hi = comp.get("employees_min"), comp.get("employees_max")
            if lo is not None and n < lo:
                disq.append(f"employees {n} < {lo}")
            if hi is not None and n > hi:
                disq.append(f"employees {n} > {hi}")

    kw = text_has_any(hay, comp.get("keywords"))
    if kw:
        score += w["keyword_match"]
        reasons.append(f"+{w['keyword_match']:g} keyword '{kw}'")
    if company.get("website"):
        score += w["has_website"]
        reasons.append(f"+{w['has_website']:g} website")
    if company.get("phone"):
        score += w["has_phone"]
        reasons.append(f"+{w['has_phone']:g} phone")
    if any(company.get(k) for k in ("facebook_url", "instagram_url", "linkedin_url")):
        score += w["has_social"]
        reasons.append(f"+{w['has_social']:g} social")
    rating, reviews = company.get("rating"), company.get("review_count")
    if rating is not None and comp.get("min_rating") is not None:
        if float(rating) < float(comp["min_rating"]):
            score += w["rating_below_min"]
            reasons.append(f"{w['rating_below_min']:g} rating {rating} < {comp['min_rating']}")
        else:
            score += w["rating_ok"]
            reasons.append(f"+{w['rating_ok']:g} rating ok")
    if reviews is not None and comp.get("min_reviews") is not None and int(reviews) < int(comp["min_reviews"]):
        score += w["reviews_below_min"]
        reasons.append(f"{w['reviews_below_min']:g} reviews {reviews} < {comp['min_reviews']}")

    usable = [c for c in contacts if c.get("email") and c.get("verify_status") != "invalid" and c.get("status") != "do_not_contact"
              and not is_offsite_crawl_email(c)]
    if not icp["contacts"].get("accept_role_email", True):
        usable = [c for c in usable if c.get("email_type") != "role"]
    primary_id: Optional[int] = None
    if usable:
        best = max(usable, key=lambda c: rank_contact(c, icp))
        primary_id = int(best["id"])
        score += w["has_email"]
        reasons.append(f"+{w['has_email']:g} email ({best.get('email_type')})")
        if best.get("email_type") in ("personal", "personal_webmail"):
            score += w["personal_email"]
            reasons.append(f"+{w['personal_email']:g} personal email")
        vs = best.get("verify_status")
        if vs == "valid":
            score += w["verified_email"]
            reasons.append(f"+{w['verified_email']:g} verified")
        elif vs == "catch_all":
            score += w["catch_all_email"]
            reasons.append(f"+{w['catch_all_email']:g} catch-all")
        elif vs == "unknown" and "mx_ok" in (best.get("verify_detail") or ""):
            score += w["mx_ok_email"]
            reasons.append(f"+{w['mx_ok_email']:g} mx ok")
        if _title_match(best.get("title") or "", icp["contacts"].get("titles") or []):
            score += w["title_match"]
            reasons.append(f"+{w['title_match']:g} title '{best.get('title')}'")
        if all(c.get("email_type") == "third_party" for c in usable):
            score += w["third_party_email_only"]
            reasons.append(f"{w['third_party_email_only']:g} only third-party email")
        if all(c.get("email_source") == "pattern" for c in usable):
            score += w["pattern_email_only"]
            reasons.append(f"{w['pattern_email_only']:g} only pattern-guessed email")
    else:
        score += w["no_email"]
        reasons.append(f"{w['no_email']:g} no usable email")

    signals = parse_json(company.get("signals"), {})
    for key, pts in (icp["signals"].get("bonus") or {}).items():
        if key.startswith("no_"):
            if company.get("crawl_status") == "ok" and not signals.get(key[3:]):
                score += pts
                reasons.append(f"{pts:+g} {key}")
        elif signals.get(key):
            score += pts
            reasons.append(f"{pts:+g} {key}")

    if disq:
        return score, ["DISQUALIFIED: " + "; ".join(disq)] + reasons, False, primary_id
    qualified = score >= float(icp["scoring"].get("qualify_threshold", 40))
    return score, reasons, qualified, primary_id


def run(conn, icp: Dict[str, Any], only_unscored: bool = False, log=print) -> Dict[str, Any]:
    _emails, sup_domains = db.suppression_sets(conn)
    where = "1=1" if not only_unscored else "score IS NULL"
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM companies WHERE {where}").fetchall()]
    stats = {"scored": 0, "qualified": 0, "disqualified": 0, "below_threshold": 0, "with_primary": 0}
    for c in rows:
        contacts = [dict(k) for k in db.company_contacts(conn, c["id"])]
        score, reasons, qualified, primary = score_company(c, contacts, icp, sup_domains)
        db.update_company(conn, c["id"], score=round(score, 1), score_reasons="; ".join(reasons), qualified=1 if qualified else 0)
        conn.execute("UPDATE contacts SET is_primary = 0 WHERE company_id = ?", (c["id"],))
        if primary:
            conn.execute("UPDATE contacts SET is_primary = 1 WHERE id = ?", (primary,))
            stats["with_primary"] += 1
        stats["scored"] += 1
        if qualified:
            stats["qualified"] += 1
        elif reasons and reasons[0].startswith("DISQUALIFIED"):
            stats["disqualified"] += 1
        else:
            stats["below_threshold"] += 1
    conn.commit()
    return stats


def explain(icp: Dict[str, Any]) -> str:
    w = dict(DEFAULT_WEIGHTS)
    w.update(icp["scoring"].get("weights") or {})
    lines = ["Scoring weights (override in icp.json scoring.weights):"]
    for k, v in w.items():
        lines.append(f"  {k:<24} {v:+g}")
    lines.append(f"Signal bonuses: {json.dumps(icp['signals'].get('bonus') or {})}")
    lines.append(f"Qualify threshold: {icp['scoring'].get('qualify_threshold')}")
    lines.append("Disqualifiers: exclude_keywords match, suppressed domain, require_website without site, employees outside range.")
    return "\n".join(lines)
