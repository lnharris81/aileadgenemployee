"""Apollo people search by company domain + title, then people/match to reveal emails (1 credit each)."""
import json
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..util import http_json, HttpError, clean_email, classify_email, parse_json
from ..sources.apollo import BASE, headers


def people_search(api_key: str, domains: List[str], titles: List[str], seniorities: List[str],
                  page: int = 1, per_page: int = 25) -> Dict[str, Any]:
    body: Dict[str, Any] = {"q_organization_domains_list": domains, "page": page, "per_page": per_page}
    if titles:
        body["person_titles"] = titles
        body["include_similar_titles"] = True
    if seniorities:
        body["person_seniorities"] = seniorities
    return http_json("POST", f"{BASE}/mixed_people/api_search", headers(api_key), body, timeout=60)


def people_match(api_key: str, person_id: str) -> Dict[str, Any]:
    body = {"id": person_id, "reveal_personal_emails": False, "reveal_phone_number": False}
    return http_json("POST", f"{BASE}/people/match", headers(api_key), body, timeout=60)


def run(conn, icp: Dict[str, Any], api_key: str, max_credits: int = 50, per_company: int = 2,
        titles: Optional[List[str]] = None, seniorities: Optional[List[str]] = None, only_qualified: bool = True,
        batch_domains: int = 20, dry_run: bool = False, log=print) -> Dict[str, Any]:
    titles = titles if titles is not None else icp["contacts"].get("titles") or []
    seniorities = seniorities if seniorities is not None else icp["contacts"].get("seniorities") or []
    where = "domain IS NOT NULL AND domain != '' AND contact_providers NOT LIKE '%\"apollo\"%'"
    if only_qualified:
        where += " AND qualified = 1"
    rows = [dict(r) for r in conn.execute(
        f"SELECT id, name, domain, contact_providers FROM companies WHERE {where} ORDER BY COALESCE(score,0) DESC, id").fetchall()]
    stats = {"eligible": len(rows), "search_requests": 0, "people_found": 0, "credits_used": 0,
             "emails": 0, "new_contacts": 0}
    log(f"  Apollo people: {len(rows)} companies, titles={titles[:4]}..., cap {max_credits} credits, {per_company}/company")
    if dry_run:
        return stats
    by_domain = {r["domain"].lower(): r for r in rows}
    domains = list(by_domain)
    for i in range(0, len(domains), batch_domains):
        if stats["credits_used"] >= max_credits:
            break
        batch = domains[i:i + batch_domains]
        try:
            data = people_search(api_key, batch, titles, seniorities, 1, min(100, per_company * len(batch)))
        except HttpError as e:
            if e.status in (401, 403):
                raise SystemExit("Apollo rejected the key or plan lacks people search. " + e.body[:200])
            log(f"  ! people search error {e.status}: {e.body[:150]}")
            continue
        stats["search_requests"] += 1
        db.log_usage(conn, "apollo", "mixed_people/api_search", 1)
        per_dom: Dict[str, int] = {}
        capped = False
        for p in data.get("people") or []:
            org = p.get("organization") or {}
            dom = (org.get("primary_domain") or "").lower()
            comp = by_domain.get(dom)
            if not comp:
                continue
            if per_dom.get(dom, 0) >= per_company:
                continue
            if stats["credits_used"] >= max_credits:
                capped = True
                break
            stats["people_found"] += 1
            try:
                m = people_match(api_key, p["id"])
            except HttpError as e:
                log(f"  ! match error {e.status} for {p.get('id')}")
                continue
            person = m.get("person") or {}
            email = clean_email(person.get("email"))
            if email:
                stats["credits_used"] += 1
                db.log_usage(conn, "apollo", "people/match", 1)
            per_dom[dom] = per_dom.get(dom, 0) + 1
            es = person.get("email_status") or ""
            _cid, created = db.upsert_contact(conn, comp["id"], {
                "email": email or None, "email_type": classify_email(email, dom) if email else None,
                "email_source": "apollo" if email else None,
                "email_confidence": (95 if es == "verified" else 60) if email else None,
                "first_name": person.get("first_name") or p.get("first_name"),
                "last_name": person.get("last_name"), "title": person.get("title") or p.get("title"),
                "seniority": person.get("seniority"), "linkedin_url": person.get("linkedin_url"),
                "verify_status": "valid" if es == "verified" else ("unverified" if email else "unverified"),
                "verify_provider": "apollo" if es == "verified" else None,
                "source_ref": f"apollo:person/{p.get('id')}",
            })
            if email:
                stats["emails"] += 1
            if created:
                stats["new_contacts"] += 1
            time.sleep(0.3)
        # The credit cap can stop a batch halfway: only mark companies that were actually worked, so the rest get a turn next run.
        for dom in (list(per_dom) if capped else batch):
            comp = by_domain[dom]
            provs = parse_json(comp["contact_providers"], [])
            provs.append("apollo")
            db.update_company(conn, comp["id"], contact_providers=json.dumps(provs))
        conn.commit()
        log(f"    batch {i // batch_domains + 1}: {stats['emails']} emails, {stats['credits_used']} credits")
    return stats
