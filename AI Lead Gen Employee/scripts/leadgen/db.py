"""SQLite lead store. One file, three main tables: companies, contacts, suppression."""
import json
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .util import now_iso, dedup_key, parse_json, normalize_website

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  domain TEXT,
  website TEXT,
  phone TEXT,
  address TEXT, city TEXT, state TEXT, postal_code TEXT, country TEXT,
  lat REAL, lng REAL,
  category TEXT, industry TEXT, employees TEXT, description TEXT,
  rating REAL, review_count INTEGER,
  linkedin_url TEXT, facebook_url TEXT, instagram_url TEXT, twitter_url TEXT, youtube_url TEXT, tiktok_url TEXT,
  yelp_url TEXT, google_maps_url TEXT,
  email_pattern TEXT,
  signals TEXT NOT NULL DEFAULT '{}',
  source TEXT, sources TEXT NOT NULL DEFAULT '[]', source_ref TEXT,
  crawl_status TEXT, crawl_at TEXT, crawl_pages INTEGER NOT NULL DEFAULT 0, crawl_error TEXT,
  contact_providers TEXT NOT NULL DEFAULT '[]',
  score REAL, score_reasons TEXT, qualified INTEGER,
  tags TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_qualified ON companies(qualified);
CREATE INDEX IF NOT EXISTS idx_companies_phone ON companies(phone);
CREATE INDEX IF NOT EXISTS idx_companies_name_city ON companies(lower(name), lower(city));

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  email TEXT,
  email_type TEXT, email_source TEXT, email_confidence INTEGER,
  first_name TEXT, last_name TEXT, title TEXT, seniority TEXT, department TEXT,
  linkedin_url TEXT, phone TEXT,
  verify_status TEXT NOT NULL DEFAULT 'unverified',
  verify_provider TEXT, verify_detail TEXT, verify_at TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'new',
  pushed TEXT NOT NULL DEFAULT '{}',
  source_ref TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);

