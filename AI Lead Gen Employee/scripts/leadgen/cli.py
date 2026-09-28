"""leadgen command line. Every stage is idempotent and resumable; state lives in data/leadgen.db."""
import argparse
import csv
import json
import os
import random
import shutil
import socket
import sqlite3
import ssl
import sys
import urllib.error
from typing import Any, Dict, List, Optional

from . import __version__, config, db
from .util import parse_json, clean_email, classify_email, normalize_website

# ----------------------------------------------------------------------------- helpers

def log(msg: str = "") -> None:
    print(msg, flush=True)


def _conn():
    return db.connect(config.DB_PATH)


def _icp():
    return config.load_icp()


def _run(conn, name: str, args: argparse.Namespace, fn):
    run_id = db.start_run(conn, name, {k: v for k, v in vars(args).items() if k not in ("func",)})
    try:
        stats = fn() or {}
    except KeyboardInterrupt:
        conn.commit()
        db.finish_run(conn, run_id, {"interrupted": True})
        log("\n  interrupted; progress saved.")
        return None
    db.finish_run(conn, run_id, stats)
    log("  done: " + json.dumps(stats, default=str))
    return stats


def _split(vals: Optional[List[str]]) -> List[str]:
    """Comma-separated or repeated flag values (categories, tags, emails, domains)."""
    out: List[str] = []
    for v in vals or []:
        out.extend(x.strip() for x in v.split(",") if x.strip())
    return out


def _list(vals: Optional[List[str]]) -> List[str]:
    """Repeated flag values kept whole (place names like 'Round Rock, TX', ranges like '1,10')."""
    return [v.strip() for v in vals or [] if v and v.strip()]


# ----------------------------------------------------------------------------- init / doctor / config

def cmd_init(args):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    os.makedirs(config.RAW_DIR, exist_ok=True)
    conn = _conn()
    conn.close()
    if not os.path.exists(config.ICP_PATH):
        with open(config.ICP_PATH, "w", encoding="utf-8") as fh:
            json.dump(config.blank_icp(), fh, indent=2)
        log("  created a blank config/icp.json. No niche or location is set yet.")
    elif config.is_configured(config.load_icp()):
        log(f"  config/icp.json exists: campaign '{config.load_icp()['campaign']}'.")
    else:
        log("  config/icp.json exists but is blank.")
    env = os.path.join(config.ROOT, ".env")
    if not os.path.exists(env):
        shutil.copy(os.path.join(config.ROOT, ".env.example"), env)
        log("  created .env from .env.example (all keys optional).")
    log(f"  database: {config.DB_PATH}")
    if config.is_configured(config.load_icp()):
        log("  ready. Next: leadgen doctor, then leadgen run")
    else:
        log("  ready. Next: describe your business and who you want to reach; the employee writes config/icp.json "
            "(examples for several industries are in config/examples/).")


def cmd_doctor(args):
    ok = True
    v = sys.version_info
    log(f"  python {v.major}.{v.minor}.{v.micro} {'ok' if v >= (3, 9) else 'TOO OLD (need 3.9+)'}")
    ok &= v >= (3, 9)
    log(f"  dig for MX checks: {'found' if shutil.which('dig') else 'missing (falls back to nslookup / A-record only)'}")
    log(f"  data dir: {config.DATA_DIR} {'writable' if os.access(os.path.dirname(config.DATA_DIR) if not os.path.exists(config.DATA_DIR) else config.DATA_DIR, os.W_OK) else 'NOT WRITABLE'}")
    if not os.path.exists(config.ICP_PATH):
        log("  icp.json: missing (run leadgen init)")
    elif config.is_configured(_icp()):
        log(f"  icp.json: configured, campaign '{_icp()['campaign']}' ({_icp().get('niche') or 'no niche text'})")
        for p in config.validate_icp(_icp()):
            log(f"    ! {p}")
    else:
        log("  icp.json: NOT CONFIGURED. " + config.NOT_CONFIGURED)
    log("  API keys (presence only, values never printed):")
    for k, present in config.key_status().items():
        log(f"    {k:<24} {'set' if present else '-':<4} {config.KEYS[k]}")
    if args.network:
        from .util import http_json
        try:
            http_json("GET", "https://nominatim.openstreetmap.org/status.php?format=json", timeout=10)
            log("  network: Nominatim reachable")
        except Exception as e:
            log(f"  network: Nominatim NOT reachable ({e})")
            ok = False
        try:
            from .util import http_request
            http_request("GET", "https://overpass-api.de/api/status", timeout=15, retries=0)
            log("  network: Overpass reachable")
        except Exception as e:
            log(f"  network: Overpass NOT reachable ({e})")
    log("  free path available: OSM sourcing + crawl + local verify need no keys.")
    return 0 if ok else 1


def cmd_config(args):
    icp = _icp()
    if args.what == "explain":
        from .score import explain
        log(explain(icp))
        return
    probs = config.validate_icp(icp)
    if args.what == "check":
        log("  valid" if not probs else "  problems:")
        for p in probs:
            log(f"    ! {p}")
        return 1 if probs else 0
    if args.what == "examples":
        for f in sorted(os.listdir(config.EXAMPLES_DIR)):
            ex = config.load_icp(os.path.join(config.EXAMPLES_DIR, f))
            log(f"  {f:<34} {ex.get('niche') or ''} | places {ex['geography']['places'][:3]}")
        return
    log(json.dumps(icp, indent=2))
    for p in probs:
        log(f"  ! {p}")


