"""CSV exports: one flat row per lead (contact + company). Formats for generic, Instantly, GHL, Smartlead, lemlist."""
import csv
import json
import os
import time
from typing import Any, Dict, List, Optional

from . import db
from .util import email_domain, is_offsite_crawl_email, parse_json

GENERIC_COLUMNS = [
    "lead_id", "company_id", "contact_id", "company_name", "website", "domain", "email", "email_type", "email_source",
    "email_confidence", "verify_status", "verify_detail", "first_name", "last_name", "full_name", "title", "seniority",
    "contact_phone", "company_phone", "address", "city", "state", "postal_code", "country", "category", "industry",
    "employees", "rating", "review_count", "linkedin_url", "facebook_url", "instagram_url", "google_maps_url",
    "description", "score", "score_reasons", "signals", "source", "source_ref", "tags", "campaign", "is_primary",
]


def _signals_summary(sig: Dict[str, Any]) -> str:
    keys = [k for k, v in sig.items() if v is True and k not in ("https", "mobile_viewport", "has_form", "email_on_site")]
    return ",".join(sorted(keys))


def build_rows(conn, icp: Dict[str, Any], only_qualified: bool = True, min_score: Optional[float] = None,
               one_per_company: bool = True, verified_only: bool = False, include_unverified: bool = True,
               include_no_email: bool = False, sources: Optional[List[str]] = None,
               limit: Optional[int] = None, exclude_pushed: Optional[str] = None) -> List[Dict[str, Any]]:
    sup_emails, sup_domains = db.suppression_sets(conn)
    where = ["1=1"]
    params: List[Any] = []
    if only_qualified:
        where.append("co.qualified = 1")
    if min_score is not None:
        where.append("co.score >= ?")
        params.append(min_score)
    if sources:
        where.append("(" + " OR ".join("co.sources LIKE ?" for _ in sources) + ")")
        params.extend(f'%"{s}"%' for s in sources)
    sql = f"SELECT * FROM companies co WHERE {' AND '.join(where)} ORDER BY co.score DESC, co.id"
    companies = [dict(r) for r in conn.execute(sql, params).fetchall()]
    rows: List[Dict[str, Any]] = []
    campaign = icp.get("campaign") or "default"
    accept_role = icp["contacts"].get("accept_role_email", True)
    for co in companies:
        if co.get("domain") in sup_domains:
            continue
        contacts = [dict(k) for k in db.company_contacts(conn, co["id"])]
        usable = []
        for k in contacts:
            if k.get("status") == "do_not_contact":
                continue
            if k.get("email"):
                if (k["email"].lower() in sup_emails or email_domain(k["email"]) in sup_domains
                        or k.get("verify_status") == "invalid" or is_offsite_crawl_email(k)
                        or (not accept_role and k.get("email_type") == "role")):
                    continue
                if verified_only and k.get("verify_status") not in ("valid", "catch_all"):
                    continue
                if not include_unverified and k.get("verify_status") in ("unverified",):
                    continue
                if exclude_pushed and exclude_pushed in parse_json(k.get("pushed"), {}):
                    continue
            elif not include_no_email:
                continue
            usable.append(k)
        if not usable:
            if include_no_email and not contacts:
                usable = [{}]
            else:
                continue
        if one_per_company:
            prim = [k for k in usable if k.get("is_primary")]
            usable = prim[:1] if prim else usable[:1]
        sig = parse_json(co.get("signals"), {})
        for k in usable:
            rows.append({
                "lead_id": f"{co['id']}-{k.get('id', 0)}", "company_id": co["id"], "contact_id": k.get("id"),
                "company_name": co["name"], "website": co.get("website") or "", "domain": co.get("domain") or "",
                "email": k.get("email") or "", "email_type": k.get("email_type") or "", "email_source": k.get("email_source") or "",
                "email_confidence": k.get("email_confidence") if k.get("email_confidence") is not None else "",
                "verify_status": k.get("verify_status") or "", "verify_detail": k.get("verify_detail") or "",
                "first_name": k.get("first_name") or "", "last_name": k.get("last_name") or "",
                "full_name": " ".join(x for x in [k.get("first_name"), k.get("last_name")] if x),
                "title": k.get("title") or "", "seniority": k.get("seniority") or "",
                "contact_phone": k.get("phone") or "", "company_phone": co.get("phone") or "",
                "address": co.get("address") or "", "city": co.get("city") or "", "state": co.get("state") or "",
                "postal_code": co.get("postal_code") or "", "country": co.get("country") or "",
                "category": co.get("category") or "", "industry": co.get("industry") or "", "employees": co.get("employees") or "",
                "rating": co.get("rating") if co.get("rating") is not None else "",
                "review_count": co.get("review_count") if co.get("review_count") is not None else "",
                "linkedin_url": k.get("linkedin_url") or co.get("linkedin_url") or "",
                "facebook_url": co.get("facebook_url") or "", "instagram_url": co.get("instagram_url") or "",
                "google_maps_url": co.get("google_maps_url") or "", "description": (co.get("description") or "")[:300],
                "score": co.get("score") if co.get("score") is not None else "", "score_reasons": co.get("score_reasons") or "",
                "signals": _signals_summary(sig), "source": co.get("source") or "", "source_ref": co.get("source_ref") or "",
                "tags": co.get("tags") or "", "campaign": campaign, "is_primary": 1 if k.get("is_primary") else 0,
            })
            if limit and len(rows) >= limit:
                return rows
    return rows


