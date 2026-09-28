"""Instantly.ai API v2: add leads to a campaign or lead list. Verified against api.instantly.ai/openapi/api_v2.json."""
import json
import re
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..util import http_json, HttpError, parse_json, now_iso

BASE = "https://api.instantly.ai/api/v2"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class Instantly:
    def __init__(self, api_key: str):
        self.h = {"Authorization": f"Bearer {api_key}"}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return http_json("GET", BASE + path, self.h, params=params, timeout=40)

    def _post(self, path: str, body: Dict[str, Any]) -> Any:
        return http_json("POST", BASE + path, self.h, body, timeout=90)

    def list_campaigns(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        after = None
        while True:
            data = self._get("/campaigns", {"limit": 100, "search": search, "starting_after": after})
            items.extend(data.get("items") or [])
            after = data.get("next_starting_after")
            if not after:
                return items

    def list_lead_lists(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._get("/lead-lists", {"limit": 100, "search": search})
        return data.get("items") or []

    def create_lead_list(self, name: str) -> Dict[str, Any]:
        return self._post("/lead-lists", {"name": name})

    def add_leads(self, leads: List[Dict[str, Any]], campaign_id: Optional[str] = None, list_id: Optional[str] = None,
                  skip_if_in_workspace: bool = True, skip_if_in_campaign: bool = False,
                  verify_leads_on_import: bool = False) -> Dict[str, Any]:
        body: Dict[str, Any] = {"leads": leads, "skip_if_in_workspace": skip_if_in_workspace,
                                "skip_if_in_campaign": skip_if_in_campaign, "verify_leads_on_import": verify_leads_on_import}
        if campaign_id:
            body["campaign_id"] = campaign_id
        elif list_id:
            body["list_id"] = list_id
        else:
            raise ValueError("campaign_id or list_id required")
        return self._post("/leads/add", body)

    def resolve_campaign(self, ref: str) -> Dict[str, Any]:
        if _UUID.match(ref):
            return {"id": ref, "name": ref}
        hits = [c for c in self.list_campaigns(ref) if (c.get("name") or "").strip().lower() == ref.strip().lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            names = [c.get("name") for c in self.list_campaigns()][:30]
            raise SystemExit(f"No Instantly campaign named '{ref}'. Campaigns: {names}")
        raise SystemExit(f"{len(hits)} campaigns named '{ref}'; pass the campaign id instead.")

    def resolve_or_create_list(self, name: str) -> Dict[str, Any]:
        if _UUID.match(name):
            return {"id": name, "name": name}
        for lst in self.list_lead_lists(name):
            if (lst.get("name") or "").strip().lower() == name.strip().lower():
                return lst
        return self.create_lead_list(name)


CUSTOM_KEYS = ["city", "state", "country", "category", "domain", "rating", "review_count", "verify_status",
               "email_type", "score", "signals", "source", "lead_id", "google_maps_url", "description"]


def build_lead(r: Dict[str, Any]) -> Dict[str, Any]:
    custom = {}
    for k in CUSTOM_KEYS:
        v = r.get(k)
        if v not in (None, ""):
            custom[k] = v if isinstance(v, (int, float, bool)) else str(v)[:500]
    lead: Dict[str, Any] = {"email": r["email"], "company_name": r["company_name"], "website": r["website"] or None,
                            "phone": r["contact_phone"] or r["company_phone"] or None, "custom_variables": custom}
    if r.get("first_name"):
        lead["first_name"] = r["first_name"]
    if r.get("last_name"):
        lead["last_name"] = r["last_name"]
    if r.get("title"):
        lead["job_title"] = r["title"]
    return {k: v for k, v in lead.items() if v is not None}


def push(conn, api_key: str, rows: List[Dict[str, Any]], campaign: Optional[str] = None, list_name: Optional[str] = None,
         yes: bool = False, batch_size: int = 100, verify_on_import: bool = False, skip_if_in_workspace: bool = True,
         log=print) -> Dict[str, Any]:
    rows = [r for r in rows if r.get("email")]
    stats: Dict[str, Any] = {"target": None, "rows": len(rows), "batches": 0, "uploaded": 0, "skipped": 0,
                             "duplicates": 0, "invalid": 0, "in_blocklist": 0, "dry_run": not yes}
    if not rows:
        log("  nothing to push (no rows with email)")
        return stats
    api = Instantly(api_key)
    target: Dict[str, Any] = {}
    if campaign:
        target = api.resolve_campaign(campaign)
        stats["target"] = f"campaign '{target.get('name')}' ({target['id']})"
        status = target.get("status")
        if status == 1:
            log("  NOTE: this campaign is ACTIVE. Leads added to it can start receiving emails immediately.")
    elif list_name:
        if yes:
            target = api.resolve_or_create_list(list_name)
        else:
            target = {"id": "found or created on the live run", "name": list_name}
        stats["target"] = f"lead list '{target.get('name')}' ({target['id']})"
    else:
        raise SystemExit("Give --campaign <name|id> or --list <name>.")
    log(f"  Instantly target: {stats['target']}")
    log(f"  {len(rows)} leads in batches of {batch_size}; skip_if_in_workspace={skip_if_in_workspace}; verify_on_import={verify_on_import}")
    sample = [build_lead(r) for r in rows[:2]]
    log("  sample payload: " + json.dumps(sample, indent=None)[:600])
    if not yes:
        log("  DRY RUN. Re-run with --yes to push.")
        return stats
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            res = api.add_leads([build_lead(r) for r in batch],
                                campaign_id=target["id"] if campaign else None,
                                list_id=target["id"] if list_name else None,
                                skip_if_in_workspace=skip_if_in_workspace, verify_leads_on_import=verify_on_import)
        except HttpError as e:
            if e.status in (401, 403):
                raise SystemExit("Instantly rejected INSTANTLY_API_KEY (needs leads:create / campaigns:read scopes).")
            log(f"  ! batch {i // batch_size + 1} failed: HTTP {e.status} {e.body[:200]}")
            continue
        stats["batches"] += 1
        db.log_usage(conn, "instantly", "leads/add", len(batch))
        stats["uploaded"] += int(res.get("leads_uploaded") or 0)
        stats["skipped"] += int(res.get("skipped_count") or 0)
        stats["duplicates"] += int(res.get("duplicated_leads") or 0) + int(res.get("duplicate_email_count") or 0)
        stats["invalid"] += int(res.get("invalid_email_count") or 0)
        stats["in_blocklist"] += int(res.get("in_blocklist") or 0)
        created_emails = {(c.get("email") or "").lower() for c in (res.get("created_leads") or []) if isinstance(c, dict)}
        for r in batch:
            if r.get("contact_id"):
                row = conn.execute("SELECT pushed FROM contacts WHERE id = ?", (r["contact_id"],)).fetchone()
                pushed = parse_json(row["pushed"] if row else "{}", {})
                pushed["instantly"] = {"target": target["id"], "at": now_iso(),
                                       "result": "uploaded" if (not created_emails or r["email"].lower() in created_emails) else "skipped"}
                db.update_contact(conn, r["contact_id"], pushed=json.dumps(pushed), status="pushed")
        conn.commit()
        log(f"    batch {i // batch_size + 1}: uploaded {res.get('leads_uploaded')} skipped {res.get('skipped_count')} "
            f"dup {res.get('duplicated_leads')} invalid {res.get('invalid_email_count')} blocklist {res.get('in_blocklist')}")
        time.sleep(0.5)
    return stats