# ----------------------------------------------------------------------------- source

def cmd_source(args):
    icp = _icp()
    conn = _conn()
    prov = args.provider
    if prov == "osm":
        from .sources import osm
        if args.list_categories:
            for k, v in sorted(osm.PRESETS.items()):
                log(f"  {k:<18} {'; '.join(v)}")
            return
        places = _list(args.place) or ([] if args.bbox else icp["geography"]["places"])  # --bbox alone searches just that box
        cats = _split(args.category) or icp["sources"].get("osm_categories") or []
        tags = _split(args.tags) or icp["sources"].get("osm_tags") or []
        return _run(conn, "source osm", args, lambda: osm.run(
            conn, icp, places=places, bbox=args.bbox, categories=cats, tags=tags, limit=args.limit,
            dry_run=args.dry_run, log=log))
    if prov == "places":
        from .sources import places as gp
        key = config.require_key("GOOGLE_PLACES_API_KEY")
        queries = _list(args.query) or icp["sources"].get("places_queries") or []
        placelist = _list(args.place) or icp["geography"]["places"]
        return _run(conn, "source places", args, lambda: gp.run(
            conn, icp, key, queries, places=placelist if not args.center else [], center=args.center,
            radius_km=args.radius_km, cell_km=args.cell_km, max_requests=args.max_requests,
            included_type=args.type, limit=args.limit, dry_run=args.dry_run, log=log))
    if prov == "apollo":
        from .sources import apollo
        key = config.require_key("APOLLO_API_KEY")
        kws = _list(args.keyword) or icp["sources"].get("apollo_keywords") or []
        locs = _list(args.location) or icp["geography"]["places"]
        sizes = _list(args.employees) or icp["sources"].get("apollo_employee_ranges") or []
        return _run(conn, "source apollo", args, lambda: apollo.run(
            conn, icp, key, kws, locs, sizes, pages=args.pages, per_page=args.per_page, start_page=args.start_page,
            limit=args.limit, dry_run=args.dry_run, log=log))
    if prov == "csv":
        from .sources import csv_import
        bad = [kv for kv in (args.map or []) if "=" not in kv]
        if bad:
            raise SystemExit(f"--map needs field=Column, for example --map name=\"Business Name\" (got {bad[0]!r})")
        overrides = dict(kv.split("=", 1) for kv in (args.map or []))
        return _run(conn, "source csv", args, lambda: csv_import.run(
            conn, icp, args.path, overrides, source=args.source_name, default_category=args.category_name,
            limit=args.limit, dry_run=args.dry_run, log=log))


def cmd_add(args):
    """Add one company (and optional contact) by hand or from Claude-driven web research."""
    icp = _icp()
    conn = _conn()
    from .sources import base_record
    rec = base_record(args.name, args.website or "", args.phone or "", args.country or icp["geography"].get("country") or "US",
                      address=args.address, city=args.city, state=args.state, postal_code=args.postal_code,
                      category=args.category, industry=args.industry, description=args.description,
                      source_ref=args.ref, tags=args.tags, notes=args.notes)
    cid, created = db.upsert_company(conn, rec, args.source)
    email = clean_email(args.email or "")
    if email or (args.first and args.last):
        db.upsert_contact(conn, cid, {"email": email or None,
                                      "email_type": classify_email(email, rec.get("domain", "")) if email else None,
                                      "email_source": args.source if email else None, "email_confidence": 70 if email else None,
                                      "first_name": args.first, "last_name": args.last, "title": args.title,
                                      "source_ref": args.ref})
    conn.commit()
    log(f"  {'created' if created else 'merged into'} company #{cid} {rec['name']}" + (f" + contact {email}" if email else ""))


def cmd_set(args):
    conn = _conn()
    if not db.get_company(conn, args.company_id):
        raise SystemExit(f"no company #{args.company_id} (leadgen sample or leadgen sql can find the id)")
    if args.name is not None and not args.name.strip():
        raise SystemExit("a company name cannot be blank")
    fields: Dict[str, Any] = {}
    if args.website is not None:
        site, domain, kind = normalize_website(args.website)
        if kind != "site":
            raise SystemExit(f"'{args.website}' is not a company website (kind={kind or 'invalid'})")
        fields["website"], fields["domain"] = site, domain
        fields["crawl_status"] = None
    for k in ("phone", "name", "city", "state", "category", "notes", "tags", "email_pattern", "employees", "industry"):
        v = getattr(args, k, None)
        if v is not None:
            fields[k] = v
    if args.qualified is not None:
        fields["qualified"] = 1 if args.qualified in ("1", "yes", "true") else 0
        fields["score_reasons"] = (db.get_company(conn, args.company_id)["score_reasons"] or "") + f"; manual qualified={fields['qualified']}"
    if not fields:
        raise SystemExit("nothing to set")
    db.update_company(conn, args.company_id, **fields)
    conn.commit()
    log(f"  updated company #{args.company_id}: {list(fields)}")


