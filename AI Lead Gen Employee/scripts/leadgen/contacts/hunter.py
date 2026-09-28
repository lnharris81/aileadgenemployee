"""Hunter.io domain search: named contacts, titles, and the company's email pattern. 1 request per domain."""
import json
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..util import http_json, HttpError, clean_email, classify_email, is_site_builder_domain, parse_json

BASE = "https://api.hunter.io/v2"


def domain_search(api_key: str, domain: str, limit: int = 10, seniority: Optional[str] = None,
                  department: Optional[str] = None, email_type: Optional[str] = None) -> Dict[str, Any]:
    params = {"domain": domain, "limit": limit, "api_key": api_key, "seniority": seniority,
              "department": department, "type": email_type}
    return http_json("GET", f"{BASE}/domain-search", params=params, timeout=30)


def run(conn, icp: Dict[str, Any], api_key: str, max_requests: int = 50, limit_per_domain: int = 10,
        seniority: Optional[str] = None, department: Optional[str] = None, only_qualified: bool = False,
        dry_run: bool = False, log=print) -> Dict[str, Any]:
    where = "domain IS NOT NULL AND domain != '' AND contact_providers NOT LIKE '%\"hunter\"%'"
    if only_qualified:
        where += " AND qualified = 1"
    rows = [dict(r) for r in conn.execute(
        f"SELECT id, name, domain, contact_providers FROM companies WHERE {where} ORDER BY COALESCE(score, 0) DESC, id").fetchall()]
    rows = [r for r in rows if not is_site_builder_domain(r["domain"])]
    stats = {"eligible": len(rows), "requests": 0, "contacts": 0, "new_contacts": 0, "patterns": 0, "no_results": 0}
    log(f"  Hunter domain search: {len(rows)} companies eligible, cap {max_requests} requests")
    if dry_run:
        return stats
    for r in rows:
        if stats["requests"] >= max_requests:
            log(f"  hit --max-requests {max_requests}")
            break
        try:
            data = domain_search(api_key, r["domain"], limit_per_domain, seniority, department)
        except HttpError as e:
            if e.status == 401:
                raise SystemExit("Hunter rejected HUNTER_API_KEY.")
            if e.status == 429:
                log("  Hunter rate limit / quota reached; stopping.")
                break
            log(f"  ! {r['domain']}: HTTP {e.status}")
            continue
        stats["requests"] += 1
        db.log_usage(conn, "hunter", "domain-search", 1)
        d = data.get("data") or {}
        fields: Dict[str, Any] = {}
        provs = parse_json(r["contact_providers"], [])
        provs.append("hunter")
        fields["contact_providers"] = json.dumps(provs)
        if d.get("pattern"):
            fields["email_pattern"] = d["pattern"]
            stats["patterns"] += 1
        if d.get("organization") and not r.get("name"):
            fields["name"] = d["organization"]
        db.update_company(conn, r["id"], **fields)
        emails = d.get("emails") or []
        if not emails:
            stats["no_results"] += 1
        for e in emails:
            email = clean_email(e.get("value"))
            if not email:
                continue
            ver = (e.get("verification") or {}).get("status")
            vstatus = {"valid": "valid", "accept_all": "catch_all", "invalid": "invalid"}.get(ver or "", "unverified")
            _cid, created = db.upsert_contact(conn, r["id"], {
                "email": email, "email_type": classify_email(email, r["domain"]) if e.get("type") != "generic" else "role",
                "email_source": "hunter", "email_confidence": int(e.get("confidence") or 50),
                "first_name": e.get("first_name"), "last_name": e.get("last_name"), "title": e.get("position"),
                "seniority": e.get("seniority"), "department": e.get("department"), "linkedin_url": e.get("linkedin"),
                "phone": e.get("phone_number"),
                "verify_status": vstatus, "verify_provider": "hunter" if vstatus != "unverified" else None,
                "verify_at": (e.get("verification") or {}).get("date"),
                "source_ref": ((e.get("sources") or [{}])[0].get("uri") or f"hunter:{r['domain']}")[:300],
            })
            stats["contacts"] += 1
            if created:
                stats["new_contacts"] += 1
        conn.commit()
        time.sleep(0.25)
    return stats