def _first_or_company(r: Dict[str, Any]) -> str:
    return r["first_name"] or ""


FORMATS = {
    "generic": lambda r: {c: r.get(c, "") for c in GENERIC_COLUMNS},
    "instantly": lambda r: {
        "email": r["email"], "first_name": r["first_name"], "last_name": r["last_name"],
        "company_name": r["company_name"], "website": r["website"], "phone": r["contact_phone"] or r["company_phone"],
        "job_title": r["title"], "city": r["city"], "state": r["state"], "country": r["country"],
        "category": r["category"], "rating": r["rating"], "review_count": r["review_count"], "domain": r["domain"],
        "email_type": r["email_type"], "verify_status": r["verify_status"], "score": r["score"],
        "signals": r["signals"], "source": r["source"], "lead_id": r["lead_id"],
    },
    "ghl": lambda r: {
        "First Name": r["first_name"], "Last Name": r["last_name"], "Email": r["email"],
        "Phone": r["contact_phone"] or r["company_phone"], "Company Name": r["company_name"], "Website": r["website"],
        "Address": r["address"], "City": r["city"], "State": r["state"], "Postal Code": r["postal_code"],
        "Country": r["country"], "Tags": ",".join(t for t in ["lead-gen-employee", r["campaign"], r["category"]] if t),
        "Source": "Lead Gen Employee", "Notes": f"score {r['score']}; {r['score_reasons']}"[:500],
    },
    "smartlead": lambda r: {
        "first_name": r["first_name"], "last_name": r["last_name"], "email": r["email"],
        "phone_number": r["contact_phone"] or r["company_phone"], "company_name": r["company_name"],
        "website": r["website"], "location": ", ".join(x for x in [r["city"], r["state"]] if x),
        "linkedin_profile": r["linkedin_url"], "category": r["category"], "score": r["score"], "lead_id": r["lead_id"],
    },
    "lemlist": lambda r: {
        "email": r["email"], "firstName": r["first_name"], "lastName": r["last_name"],
        "companyName": r["company_name"], "companyDomain": r["domain"], "phone": r["contact_phone"] or r["company_phone"],
        "linkedinUrl": r["linkedin_url"], "city": r["city"], "category": r["category"], "score": r["score"],
    },
}


def write_csv(rows: List[Dict[str, Any]], fmt: str, out_path: str) -> str:
    conv = FORMATS[fmt]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        first = conv(rows[0] if rows else dict.fromkeys(GENERIC_COLUMNS, ""))  # an empty list still gets its header row
        if not rows:
            csv.DictWriter(fh, fieldnames=list(first.keys())).writeheader()
            return out_path
        w = csv.DictWriter(fh, fieldnames=list(first.keys()))
        w.writeheader()
        for r in rows:
            w.writerow(conv(r))
    return out_path


def default_path(export_dir: str, campaign: str, fmt: str) -> str:
    return os.path.join(export_dir, f"{campaign}_{fmt}_{time.strftime('%Y%m%d-%H%M')}.csv")


def summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    from collections import Counter
    s: Dict[str, Any] = {"rows": len(rows), "companies": len({r["company_id"] for r in rows})}
    s["with_email"] = sum(1 for r in rows if r["email"])
    s["email_type"] = dict(Counter(r["email_type"] for r in rows if r["email"]))
    s["verify_status"] = dict(Counter(r["verify_status"] for r in rows if r["email"]))
    s["with_name"] = sum(1 for r in rows if r["first_name"])
    s["with_phone"] = sum(1 for r in rows if r["contact_phone"] or r["company_phone"])
    s["sources"] = dict(Counter(r["source"] for r in rows))
    s["dup_emails"] = len([e for e, n in Counter(r["email"] for r in rows if r["email"]).items() if n > 1])
    return s
