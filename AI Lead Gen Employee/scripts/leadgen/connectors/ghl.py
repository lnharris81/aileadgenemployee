"""GoHighLevel (LeadConnector) API v2: upsert contacts into a sub-account. Private Integration token auth."""
import json
import os
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..util import http_json, HttpError, parse_json, now_iso, RateLimiter

BASE = "https://services.leadconnectorhq.com"


def headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Version": os.environ.get("GHL_API_VERSION", "2021-07-28"),
            "Content-Type": "application/json", "Accept": "application/json"}


def build_contact(r: Dict[str, Any], location_id: str, tags: List[str], source: str = "Lead Gen Employee") -> Dict[str, Any]:
    body: Dict[str, Any] = {"locationId": location_id, "source": source,
                            "tags": [t for t in tags if t]}
    if r.get("first_name"):
        body["firstName"] = r["first_name"]
    if r.get("last_name"):
        body["lastName"] = r["last_name"]
    if not r.get("first_name") and not r.get("last_name"):
        body["name"] = r["company_name"]
    if r.get("email"):
        body["email"] = r["email"]
    phone = r.get("contact_phone") or r.get("company_phone")
    if phone:
        body["phone"] = phone
    if r.get("company_name"):
        body["companyName"] = r["company_name"]
    if r.get("website"):
        body["website"] = r["website"]
    for src, dst in (("address", "address1"), ("city", "city"), ("state", "state"), ("postal_code", "postalCode")):
        if r.get(src):
            body[dst] = r[src]
    if r.get("country") and len(r["country"]) == 2:
        body["country"] = r["country"].upper()
    return body


def row_tags(r: Dict[str, Any], tags: List[str]) -> List[str]:
    """The user's tags plus the row's campaign and category, the same list for the preview and the live push."""
    return tags + [t for t in [r.get("campaign"), r.get("category")] if t and t not in tags]


def upsert(token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    return http_json("POST", f"{BASE}/contacts/upsert", headers(token), body, timeout=40)


def push(conn, token: str, location_id: str, rows: List[Dict[str, Any]], tags: Optional[List[str]] = None,
         yes: bool = False, source: str = "Lead Gen Employee", require_email: bool = True, log=print) -> Dict[str, Any]:
    if require_email:
        rows = [r for r in rows if r.get("email")]
    stats: Dict[str, Any] = {"rows": len(rows), "created": 0, "updated": 0, "failed": 0, "dry_run": not yes}
    tags = tags or []
    log(f"  GHL target: location {location_id}; {len(rows)} contacts; tags {tags}")
    if not rows:
        return stats
    for r in rows[:2]:
        log("  sample payload: " + json.dumps(build_contact(r, location_id, row_tags(r, tags), source))[:500])
    if not yes:
        log("  DRY RUN. Re-run with --yes to push.")
        return stats
    limiter = RateLimiter(8)  # GHL burst limit is 100 requests / 10 s
    for i, r in enumerate(rows, 1):
        limiter.wait()
        body = build_contact(r, location_id, row_tags(r, tags), source)
        try:
            res = upsert(token, body)
        except HttpError as e:
            if e.status in (401, 403):
                raise SystemExit("GHL rejected GHL_API_KEY. Use a Private Integration token with contacts.write scope.")
            if e.status == 422:
                log(f"  ! {r.get('email')}: rejected {e.body[:160]}")
                stats["failed"] += 1
                continue
            log(f"  ! {r.get('email')}: HTTP {e.status} {e.body[:120]}")
            stats["failed"] += 1
            continue
        db.log_usage(conn, "ghl", "contacts/upsert", 1)
        contact = res.get("contact") or {}
        stats["created" if res.get("new") else "updated"] += 1
        if r.get("contact_id"):
            row = conn.execute("SELECT pushed FROM contacts WHERE id = ?", (r["contact_id"],)).fetchone()
            pushed = parse_json(row["pushed"] if row else "{}", {})
            pushed["ghl"] = {"contact_id": contact.get("id"), "location": location_id, "at": now_iso(),
                             "result": "created" if res.get("new") else "updated"}
            db.update_contact(conn, r["contact_id"], pushed=json.dumps(pushed), status="pushed")
        if i % 25 == 0 or i == len(rows):
            conn.commit()
            log(f"    {i}/{len(rows)} | created {stats['created']} updated {stats['updated']} failed {stats['failed']}")
    conn.commit()
    return stats