CREATE TABLE IF NOT EXISTS suppression (
  kind TEXT NOT NULL, value TEXT NOT NULL, reason TEXT, added_at TEXT NOT NULL,
  UNIQUE(kind, value)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  command TEXT NOT NULL, args TEXT, started_at TEXT NOT NULL, finished_at TEXT, stats TEXT
);
CREATE TABLE IF NOT EXISTS dns_cache (
  domain TEXT PRIMARY KEY, has_mx INTEGER, has_a INTEGER, checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL, endpoint TEXT NOT NULL, units INTEGER NOT NULL DEFAULT 1, at TEXT NOT NULL
);
"""

COMPANY_FIELDS = [
    "name", "domain", "website", "phone", "address", "city", "state", "postal_code", "country", "lat", "lng",
    "category", "industry", "employees", "description", "rating", "review_count",
    "linkedin_url", "facebook_url", "instagram_url", "twitter_url", "youtube_url", "tiktok_url", "yelp_url",
    "google_maps_url", "email_pattern", "source_ref", "tags", "notes",
]
CONTACT_FIELDS = [
    "email", "email_type", "email_source", "email_confidence", "first_name", "last_name", "title", "seniority",
    "department", "linkedin_url", "phone", "verify_status", "verify_provider", "verify_detail", "verify_at",
    "source_ref",
]


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def _clean(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


# ---------------------------------------------------------------- companies

def find_company(conn: sqlite3.Connection, domain: str = "", key: str = "", phone: str = "", name: str = "",
                 city: str = "") -> Optional[sqlite3.Row]:
    """Same business from another source: domain, then its dedup key, then phone, then exact name + city.
    The phone and name matches never join two companies whose websites differ."""
    if domain:
        row = conn.execute("SELECT * FROM companies WHERE domain = ?", (domain,)).fetchone()
        if row:
            return row
    if key:
        row = conn.execute("SELECT * FROM companies WHERE dedup_key = ?", (key,)).fetchone()
        if row:
            return row
    compatible = "(domain IS NULL OR domain = '' OR ? = '' OR domain = ?)"
    if phone:
        row = conn.execute(f"SELECT * FROM companies WHERE phone = ? AND {compatible} ORDER BY id LIMIT 1",
                           (phone, domain, domain)).fetchone()
        if row:
            return row
    if name and city:
        return conn.execute(f"SELECT * FROM companies WHERE lower(name) = lower(?) AND lower(city) = lower(?) AND {compatible} "
                            "ORDER BY id LIMIT 1", (name, city, domain, domain)).fetchone()
    return None


def upsert_company(conn: sqlite3.Connection, rec: Dict[str, Any], source: str) -> Tuple[int, bool]:
    """Insert or merge a company. Blank fields on the existing row are filled from rec. Returns (id, created)."""
    rec = {k: _clean(v) for k, v in rec.items() if k in COMPANY_FIELDS}
    name = rec.get("name")
    if not name:
        raise ValueError("company needs a name")
    key = dedup_key(rec.get("domain") or "", rec.get("phone") or "", name, rec.get("city") or "")
    existing = find_company(conn, rec.get("domain") or "", key, rec.get("phone") or "", name, rec.get("city") or "")
    ts = now_iso()
    if existing:
        updates: Dict[str, Any] = {}
        for k, v in rec.items():
            if v in (None, "") or k in ("tags", "notes"):
                continue
            if existing[k] in (None, ""):
                updates[k] = v
        sources = parse_json(existing["sources"], [])
        if source and source not in sources:
            sources.append(source)
            updates["sources"] = json.dumps(sources)
        if rec.get("tags"):
            cur = set(t for t in (existing["tags"] or "").split(",") if t)
            cur.update(t for t in rec["tags"].split(",") if t)
            updates["tags"] = ",".join(sorted(cur))
        if updates:
            updates["updated_at"] = ts
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", (*updates.values(), existing["id"]))
        return int(existing["id"]), False
    cols = ["dedup_key", "source", "sources", "created_at", "updated_at"] + list(rec.keys())
    vals = [key, source, json.dumps([source] if source else []), ts, ts] + list(rec.values())
    cur = conn.execute(f"INSERT INTO companies ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    return int(cur.lastrowid), True


def update_company(conn: sqlite3.Connection, company_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", (*fields.values(), company_id))


def get_company(conn: sqlite3.Connection, company_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()


def company_contacts(conn: sqlite3.Connection, company_id: int) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts WHERE company_id = ? ORDER BY is_primary DESC, id", (company_id,)).fetchall()


# ---------------------------------------------------------------- contacts

def upsert_contact(conn: sqlite3.Connection, company_id: int, rec: Dict[str, Any]) -> Tuple[int, bool]:
    """Insert or merge a contact. Matched by email, else by (company, first, last). Returns (id, created)."""
    rec = {k: _clean(v) for k, v in rec.items() if k in CONTACT_FIELDS}
    email = rec.get("email")
    ts = now_iso()
    existing = None
    if email:
        existing = conn.execute("SELECT * FROM contacts WHERE email = ?", (email,)).fetchone()
    if existing is None and rec.get("first_name") and rec.get("last_name"):
        existing = conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? AND lower(first_name) = ? AND lower(last_name) = ? "
            "AND (email IS NULL OR email = ?) ORDER BY id LIMIT 1",
            (company_id, rec["first_name"].lower(), rec["last_name"].lower(), email or ""),
        ).fetchone()
    if existing:
        updates: Dict[str, Any] = {}
        for k, v in rec.items():
            if v in (None, ""):
                continue
            if existing[k] in (None, "", "unverified") and k != "verify_status":
                updates[k] = v
            elif k == "verify_status" and existing["verify_status"] in ("unverified", "unknown") and v not in ("unverified",):
                updates[k] = v
            elif k == "email_confidence" and existing[k] is not None and v is not None and int(v) > int(existing[k]):
                updates[k] = v
        if updates:
            updates["updated_at"] = ts
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE contacts SET {sets} WHERE id = ?", (*updates.values(), existing["id"]))
        return int(existing["id"]), False
    cols = ["company_id", "created_at", "updated_at"] + list(rec.keys())
    vals = [company_id, ts, ts] + list(rec.values())
    suppressed = conn.execute(
        "SELECT 1 FROM suppression WHERE (kind = 'email' AND value = ?) OR (kind = 'domain' AND value = ?) OR "
        "(kind = 'domain' AND value = (SELECT domain FROM companies WHERE id = ?)) LIMIT 1",
        ((email or "").lower(), (email or "").rsplit("@", 1)[-1].lower() if email else "", company_id)).fetchone()
    if suppressed:
        cols.append("status")
        vals.append("do_not_contact")
    cur = conn.execute(f"INSERT INTO contacts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    return int(cur.lastrowid), True


def update_contact(conn: sqlite3.Connection, contact_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE contacts SET {sets} WHERE id = ?", (*fields.values(), contact_id))


# ---------------------------------------------------------------- suppression

def suppress(conn: sqlite3.Connection, kind: str, value: str, reason: str = "") -> bool:
    value = value.strip().lower()
    if kind == "domain":  # "www.x.com", "https://x.com/" and "x.com" all mean x.com
        value = normalize_website(value)[1] or value.split("@")[-1].strip("/")
    if not value:
        return False
    cur = conn.execute("INSERT OR IGNORE INTO suppression (kind, value, reason, added_at) VALUES (?, ?, ?, ?)",
                       (kind, value, reason, now_iso()))
    if kind == "email":
        conn.execute("UPDATE contacts SET status = 'do_not_contact', updated_at = ? WHERE email = ?", (now_iso(), value))
    elif kind == "domain":
        conn.execute("UPDATE contacts SET status = 'do_not_contact', updated_at = ? WHERE company_id IN "
                     "(SELECT id FROM companies WHERE domain = ?) OR lower(email) LIKE ?", (now_iso(), value, "%@" + value))
    return cur.rowcount > 0


def suppression_sets(conn: sqlite3.Connection) -> Tuple[set, set]:
    emails, domains = set(), set()
    for row in conn.execute("SELECT kind, value FROM suppression"):
        (emails if row["kind"] == "email" else domains).add(row["value"])
    return emails, domains


# ---------------------------------------------------------------- runs / usage

def start_run(conn: sqlite3.Connection, command: str, args: Dict[str, Any]) -> int:
    cur = conn.execute("INSERT INTO runs (command, args, started_at) VALUES (?, ?, ?)",
                       (command, json.dumps(args, default=str), now_iso()))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, stats: Dict[str, Any]) -> None:
    conn.execute("UPDATE runs SET finished_at = ?, stats = ? WHERE id = ?",
                 (now_iso(), json.dumps(stats, default=str), run_id))
    conn.commit()


def log_usage(conn: sqlite3.Connection, provider: str, endpoint: str, units: int = 1) -> None:
    conn.execute("INSERT INTO api_usage (provider, endpoint, units, at) VALUES (?, ?, ?, ?)",
                 (provider, endpoint, units, now_iso()))


def usage_summary(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT provider, endpoint, SUM(units) AS units, COUNT(*) AS calls FROM api_usage "
                        "GROUP BY provider, endpoint ORDER BY provider, endpoint").fetchall()


# ---------------------------------------------------------------- dns cache

def dns_cached(conn: sqlite3.Connection, domain: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM dns_cache WHERE domain = ?", (domain,)).fetchone()


def dns_store(conn: sqlite3.Connection, domain: str, has_mx: Optional[bool], has_a: Optional[bool]) -> None:
    conn.execute("INSERT OR REPLACE INTO dns_cache (domain, has_mx, has_a, checked_at) VALUES (?, ?, ?, ?)",
                 (domain, None if has_mx is None else int(has_mx), None if has_a is None else int(has_a), now_iso()))


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]