# ----------------------------------------------------------------------------- enrich

def cmd_crawl(args):
    conn = _conn()
    from . import crawl
    ids = [int(x) for x in _split(args.ids)] if args.ids else None
    return _run(conn, "crawl", args, lambda: crawl.run(
        conn, limit=args.limit, workers=args.workers, recrawl=args.recrawl, retry_errors=args.retry_errors, max_pages=args.max_pages, only_ids=ids,
        delay=args.delay, log=log))


def cmd_contacts(args):
    icp = _icp()
    conn = _conn()
    if args.provider == "hunter":
        from .contacts import hunter
        key = config.require_key("HUNTER_API_KEY")
        return _run(conn, "contacts hunter", args, lambda: hunter.run(
            conn, icp, key, max_requests=args.max_requests, limit_per_domain=args.limit_per_domain,
            seniority=args.seniority, department=args.department, only_qualified=args.only_qualified,
            dry_run=args.dry_run, log=log))
    if args.provider == "apollo":
        from .contacts import apollo_people
        key = config.require_key("APOLLO_API_KEY")
        return _run(conn, "contacts apollo", args, lambda: apollo_people.run(
            conn, icp, key, max_credits=args.max_credits, per_company=args.per_company,
            titles=_list(args.title) or None, seniorities=_split(args.seniority) or None,
            only_qualified=not args.all, dry_run=args.dry_run, log=log))
    if args.provider == "pattern":
        from .contacts import pattern
        return _run(conn, "contacts pattern", args, lambda: pattern.run(conn, icp, limit=args.limit, log=log))


def cmd_verify(args):
    conn = _conn()
    from . import verify
    key = None
    if args.provider == "hunter":
        key = config.require_key("HUNTER_API_KEY")
    elif args.provider == "instantly":
        key = config.require_key("INSTANTLY_API_KEY")
    return _run(conn, "verify", args, lambda: verify.run(
        conn, provider=args.provider, limit=args.limit, max_requests=args.max_requests,
        only_qualified=args.only_qualified, api_key=key, recheck=args.recheck, log=log))


def cmd_score(args):
    icp = _icp()
    conn = _conn()
    from . import score
    if args.explain:
        log(score.explain(icp))
        return
    return _run(conn, "score", args, lambda: score.run(conn, icp, only_unscored=args.only_unscored, log=log))


# ----------------------------------------------------------------------------- suppression

