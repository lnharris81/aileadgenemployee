"""Self-contained interactive HTML report: overview, lead explorer with a detail drawer, map, and insights.

Python collects the numbers and one compact record per company; report_assets/report.css and report.js are
inlined so the output is a single file that works offline. Standard library only.
"""
import html
import json
import math
import os
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from . import db
from .score import DEFAULT_WEIGHTS, VERIFY_RANK
from .util import email_domain, is_offsite_crawl_email, parse_json

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_assets")
UPPER_WORDS = {"uk", "us", "usa", "ai", "b2b", "b2c", "dtc", "hvac", "seo", "ppc", "crm", "saas", "nyc", "la", "sf"}


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _asset(name: str) -> str:
    with open(os.path.join(ASSET_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values so the embedded JSON stays small on big campaigns."""
    return {k: v for k, v in d.items() if v is not None and v != "" and v != [] and v != {}}


def pretty_title(slug: str) -> str:
    words = [w for w in re.split(r"[-_\s]+", slug or "") if w]
    return " ".join(w.upper() if w.lower() in UPPER_WORDS else w[:1].upper() + w[1:] for w in words) or "Lead report"


def _int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError, OverflowError):
        return 0


def _num(v: Any) -> Optional[float]:
    """A number the way score.py reads it (a numeric string counts), or None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return (int(f) if f.is_integer() else f) if math.isfinite(f) else None


def _finite(v: Any) -> Any:
    """JSON has no Infinity or NaN; one such value would stop the page from loading."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


def _blocked(k: Dict[str, Any], domain: Optional[str], sup_emails: set, sup_domains: set, accept_role: bool = True) -> str:
    """Why this contact can never be exported or pushed (empty when it can). Mirrors export.build_rows."""
    if k.get("status") == "do_not_contact":
        return "do not contact"
    if (domain and domain in sup_domains) or (k.get("email") and email_domain(k["email"]) in sup_domains):
        return "domain suppressed"
    if k.get("email") and k["email"].lower() in sup_emails:
        return "suppressed"
    if k.get("verify_status") == "invalid":
        return "invalid"
    if is_offsite_crawl_email(k):
        return "third-party address"
    if not accept_role and k.get("email_type") == "role":
        return "role inbox (your profile excludes these)"
    return ""


def _lead(c: Dict[str, Any], contacts: List[Dict[str, Any]], ready: bool, has_email: bool,
          sup_emails: set, sup_domains: set, accept_role: bool = True) -> Dict[str, Any]:
    sig = parse_json(c.get("signals"), {})
    cms = sig.get("cms") if isinstance(sig.get("cms"), str) else None
    year = sig.get("copyright_year") if isinstance(sig.get("copyright_year"), int) else None
    reasons = [r.strip() for r in (c.get("score_reasons") or "").split(";") if r.strip()]
    disq = reasons[0][len("DISQUALIFIED:"):].strip() if reasons and reasons[0].startswith("DISQUALIFIED") else ""
    people = []
    for k in contacts:
        if not (k.get("email") or k.get("first_name") or k.get("last_name")):
            continue
        people.append(_compact({
            "name": " ".join(x for x in (k.get("first_name"), k.get("last_name")) if x),
            "title": k.get("title"), "email": k.get("email"), "type": k.get("email_type"), "via": k.get("email_source"),
            "conf": k.get("email_confidence"), "verify": k.get("verify_status") if k.get("email") else None,
            "detail": k.get("verify_detail"), "phone": k.get("phone"), "linkedin": k.get("linkedin_url"),
            "primary": 1 if k.get("is_primary") else 0, "pushed": 1 if k.get("status") == "pushed" else 0,
            "blocked": _blocked(k, c.get("domain"), sup_emails, sup_domains, accept_role),
        }))
    people.sort(key=lambda p: (-p.get("primary", 0), 1 if p.get("blocked") else 0, 0 if p.get("email") else 1))
    live = [p for p in people if p.get("email") and not p.get("blocked")]
    best_verify = max((p.get("verify") or "unverified" for p in live), key=lambda v: VERIFY_RANK.get(v, 1), default="")
    socials = _compact({k: c.get(f"{k}_url") for k in ("linkedin", "facebook", "instagram", "twitter", "youtube", "tiktok", "yelp")})
    return _compact({
        "id": c["id"], "name": c.get("name") or c.get("domain") or "Unnamed company", "category": c.get("category"), "industry": c.get("industry"),
        "city": c.get("city"), "state": c.get("state"), "address": c.get("address"), "postal": c.get("postal_code"),
        "country": c.get("country"), "phone": c.get("phone"), "website": c.get("website"), "domain": c.get("domain"),
        "lat": c.get("lat"), "lng": c.get("lng"), "rating": c.get("rating"), "reviews": c.get("review_count"),
        "employees": c.get("employees"), "about": (c.get("description") or "")[:420 if c.get("qualified") == 1 else 160],
        "score": c.get("score"), "q": 1 if c.get("qualified") == 1 else 0, "ready": 1 if ready else 0,
        "email": 1 if has_email else 0, "verify": best_verify, "disq": disq,
        "reasons": reasons[1:] if disq else reasons,
        "signals": sorted(k for k, v in sig.items() if v is True and not k.startswith("cms_") and k != "email_on_site"),
        "cms": cms, "year": year, "crawl": c.get("crawl_status"),
        "social": socials, "maps": c.get("google_maps_url"), "source": c.get("source"),
        "sources": parse_json(c.get("sources"), []), "ref": c.get("source_ref"), "people": people,
    })


def collect(conn, icp: Dict[str, Any], export_dir: str) -> Dict[str, Any]:
    """Everything the page renders, as plain JSON-able data."""
    companies = [dict(r) for r in conn.execute("SELECT * FROM companies ORDER BY score DESC, id").fetchall()]
    contacts = [dict(r) for r in conn.execute("SELECT * FROM contacts ORDER BY is_primary DESC, id").fetchall()]
    sup_emails, sup_domains = db.suppression_sets(conn)
    by_company: Dict[int, List[Dict[str, Any]]] = {}
    for k in contacts:
        by_company.setdefault(k["company_id"], []).append(k)
    domain_of = {c["id"]: c["domain"] for c in companies}
    accept_role = icp["contacts"].get("accept_role_email", True)
    usable = {cid for cid, ks in by_company.items()  # an address that can export; `leadgen status` counts the same way
              if any(k["email"] and not _blocked(k, domain_of.get(cid), sup_emails, sup_domains, accept_role) for k in ks)}
    verified = {cid for cid, ks in by_company.items() if any(k["verify_status"] in ("valid", "catch_all") for k in ks)}
    crawled = [c for c in companies if c["crawl_status"] == "ok"]
    qualified = [c for c in companies if c["qualified"] == 1]
    ready_ids = {c["id"] for c in qualified if c["id"] in usable}
    thr = icp["scoring"].get("qualify_threshold")

    kpi = {
        "total": len(companies), "website": sum(1 for c in companies if c["website"]),
        "phone": sum(1 for c in companies if c["phone"]), "crawled": len(crawled),
        "crawl_errors": sum(1 for c in companies if c["crawl_status"] and c["crawl_status"] != "ok"),
        "crawl_pending": sum(1 for c in companies if c["website"] and not c["crawl_status"]),
        "email": len(usable), "verified": len(verified), "qualified": len(qualified), "ready": len(ready_ids),
        "disqualified": sum(1 for c in companies if (c["score_reasons"] or "").startswith("DISQUALIFIED")),
        "unscored": sum(1 for c in companies if c["score"] is None),
        "contacts": len(contacts), "emails": sum(1 for k in contacts if k["email"]),
    }

    scores = [c["score"] for c in companies if c["score"] is not None]
    bins = [[lo, sum(1 for s in scores if (lo <= s < lo + 10) or (lo == 0 and s < 0) or (lo == 90 and s >= 100))]
            for lo in range(0, 100, 10)]

    with_email = [k for k in contacts if k["email"]]
    etype = Counter(k["email_type"] or "unknown" for k in with_email)
    vstat = Counter(k["verify_status"] or "unverified" for k in with_email)

    sig_has: Counter = Counter()
    platforms: Counter = Counter()
    for c in crawled:
        sig = parse_json(c["signals"], {})
        for k, v in sig.items():
            if v is True and not k.startswith("cms_") and k != "email_on_site":
                sig_has[k] += 1
        platforms[sig.get("cms") if isinstance(sig.get("cms"), str) else "other"] += 1
    bonus = {k: v for k, v in (icp["signals"].get("bonus") or {}).items() if isinstance(v, (int, float))}
    for key in bonus:  # keep bonus signals on the chart even when no site shows them
        sig_has.setdefault(key[3:] if key.startswith("no_") else key, 0)

    cities: Dict[tuple, Dict[str, Any]] = {}
    for c in companies:
        if not c["city"]:
            continue
        row = cities.setdefault((c["city"], c["state"] or ""), {"city": c["city"], "state": c["state"] or "", "total": 0, "qualified": 0, "ready": 0})
        row["total"] += 1
        row["qualified"] += c["qualified"] == 1
        row["ready"] += c["id"] in ready_ids

    weights = dict(DEFAULT_WEIGHTS)
    weights.update(icp["scoring"].get("weights") or {})
    exports = sorted((f for f in os.listdir(export_dir) if f.endswith(".csv")), reverse=True)[:6] if os.path.isdir(export_dir) else []
    now = time.localtime()

    return {
        "meta": {
            "campaign": icp.get("campaign") or "", "title": pretty_title(icp.get("campaign") or ""),
            "niche": icp.get("niche") or "", "offer": icp.get("offer") or "",
            "places": [str(p) for p in (icp["geography"].get("places") or [])], "country": icp["geography"].get("country") or "",
            "threshold": _num(thr if thr is not None else 40),
            "target": _int(icp["targets"].get("leads")),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S", now),
            "generated_label": f"{time.strftime('%b', now)} {now.tm_mday}, {now.tm_year} at {time.strftime('%H:%M', now)}",
            "titles": icp["contacts"].get("titles") or [],
        },
        "kpi": kpi,
        "bins": bins,
        "email_types": [[k, etype.get(k, 0)] for k in ("personal", "role", "personal_webmail", "third_party", "unknown") if etype.get(k)],
        "verify": [[k, vstat.get(k, 0)] for k in ("valid", "catch_all", "unknown", "risky", "invalid", "unverified") if vstat.get(k)],
        "signals": [[k, n] for k, n in sig_has.most_common()],
        "platforms": [[k, n] for k, n in platforms.most_common(8)],
        "sources": [[k, n] for k, n in Counter(c["source"] or "unknown" for c in companies).most_common()],
        "categories": [[k, n] for k, n in Counter(c["category"] or "uncategorized" for c in companies).most_common(8)],
        "cities": sorted(cities.values(), key=lambda r: (-r["ready"], -r["qualified"], -r["total"]))[:14],
        "weights": sorted(([k, v] for k, v in weights.items() if v), key=lambda kv: -kv[1]),
        "bonus": bonus,
        "usage": [{"provider": u["provider"], "endpoint": u["endpoint"], "units": u["units"], "calls": u["calls"]} for u in db.usage_summary(conn)],
        "exports": exports,
        "leads": [_lead(c, by_company.get(c["id"], []), c["id"] in ready_ids, c["id"] in usable, sup_emails, sup_domains, accept_role)
                  for c in companies],
    }


def _json_for_script(data: Dict[str, Any]) -> str:
    """JSON that is safe inside <script>: no '</script>', no HTML comment openers, no line separators."""
    raw = json.dumps(_finite(data), separators=(",", ":"), default=str, ensure_ascii=False, allow_nan=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") \
              .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E"
           "%3Cstop offset='0' stop-color='%237c5cff'/%3E%3Cstop offset='1' stop-color='%2322d3ee'/%3E%3C/linearGradient%3E%3C/defs%3E"
           "%3Crect width='32' height='32' rx='9' fill='url(%23g)'/%3E%3Ccircle cx='16' cy='16' r='7' fill='none' stroke='white' stroke-width='2.6'/%3E"
           "%3Ccircle cx='16' cy='16' r='2.4' fill='white'/%3E%3C/svg%3E")


def build(conn, icp: Dict[str, Any], export_dir: str) -> str:
    data = collect(conn, icp, export_dir)
    m, k = data["meta"], data["kpi"]
    title = m["title"]
    sub = " · ".join(x for x in (m["niche"], ", ".join(m["places"][:3]) + (f" +{len(m['places']) - 3}" if len(m["places"]) > 3 else "")) if x)
    tabs = "".join(
        f'<button class="tab" role="tab" data-view="{v}" aria-controls="{v}">{label}{badge}</button>'
        for v, label, badge in [("overview", "Overview", ""),
                                ("leads", "Leads", f'<span class="tab-n">{k["ready"]:,}</span>'),
                                ("map", "Map", ""), ("insights", "Insights", "")])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · Lead report</title>
<meta name="description" content="{_esc(f'{k["ready"]:,} ready-to-contact leads out of {k["total"]:,} companies. {sub}')}">
<link rel="icon" href="{FAVICON}">
<script>try{{var t=localStorage.getItem('leadgen-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}}catch(e){{}}</script>
<style>{_asset("report.css")}</style></head>
<body>
<div class="bg-fx" aria-hidden="true"></div>
<nav class="topbar"><div class="topbar-in">
<a class="brand" href="#overview" aria-label="Overview"><span class="logo" aria-hidden="true"></span><span class="brand-t"><b>{_esc(title)}</b><small>Lead Gen Employee</small></span></a>
<div class="tabs" role="tablist">{tabs}<span class="tab-ind" aria-hidden="true"></span></div>
<div class="top-actions"><span class="stamp">{_esc(m["generated_label"])}</span><button class="icon-btn" id="theme" type="button" aria-label="Switch light or dark theme"></button></div>
</div></nav>
<main class="wrap">
<section class="view" id="overview" role="tabpanel"><noscript><p class="sub">This report needs JavaScript to draw its charts and lead list.</p></noscript></section>
<section class="view" id="leads" role="tabpanel"></section>
<section class="view" id="map" role="tabpanel"></section>
<section class="view" id="insights" role="tabpanel"></section>
</main>
<footer class="foot"><div class="wrap">
<span>Generated by the AI Lead Gen Employee on {_esc(m["generated_label"])}.</span>
<span>Every row carries a source reference. Guessed emails stay flagged until verified. Invalid, suppressed and do-not-contact addresses never export or push.</span>
</div></footer>
<div class="scrim" id="scrim" hidden></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="Lead details" aria-hidden="true" tabindex="-1"></aside>
<div id="tip" role="tooltip"></div><div id="toast" role="status" aria-live="polite"></div>
<script type="application/json" id="leadgen-data">{_json_for_script(data)}</script>
<script>{_asset("report.js")}</script>
</body></html>"""


def write(conn, icp: Dict[str, Any], export_dir: str, out: Optional[str] = None) -> str:
    os.makedirs(export_dir, exist_ok=True)
    path = out or os.path.join(export_dir, f"{icp.get('campaign') or 'leads'}_report_{time.strftime('%Y%m%d-%H%M')}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build(conn, icp, export_dir))
    return path


def open_in_browser(path: str) -> None:
    """Best-effort open on macOS, Windows, and Linux."""
    import subprocess
    import sys
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
