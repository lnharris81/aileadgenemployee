"""Apollo.io organization search. Needs a paid Apollo plan for search endpoints. 1 credit per page."""
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..util import http_json, HttpError
from . import base_record

BASE = "https://api.apollo.io/api/v1"


def headers(api_key: str) -> Dict[str, str]:
    return {"x-api-key": api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"}


def org_search(api_key: str, keywords: List[str], locations: List[str], employee_ranges: List[str],
               page: int = 1, per_page: int = 100, name: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"page": page, "per_page": per_page}
    if keywords:
        body["q_organization_keyword_tags"] = keywords
    if locations:
        body["organization_locations"] = locations
    if employee_ranges:
        body["organization_num_employees_ranges"] = employee_ranges
    if name:
        body["q_organization_name"] = name
    return http_json("POST", f"{BASE}/mixed_companies/search", headers(api_key), body, timeout=60)


def org_to_record(o: Dict[str, Any], country: str) -> Optional[Dict[str, Any]]:
    name = o.get("name")
    if not name:
        return None
    phone = ((o.get("primary_phone") or {}).get("number")) or o.get("phone") or ""
    emp = o.get("estimated_num_employees")
    return base_record(
        name, o.get("website_url") or o.get("primary_domain") or "", phone, o.get("country") or country,
        city=o.get("city"), state=o.get("state"), postal_code=o.get("postal_code"),
        address=o.get("street_address"), industry=o.get("industry"),
        employees=str(emp) if emp else None, description=(o.get("short_description") or "")[:500] or None,
        linkedin_url=o.get("linkedin_url"), facebook_url=o.get("facebook_url"), twitter_url=o.get("twitter_url"),
        category=o.get("industry"), source_ref=f"apollo:org/{o.get('id')}",
    )


def run(conn, icp: Dict[str, Any], api_key: str, keywords: List[str], locations: List[str],
        employee_ranges: List[str], pages: int = 1, per_page: int = 100, start_page: int = 1,
        limit: Optional[int] = None, dry_run: bool = False, log=print) -> Dict[str, Any]:
    country = icp["geography"].get("country") or "US"
    stats = {"pages": 0, "organizations": 0, "created": 0, "merged": 0, "total_available": None}
    log(f"  Apollo org search: keywords={keywords} locations={locations} sizes={employee_ranges} pages {start_page}-{start_page + pages - 1}")
    if dry_run:
        return stats
    for page in range(start_page, start_page + pages):
        try:
            data = org_search(api_key, keywords, locations, employee_ranges, page, per_page)
        except HttpError as e:
            if e.status in (401, 403):
                raise SystemExit("Apollo rejected the key or plan does not include search. " + e.body[:200])
            if e.status == 422:
                raise SystemExit("Apollo rejected the filters: " + e.body[:300])
            raise
        stats["pages"] += 1
        db.log_usage(conn, "apollo", "mixed_companies/search", 1)
        orgs = data.get("organizations") or data.get("accounts") or []
        pag = data.get("pagination") or {}
        stats["total_available"] = pag.get("total_entries")
        stats["organizations"] += len(orgs)
        for o in orgs:
            rec = org_to_record(o, country)
            if not rec:
                continue
            _cid, created = db.upsert_company(conn, rec, "apollo")
            stats["created" if created else "merged"] += 1
            if limit and stats["created"] >= limit:
                conn.commit()
                return stats
        conn.commit()
        log(f"    page {page}: {len(orgs)} orgs, {stats['created']} new (total available {pag.get('total_entries')})")
        if not orgs or (pag.get("total_pages") and page >= int(pag["total_pages"])):
            break
        time.sleep(0.5)
    return stats