def cmd_suppress(args):
    conn = _conn()
    if args.action == "list":
        rows = conn.execute("SELECT kind, value, reason, added_at FROM suppression ORDER BY added_at DESC").fetchall()
        for r in rows:
            log(f"  {r['kind']:<7} {r['value']:<40} {r['reason'] or ''}")
        log(f"  {len(rows)} entries")
        return
    n = 0
    if args.action == "add":
        for e in _split(args.email):
            n += db.suppress(conn, "email", e, args.reason or "manual")
        for d in _split(args.domain):
            n += db.suppress(conn, "domain", d, args.reason or "manual")
    elif args.action == "import":
        with open(args.path, encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            if "," in sample.splitlines()[0] if sample else False:
                for row in csv.DictReader(fh):
                    val = next((v for k, v in row.items() if k and k.lower() in ("email", "domain", "value")), None) or next(iter(row.values()))
                    val = (val or "").strip().lower()
                    if not val:
                        continue
                    n += db.suppress(conn, "email" if "@" in val else "domain", val, args.reason or f"import:{os.path.basename(args.path)}")
            else:
                for line in fh:
                    val = line.strip().lower()
                    if val and not val.startswith("#"):
                        n += db.suppress(conn, "email" if "@" in val else "domain", val, args.reason or f"import:{os.path.basename(args.path)}")
    conn.commit()
    log(f"  added {n} suppression entries")


# ----------------------------------------------------------------------------- export / push

def _rows_from_args(conn, icp, args, exclude_pushed: Optional[str] = None):
    from .export import build_rows
    return build_rows(conn, icp, only_qualified=not getattr(args, "all", False), min_score=args.min_score,
                      one_per_company=not getattr(args, "all_contacts", False), verified_only=args.verified_only,
                      include_unverified=not getattr(args, "no_unverified", False),
                      include_no_email=getattr(args, "include_no_email", False), sources=_split(getattr(args, "source", None)) or None,
                      limit=args.limit, exclude_pushed=exclude_pushed)


def cmd_export(args):
    icp = _icp()
    conn = _conn()
    from .export import write_csv, default_path, summary
    rows = _rows_from_args(conn, icp, args)
    out = args.out or default_path(config.EXPORT_DIR, icp.get("campaign") or "leads", args.format)
    write_csv(rows, args.format, out)
    s = summary(rows)
    db.start_run(conn, "export", {"format": args.format, "out": out, **s})
    log(f"  wrote {len(rows)} rows -> {out}")
    log("  summary: " + json.dumps(s))
    if s.get("dup_emails"):
        log("  ! duplicate emails present (use --all-contacts off, or check suppression)")
    return s


def cmd_push(args):
    icp = _icp()
    conn = _conn()
    rows = _rows_from_args(conn, icp, args, exclude_pushed=None if args.repush else args.target)
    if args.target == "instantly":
        from .connectors import instantly
        key = config.require_key("INSTANTLY_API_KEY")
        return _run(conn, "push instantly", args, lambda: instantly.push(
            conn, key, rows, campaign=args.campaign, list_name=args.list, yes=args.yes, batch_size=args.batch,
            verify_on_import=args.verify_on_import, skip_if_in_workspace=not args.no_skip_workspace, log=log))
    if args.target == "ghl":
        from .connectors import ghl
        key = config.require_key("GHL_API_KEY")
        loc = args.location or config.require_key("GHL_LOCATION_ID")
        tags = _split(args.tag) or ["lead-gen-employee"]
        return _run(conn, "push ghl", args, lambda: ghl.push(conn, key, loc, rows, tags=tags, yes=args.yes, log=log))


# ----------------------------------------------------------------------------- status / inspection

def _count(conn, sql: str, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def usable_email_sql(icp: Dict[str, Any]) -> str:
    """A contact email that can export: the same rule export.build_rows and the report apply."""
    sql = ("c.email IS NOT NULL AND c.verify_status != 'invalid' AND c.status != 'do_not_contact' "
           "AND NOT (COALESCE(c.email_type, '') = 'third_party' AND COALESCE(c.email_source, '') = 'crawl') "
           "AND lower(c.email) NOT IN (SELECT value FROM suppression WHERE kind = 'email') "
           "AND lower(substr(c.email, instr(c.email, '@') + 1)) NOT IN (SELECT value FROM suppression WHERE kind = 'domain') "
           "AND (co.domain IS NULL OR co.domain NOT IN (SELECT value FROM suppression WHERE kind = 'domain'))")
    if not icp["contacts"].get("accept_role_email", True):
        sql += " AND COALESCE(c.email_type, '') != 'role'"
    return sql


def status_data(conn, icp) -> Dict[str, Any]:
    d: Dict[str, Any] = {"campaign": icp.get("campaign"), "target_leads": icp["targets"].get("leads")}
    d["companies"] = {
        "total": _count(conn, "SELECT COUNT(*) FROM companies"),
        "with_website": _count(conn, "SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website != ''"),
        "with_phone": _count(conn, "SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''"),
        "crawled_ok": _count(conn, "SELECT COUNT(*) FROM companies WHERE crawl_status = 'ok'"),
        "crawl_errors": _count(conn, "SELECT COUNT(*) FROM companies WHERE crawl_status = 'error'"),
        "uncrawled_with_site": _count(conn, "SELECT COUNT(*) FROM companies WHERE crawl_status IS NULL AND website IS NOT NULL AND website != ''"),
        "with_any_email": _count(conn, "SELECT COUNT(DISTINCT c.company_id) FROM contacts c JOIN companies co ON co.id = c.company_id WHERE " + usable_email_sql(icp)),
        "with_valid_email": _count(conn, "SELECT COUNT(DISTINCT company_id) FROM contacts WHERE verify_status IN ('valid','catch_all')"),
        "unscored": _count(conn, "SELECT COUNT(*) FROM companies WHERE score IS NULL"),
        "qualified": _count(conn, "SELECT COUNT(*) FROM companies WHERE qualified = 1"),
        "disqualified_or_low": _count(conn, "SELECT COUNT(*) FROM companies WHERE qualified = 0"),
    }
    d["contacts"] = {
        "total": _count(conn, "SELECT COUNT(*) FROM contacts"),
        "with_email": _count(conn, "SELECT COUNT(*) FROM contacts WHERE email IS NOT NULL"),
        "by_type": {r[0] or "none": r[1] for r in conn.execute("SELECT email_type, COUNT(*) FROM contacts WHERE email IS NOT NULL GROUP BY email_type")},
        "by_source": {r[0] or "none": r[1] for r in conn.execute("SELECT email_source, COUNT(*) FROM contacts WHERE email IS NOT NULL GROUP BY email_source")},
        "by_verify": {r[0]: r[1] for r in conn.execute("SELECT verify_status, COUNT(*) FROM contacts WHERE email IS NOT NULL GROUP BY verify_status")},
        "pushed": _count(conn, "SELECT COUNT(*) FROM contacts WHERE status = 'pushed'"),
        "do_not_contact": _count(conn, "SELECT COUNT(*) FROM contacts WHERE status = 'do_not_contact'"),
    }
    d["sources"] = {r[0] or "none": r[1] for r in conn.execute("SELECT source, COUNT(*) FROM companies GROUP BY source")}
    d["suppression"] = {r[0]: r[1] for r in conn.execute("SELECT kind, COUNT(*) FROM suppression GROUP BY kind")}
    d["api_usage"] = [dict(r) for r in db.usage_summary(conn)]
    d["last_runs"] = [dict(r) for r in conn.execute("SELECT command, started_at, finished_at, stats FROM runs ORDER BY id DESC LIMIT 8")]
    exports = sorted((f for f in os.listdir(config.EXPORT_DIR) if f.endswith(".csv")), reverse=True) if os.path.isdir(config.EXPORT_DIR) else []
    d["exports"] = exports[:5]
    d["ready_leads"] = _count(conn, "SELECT COUNT(DISTINCT c.company_id) FROM contacts c JOIN companies co ON co.id = c.company_id "
                                    "WHERE co.qualified = 1 AND " + usable_email_sql(icp))
    return d


def cmd_status(args):
    icp = _icp()
    conn = _conn()
    d = status_data(conn, icp)
    if args.json:
        log(json.dumps(d, indent=2, default=str))
        return
    c, k = d["companies"], d["contacts"]
    if not config.is_configured(icp):
        log("!! " + config.NOT_CONFIGURED)
    target = f"{d['target_leads']} leads" if config.is_configured(icp) else "not set"
    log(f"Campaign: {d['campaign'] or '(not configured)'}   target: {target}   READY NOW: {d['ready_leads']} qualified companies with a usable email")
    log(f"Companies: {c['total']} total | website {c['with_website']} | phone {c['with_phone']} | any email {c['with_any_email']} | verified email {c['with_valid_email']}")
    log(f"  crawl: ok {c['crawled_ok']} | errors {c['crawl_errors']} | pending {c['uncrawled_with_site']}")
    log(f"  score: qualified {c['qualified']} | not qualified {c['disqualified_or_low']} | unscored {c['unscored']}")
    log(f"Contacts: {k['total']} | with email {k['with_email']} | pushed {k['pushed']} | do-not-contact {k['do_not_contact']}")
    log(f"  type: {k['by_type']}")
    log(f"  source: {k['by_source']}")
    log(f"  verify: {k['by_verify']}")
    log(f"Sources: {d['sources']}   Suppression: {d['suppression'] or {}}")
    if d["api_usage"]:
        log("API usage: " + ", ".join(f"{u['provider']}/{u['endpoint']}={u['units']}" for u in d["api_usage"]))
    if d["exports"]:
        log("Exports: " + ", ".join(d["exports"]))
    if d["last_runs"]:
        log("Last runs:")
        for r in d["last_runs"]:
            log(f"  {r['started_at']}  {r['command']:<18} {(r['stats'] or '')[:100]}")


def cmd_report(args):
    icp = _icp()
    conn = _conn()
    from . import report
    path = report.write(conn, icp, config.EXPORT_DIR, args.out)
    db.start_run(conn, "report", {"out": path})
    log(f"  wrote report -> {path}")
    if args.open:
        report.open_in_browser(path)
    return 0


def cmd_sample(args):
    icp = _icp()
    conn = _conn()
    from .export import build_rows
    rows = build_rows(conn, icp, only_qualified=not args.all, min_score=args.min_score, one_per_company=True,
                      include_no_email=args.all)
    random.shuffle(rows)
    for r in rows[:args.n]:
        log(f"#{r['company_id']} {r['company_name']} | {r['website']} | {r['city']}, {r['state']} | score {r['score']}")
        log(f"    email: {r['email'] or '-'} ({r['email_type']}, {r['email_source']}, {r['verify_status']}) | name: {r['full_name'] or '-'} {r['title'] or ''}")
        log(f"    why: {r['score_reasons'][:160]}")
        log(f"    signals: {r['signals'] or '-'} | src: {r['source']} {r['source_ref'][:60]}")
    log(f"  ({len(rows)} matching rows)")


def cmd_show(args):
    conn = _conn()
    co = db.get_company(conn, args.company_id)
    if not co:
        raise SystemExit("no such company")
    d = dict(co)
    d["signals"] = parse_json(d.get("signals"), {})
    log(json.dumps(d, indent=2, default=str))
    for k in db.company_contacts(conn, args.company_id):
        kd = dict(k)
        log("  contact: " + json.dumps({x: kd[x] for x in ("id", "email", "email_type", "email_source", "email_confidence",
                                                          "first_name", "last_name", "title", "verify_status", "verify_detail",
                                                          "is_primary", "status")}, default=str))


def cmd_missing(args):
    conn = _conn()
    f = args.field
    if f == "email":
        sql = ("SELECT co.id, co.name, co.website, co.city, co.state, co.phone FROM companies co WHERE co.qualified IS NOT 0 AND NOT EXISTS "
               "(SELECT 1 FROM contacts c WHERE c.company_id = co.id AND c.email IS NOT NULL AND c.verify_status != 'invalid') "
               "ORDER BY COALESCE(co.score,0) DESC, co.id")
    else:
        sql = (f"SELECT id, name, website, city, state, phone FROM companies WHERE ({f} IS NULL OR {f} = '') AND qualified IS NOT 0 "
               f"ORDER BY COALESCE(score,0) DESC, id")
    rows = conn.execute(sql + f" LIMIT {int(args.limit)}").fetchall()
    if args.json:
        log(json.dumps([dict(r) for r in rows]))
        return
    for r in rows:
        log(f"  #{r['id']}\t{r['name']}\t{r['website'] or '-'}\t{r['city'] or ''} {r['state'] or ''}\t{r['phone'] or ''}")
    log(f"  {len(rows)} companies missing {f}")


def cmd_sql(args):
    conn = _conn()
    q = args.query.strip()
    if not args.write and not q.lower().startswith(("select", "with", "explain", "pragma")):
        raise SystemExit("read-only: pass --write for UPDATE/DELETE/INSERT")
    if not args.write:
        conn.execute("PRAGMA query_only = ON")  # the database itself refuses writes, whatever the query looks like
    try:
        cur = conn.execute(q)
    except sqlite3.Error as e:
        if "readonly" in str(e).lower() or "query_only" in str(e).lower():
            raise SystemExit("read-only: this query changes data; pass --write only if the user asked for that change")
        raise SystemExit(f"sql error: {e}")
    if cur.description:
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(args.limit)
        if args.json:
            log(json.dumps([dict(zip(cols, r)) for r in rows], default=str))
        else:
            log("\t".join(cols))
            for r in rows:
                log("\t".join("" if v is None else str(v) for v in r))
            log(f"  ({len(rows)} rows shown)")
    else:
        conn.commit()
        log(f"  {cur.rowcount} rows affected")


def cmd_reset(args):
    if not args.yes:
        raise SystemExit(f"This deletes {config.DB_PATH} (all companies, contacts, suppression). Re-run with --yes.")
    if os.path.exists(config.DB_PATH):
        import sqlite3
        import time
        backup_dir = os.path.join(config.DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, time.strftime("leadgen-%Y%m%d-%H%M%S.db"))
        src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        src.close(); dst.close()
        log(f"  backup: {dest}")
    for sfx in ("", "-wal", "-shm", "-journal"):
        p = config.DB_PATH + sfx
        if os.path.exists(p):
            os.remove(p)
    log("  database deleted. Exports in data/exports are untouched.")


# ----------------------------------------------------------------------------- run (pipeline)

def cmd_run(args):
    """Default pipeline from icp.json: source -> crawl -> local verify -> score -> export."""
    icp = _icp()
    if not config.is_configured(icp):
        raise SystemExit(config.NOT_CONFIGURED)
    probs = config.validate_icp(icp)
    if probs:
        for p in probs:
            log(f"  ! {p}")
        raise SystemExit("fix config/icp.json first (leadgen config check)")
    conn = _conn()
    keys = config.key_status()
    if not args.skip_source:
        from .sources import osm
        cats = icp["sources"].get("osm_categories") or []
        tags = icp["sources"].get("osm_tags") or []
        if cats or tags:
            log("== source osm")
            _run(conn, "source osm", args, lambda: osm.run(conn, icp, places=icp["geography"]["places"], categories=cats, tags=tags, log=log))
        if keys["GOOGLE_PLACES_API_KEY"] and icp["sources"].get("places_queries"):
            from .sources import places as gp
            log("== source places")
            _run(conn, "source places", args, lambda: gp.run(conn, icp, os.environ["GOOGLE_PLACES_API_KEY"],
                                                            icp["sources"]["places_queries"], places=icp["geography"]["places"],
                                                            max_requests=args.max_requests, log=log))
        if keys["APOLLO_API_KEY"] and icp["sources"].get("apollo_keywords"):
            from .sources import apollo
            log("== source apollo")
            _run(conn, "source apollo", args, lambda: apollo.run(conn, icp, os.environ["APOLLO_API_KEY"], icp["sources"]["apollo_keywords"],
                                                                icp["geography"]["places"], icp["sources"].get("apollo_employee_ranges") or [],
                                                                pages=args.apollo_pages, log=log))
    if not args.skip_crawl:
        from . import crawl
        log("== crawl")
        _run(conn, "crawl", args, lambda: crawl.run(conn, workers=args.workers, log=log))
    from . import verify, score
    log("== verify local")
    _run(conn, "verify", args, lambda: verify.run(conn, provider="local", log=log))
    log("== score")
    _run(conn, "score", args, lambda: score.run(conn, icp, log=log))
    if not args.skip_contacts and keys["HUNTER_API_KEY"] and args.hunter_requests > 0:
        from .contacts import hunter
        log("== contacts hunter (qualified companies only)")
        _run(conn, "contacts hunter", args, lambda: hunter.run(conn, icp, os.environ["HUNTER_API_KEY"], max_requests=args.hunter_requests,
                                                               only_qualified=True, log=log))
        log("== verify local + score again")
        _run(conn, "verify", args, lambda: verify.run(conn, provider="local", log=log))
        _run(conn, "score", args, lambda: score.run(conn, icp, log=log))
    from .export import build_rows, write_csv, default_path, summary
    rows = build_rows(conn, icp, only_qualified=True, one_per_company=True)
    out = default_path(config.EXPORT_DIR, icp.get("campaign") or "leads", "generic")
    write_csv(rows, "generic", out)
    log(f"== export: {len(rows)} rows -> {out}")
    log("  " + json.dumps(summary(rows)))
    cmd_status(argparse.Namespace(json=False))


# ----------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadgen", description="Lead Gen Employee toolkit: find companies, find emails, verify, score, export, push.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create data dir, database, config/icp.json and .env from examples"); s.set_defaults(func=cmd_init)
    s = sub.add_parser("doctor", help="check python, DNS tools, config, which API keys are set"); s.add_argument("--network", action="store_true"); s.set_defaults(func=cmd_doctor)
    s = sub.add_parser("config", help="show / check / explain the ICP config"); s.add_argument("what", nargs="?", default="show", choices=["show", "check", "explain", "examples"]); s.set_defaults(func=cmd_config)

    s = sub.add_parser("source", help="find companies from a provider")
    ss = s.add_subparsers(dest="provider", required=True)
    o = ss.add_parser("osm", help="OpenStreetMap via Overpass (free, no key)")
    o.add_argument("--place", action="append", help="place name like 'Round Rock, TX'; repeat the flag for more (default: icp geography.places)")
    o.add_argument("--bbox", help="south,west,north,east instead of --place")
    o.add_argument("--category", action="append", help="preset category (see --list-categories)")
    o.add_argument("--tags", action="append", help="raw OSM filter like amenity=dentist or shop~beauty|hairdresser; ';' for AND")
    o.add_argument("--list-categories", action="store_true")
    o.add_argument("--limit", type=int); o.add_argument("--dry-run", action="store_true"); o.set_defaults(func=cmd_source)
    g = ss.add_parser("places", help="Google Places API (New) text search with grid tiling (paid)")
    g.add_argument("--place", action="append"); g.add_argument("--query", action="append", help="search phrase, repeatable")
    g.add_argument("--center", help="lat,lng instead of --place"); g.add_argument("--radius-km", type=float)
    g.add_argument("--cell-km", type=float, help="grid cell size; omit for a single 60-result search per query")
    g.add_argument("--max-requests", type=int, default=100); g.add_argument("--type", help="Places includedType filter, e.g. dentist")
    g.add_argument("--limit", type=int); g.add_argument("--dry-run", action="store_true"); g.set_defaults(func=cmd_source)
    a = ss.add_parser("apollo", help="Apollo.io organization search (paid plan)")
    a.add_argument("--keyword", action="append"); a.add_argument("--location", action="append")
    a.add_argument("--employees", action="append", help="ranges like 1,10 or 11,50")
    a.add_argument("--pages", type=int, default=1); a.add_argument("--per-page", type=int, default=100); a.add_argument("--start-page", type=int, default=1)
    a.add_argument("--limit", type=int); a.add_argument("--dry-run", action="store_true"); a.set_defaults(func=cmd_source)
    c = ss.add_parser("csv", help="import companies from any CSV")
    c.add_argument("path"); c.add_argument("--map", action="append", help="field=Column overrides, e.g. --map name='Business Name'")
    c.add_argument("--source-name", default="csv"); c.add_argument("--category-name", help="category to assign when the CSV has none")
    c.add_argument("--limit", type=int); c.add_argument("--dry-run", action="store_true"); c.set_defaults(func=cmd_source)

    s = sub.add_parser("add", help="add one company (+ optional contact) e.g. from web research")
    for f in ("name", "website", "phone", "email", "address", "city", "state", "postal-code", "country", "category", "industry",
              "description", "ref", "tags", "notes", "first", "last", "title"):
        s.add_argument("--" + f, dest=f.replace("-", "_"), required=(f == "name"))
    s.add_argument("--source", default="web_research"); s.set_defaults(func=cmd_add)
    s = sub.add_parser("set", help="update fields on a company by id")
    s.add_argument("company_id", type=int)
    for f in ("website", "phone", "name", "city", "state", "category", "notes", "tags", "email-pattern", "employees", "industry", "qualified"):
        s.add_argument("--" + f, dest=f.replace("-", "_"))
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("crawl", help="crawl company websites for emails, phones, socials, signals")
    s.add_argument("--limit", type=int); s.add_argument("--workers", type=int, default=6); s.add_argument("--recrawl", action="store_true")
    s.add_argument("--retry-errors", action="store_true", help="crawl only sites that failed or were never crawled")
    s.add_argument("--max-pages", type=int, default=6); s.add_argument("--ids", action="append"); s.add_argument("--delay", type=float, default=0.6)
    s.set_defaults(func=cmd_crawl)

    s = sub.add_parser("contacts", help="find named contacts / emails via a provider")
    ss = s.add_subparsers(dest="provider", required=True)
    h = ss.add_parser("hunter"); h.add_argument("--max-requests", type=int, default=50); h.add_argument("--limit-per-domain", type=int, default=10)
    h.add_argument("--seniority", help="junior,senior,executive"); h.add_argument("--department", help="executive,sales,marketing,it,...")
    h.add_argument("--only-qualified", action="store_true"); h.add_argument("--dry-run", action="store_true"); h.set_defaults(func=cmd_contacts)
    ap = ss.add_parser("apollo"); ap.add_argument("--max-credits", type=int, default=50); ap.add_argument("--per-company", type=int, default=2)
    ap.add_argument("--title", action="append"); ap.add_argument("--seniority", action="append"); ap.add_argument("--all", action="store_true", help="not only qualified companies")
    ap.add_argument("--dry-run", action="store_true"); ap.set_defaults(func=cmd_contacts)
    pt = ss.add_parser("pattern", help="generate emails for named contacts from the company's known email pattern"); pt.add_argument("--limit", type=int); pt.set_defaults(func=cmd_contacts)

    s = sub.add_parser("verify", help="verify emails: local (syntax+MX, free) or hunter / instantly")
    s.add_argument("--provider", default="local", choices=["local", "hunter", "instantly"]); s.add_argument("--limit", type=int)
    s.add_argument("--max-requests", type=int, default=100); s.add_argument("--only-qualified", action="store_true"); s.add_argument("--recheck", action="store_true")
    s.set_defaults(func=cmd_verify)
    s = sub.add_parser("score", help="score companies against the ICP and pick primary contacts"); s.add_argument("--only-unscored", action="store_true"); s.add_argument("--explain", action="store_true"); s.set_defaults(func=cmd_score)

    s = sub.add_parser("suppress", help="do-not-contact list")
    ss = s.add_subparsers(dest="action", required=True)
    x = ss.add_parser("add"); x.add_argument("--email", action="append"); x.add_argument("--domain", action="append"); x.add_argument("--reason"); x.set_defaults(func=cmd_suppress)
    x = ss.add_parser("import"); x.add_argument("path"); x.add_argument("--reason"); x.set_defaults(func=cmd_suppress)
    x = ss.add_parser("list"); x.set_defaults(func=cmd_suppress)

    def add_selection(sp):
        sp.add_argument("--all", action="store_true", help="include non-qualified companies")
        sp.add_argument("--min-score", type=float); sp.add_argument("--verified-only", action="store_true")
        sp.add_argument("--no-unverified", action="store_true", help="drop contacts never checked (keeps mx_ok unknowns)")
        sp.add_argument("--limit", type=int); sp.add_argument("--source", action="append")
    s = sub.add_parser("export", help="write the lead CSV")
    s.add_argument("--format", default="generic", choices=["generic", "instantly", "ghl", "smartlead", "lemlist"]); s.add_argument("--out")
    s.add_argument("--all-contacts", action="store_true", help="every usable contact, not just the primary one per company")
    s.add_argument("--include-no-email", action="store_true"); add_selection(s); s.set_defaults(func=cmd_export)

    s = sub.add_parser("push", help="push leads to Instantly or GoHighLevel (dry run unless --yes)")
    ss = s.add_subparsers(dest="target", required=True)
    i = ss.add_parser("instantly"); i.add_argument("--campaign", help="campaign name or id"); i.add_argument("--list", help="lead list name or id (created if missing)")
    i.add_argument("--yes", action="store_true"); i.add_argument("--batch", type=int, default=100); i.add_argument("--verify-on-import", action="store_true")
    i.add_argument("--no-skip-workspace", action="store_true", help="allow leads already elsewhere in the workspace"); i.add_argument("--repush", action="store_true")
    i.add_argument("--all-contacts", action="store_true"); add_selection(i); i.set_defaults(func=cmd_push)
    gh = ss.add_parser("ghl"); gh.add_argument("--location", help="override GHL_LOCATION_ID"); gh.add_argument("--tag", action="append")
    gh.add_argument("--yes", action="store_true"); gh.add_argument("--repush", action="store_true"); gh.add_argument("--all-contacts", action="store_true"); add_selection(gh); gh.set_defaults(func=cmd_push)

    s = sub.add_parser("status", help="pipeline counts and progress"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("report", help="write a self-contained HTML dashboard of the campaign"); s.add_argument("--out"); s.add_argument("--open", action="store_true", help="open in the default browser"); s.set_defaults(func=cmd_report)
    s = sub.add_parser("sample", help="print random leads for review"); s.add_argument("-n", type=int, default=10); s.add_argument("--all", action="store_true"); s.add_argument("--min-score", type=float); s.set_defaults(func=cmd_sample)
    s = sub.add_parser("show", help="dump one company and its contacts"); s.add_argument("company_id", type=int); s.set_defaults(func=cmd_show)
    s = sub.add_parser("missing", help="list companies missing a field (for manual / web research)"); s.add_argument("--field", default="website", choices=["website", "email", "phone"]); s.add_argument("--limit", type=int, default=50); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_missing)
    s = sub.add_parser("sql", help="run SQL against the lead store (read-only unless --write)"); s.add_argument("query"); s.add_argument("--write", action="store_true"); s.add_argument("--limit", type=int, default=200); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_sql)
    s = sub.add_parser("reset", help="delete the database"); s.add_argument("--yes", action="store_true"); s.set_defaults(func=cmd_reset)
    s = sub.add_parser("run", help="full pipeline from icp.json: source -> crawl -> verify -> score -> export")
    s.add_argument("--skip-source", action="store_true"); s.add_argument("--skip-crawl", action="store_true"); s.add_argument("--skip-contacts", action="store_true")
    s.add_argument("--workers", type=int, default=6); s.add_argument("--max-requests", type=int, default=100, help="Google Places request cap")
    s.add_argument("--apollo-pages", type=int, default=1); s.add_argument("--hunter-requests", type=int, default=25); s.set_defaults(func=cmd_run)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to cp1252 and crash on names like "Phở"
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    config.load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
    except SystemExit as e:
        if e.code not in (None, 0) and not isinstance(e.code, int):
            print(f"error: {e.code}", file=sys.stderr)
            return 2
        raise
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("\nstopped. Everything finished so far is saved; run the same command again to continue.", file=sys.stderr)
        return 130
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename or e}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError, TimeoutError) as e:
        reason = getattr(e, "reason", None) or e
        print(f"error: network problem ({reason}). Check the internet connection and run the same command again; "
              "work already done is saved.", file=sys.stderr)
        return 3
    return int(rc) if isinstance(rc, int) else 0
