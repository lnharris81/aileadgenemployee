"""Import companies (and optional contacts) from any CSV. Headers are auto-mapped; override with --map."""
import csv
import io
import math
import sys
from typing import Any, Dict, List, Optional

from .. import db
from ..util import clean_email, classify_email
from . import base_record

ALIASES: Dict[str, List[str]] = {
    "name": ["name", "company", "company name", "company_name", "business", "business name", "business_name",
             "organization", "organisation", "account", "account name", "practice", "firm"],
    "website": ["website", "url", "site", "web", "domain", "company website", "website url", "homepage", "web address"],
    "phone": ["phone", "telephone", "phone number", "phone_number", "tel", "company phone", "mobile", "main phone"],
    "email": ["email", "e-mail", "email address", "email_address", "contact email", "work email"],
    "address": ["address", "street", "address1", "address 1", "street address"],
    "city": ["city", "town", "locality"],
    "state": ["state", "province", "region", "state/province", "county"],
    "postal_code": ["zip", "zipcode", "zip code", "postal", "postal code", "postcode", "postal_code"],
    "country": ["country", "country code"],
    "category": ["category", "type", "business type", "niche", "vertical", "sector"],
    "industry": ["industry"],
    "employees": ["employees", "employee count", "headcount", "size", "company size", "# employees"],
    "description": ["description", "about", "summary", "notes"],
    "linkedin_url": ["linkedin", "linkedin url", "company linkedin", "linkedin_url"],
    "facebook_url": ["facebook", "facebook url"],
    "instagram_url": ["instagram", "instagram url"],
    "rating": ["rating", "stars", "google rating"],
    "review_count": ["reviews", "review count", "review_count", "num reviews"],
    "first_name": ["first name", "first_name", "firstname", "first", "contact first name"],
    "last_name": ["last name", "last_name", "lastname", "last", "surname", "contact last name"],
    "title": ["title", "job title", "job_title", "position", "role"],
    "contact_linkedin": ["person linkedin", "contact linkedin", "linkedin profile", "profile url"],
    "source_ref": ["source", "source url", "source_ref", "listing url", "ref", "id"],
}


def auto_map(headers: List[str], overrides: Dict[str, str]) -> Dict[str, str]:
    """Return {field: header}."""
    norm = {h.strip().lower(): h for h in headers}
    mapping: Dict[str, str] = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in norm:
                mapping[field] = norm[n]
                break
    for field, header in overrides.items():
        if header not in headers:
            raise SystemExit(f"--map {field}={header}: column '{header}' not in CSV headers {headers}")
        mapping[field] = header
    return mapping


def _read_text(path: str) -> str:
    """UTF-8 (with or without BOM) first, then the encodings Excel on Windows and Mac write."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252", "mac_roman"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _dialect(sample: str):
    """Comma, semicolon (European Excel), tab, or pipe separated."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def run(conn, icp: Dict[str, Any], path: str, overrides: Optional[Dict[str, str]] = None, source: str = "csv",
        default_category: Optional[str] = None, limit: Optional[int] = None, dry_run: bool = False,
        log=print) -> Dict[str, Any]:
    country = icp["geography"].get("country") or "US"
    text = _read_text(path)
    with io.StringIO(text, newline="") as fh:
        reader = csv.DictReader(fh, dialect=_dialect(text[:20000]))
        headers = reader.fieldnames or []
        mapping = auto_map(headers, overrides or {})
        if "name" not in mapping:
            raise SystemExit(f"Could not find a company name column in {headers}. Use --map name=<column>.")
        log(f"  column map: {mapping}")
        stats = {"rows": 0, "created": 0, "merged": 0, "contacts": 0, "skipped": 0}
        if dry_run:
            return stats
        for row in reader:
            stats["rows"] += 1
            g = lambda f: (row.get(mapping[f]) or "").strip() if f in mapping else ""
            if not g("name"):
                stats["skipped"] += 1
                continue
            rec = base_record(
                g("name"), g("website"), g("phone"), g("country") or country,
                address=g("address") or None, city=g("city") or None, state=g("state") or None,
                postal_code=g("postal_code") or None, category=g("category") or default_category,
                industry=g("industry") or None, employees=g("employees") or None, description=g("description") or None,
                linkedin_url=g("linkedin_url") or None, facebook_url=g("facebook_url") or None,
                instagram_url=g("instagram_url") or None, source_ref=g("source_ref") or f"{source}:{path.split('/')[-1]}#{stats['rows']}",
            )
            for numf in ("rating", "review_count"):
                v = g(numf)
                if v:
                    try:
                        num = float(v.replace(",", "") if numf == "review_count" else v)  # "1,234" reviews; "4,5" is not a rating
                    except ValueError:
                        continue
                    if math.isfinite(num):
                        rec[numf] = num if numf == "rating" else int(num)
            cid, created = db.upsert_company(conn, rec, source)
            stats["created" if created else "merged"] += 1
            email = clean_email(g("email"))
            if email or (g("first_name") and g("last_name")):
                db.upsert_contact(conn, cid, {
                    "email": email or None,
                    "email_type": classify_email(email, rec.get("domain", "")) if email else None,
                    "email_source": source if email else None, "email_confidence": 75 if email else None,
                    "first_name": g("first_name") or None, "last_name": g("last_name") or None,
                    "title": g("title") or None, "linkedin_url": g("contact_linkedin") or None,
                    "source_ref": rec["source_ref"],
                })
                stats["contacts"] += 1
            if limit and stats["created"] >= limit:
                break
        conn.commit()
    return stats
