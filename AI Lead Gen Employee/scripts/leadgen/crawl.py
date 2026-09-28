"""Polite website crawler: homepage + contact/about/team pages. Extracts emails, phones, socials, signals.

Honors robots.txt, one site at a time per worker, small page budget, short timeouts.
"""
import concurrent.futures
import json
import re
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set, Tuple

from . import db
from .util import (EMAIL_RE, clean_email, classify_email, http_request, normalize_phone, social_field_for,
                   user_agent, HttpError)

CONTACT_HINT = re.compile(
    r"(contact|about|team|staff|our-team|ourteam|meet|leadership|people|who-we-are|impressum|kontakt|management|"
    r"doctors|dentists|providers|attorneys|lawyers|agents|physicians|founder|owner|locations|get-in-touch|reach-us)", re.I)
PRIORITY = ["contact", "kontakt", "about", "team", "staff", "meet", "leadership", "people", "doctors", "providers",
            "attorneys", "agents", "impressum", "locations"]
FALLBACK_PATHS = ["/contact", "/contact-us", "/about", "/about-us"]
MAX_BYTES = 1_500_000

SIGNAL_PATTERNS = {
    "booking_widget": r"calendly\.com|acuityscheduling|booksy\.com|mindbodyonline|vagaro\.com|zocdoc\.com|setmore\.com|"
                      r"squareup\.com/appointments|square\.site/book|housecallpro|getjobber|servicetitan|schedulicity|"
                      r"simplybook|appointy|nexhealth|localmed|solutionreach|patientpop|tebra|kareo|healow|"
                      r"book(?:-|\s)?(?:online|now|an appointment)|schedule(?:-|\s)?(?:online|now)|reserve(?:-|\s)?online",
    "chat_widget": r"intercom|drift\.com|tawk\.to|tidio|crisp\.chat|livechatinc|podium\.com|birdeye|smith\.ai|"
                   r"hubspot.{0,40}messages|zendesk.{0,40}web_widget|freshchat|manychat|olark|purechat|chatra|gorgias|"
                   r"leadconnectorhq.{0,60}chat|msgsndr.{0,60}chat|widgets\.leadconnectorhq",
    "analytics_pixel": r"googletagmanager|gtag\(|google-analytics|fbq\(|connect\.facebook\.net|clarity\.ms|hotjar",
    "cms_wordpress": r"wp-content|wp-includes|wp-json",
    "cms_wix": r"wix\.com|wixstatic|parastorage|wixsite",
    "cms_squarespace": r"squarespace",
    "cms_shopify": r"cdn\.shopify|shopify",
    "cms_godaddy": r"godaddy|secureserver\.net|img1\.wsimg|wsimg\.com",
    "cms_weebly": r"weebly",
    "cms_webflow": r"webflow",
    "cms_duda": r"cdn-website\.com|dudamobile|duda\.co",
    "cms_hubspot": r"hs-scripts|hubspot",
    "cms_ghl": r"leadconnectorhq|msgsndr|funnels\.|gohighlevel",
    "ecommerce": r"add-to-cart|add_to_cart|cart\.js|woocommerce|cdn\.shopify",
    "reviews_widget": r"birdeye|podium|reviews\.io|trustpilot|yotpo|elfsight.{0,40}review",
    "email_marketing": r"activehosted|mailchimp|klaviyo|constantcontact|list-manage\.com|hs-forms|convertkit",
    "ai_or_chatbot": r"chatbot|voiceflow|botpress|manychat|smith\.ai|conversational ai|ai assistant|ai receptionist",
    "financing_or_pricing": r"carecredit|affirm\.com|klarna|financing|pricing",
    "hiring": r"we(?:'|&#8217;|’)?re hiring|now hiring|join our team|careers",
}
_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|&#169;|copyright)\s*(?:\(c\)\s*)?(?:\d{4}\s*[-–]\s*)?(20\d{2})", re.I)
_YEAR_RANGE_RE = re.compile(r"(?:©|&copy;|copyright)[^<]{0,40}?(20\d{2})", re.I)
_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b[2-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_desc = ""
        self.links: List[Tuple[str, str]] = []
        self.mailtos: Set[str] = set()
        self.tels: Set[str] = set()
        self.cf_emails: Set[str] = set()
        self.has_form = False
        self.has_viewport = False
        self.generator = ""
        self.jsonld: List[str] = []
        self.text: List[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._skip = 0
        self._cur_link: Optional[int] = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if a.get("data-cfemail"):
            self.cf_emails.add(a["data-cfemail"])
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and not self.meta_desc:
                self.meta_desc = a.get("content", "").strip()
            elif name == "viewport":
                self.has_viewport = True
            elif name == "generator":
                self.generator = a.get("content", "")
        elif tag == "a":
            href = a.get("href", "").strip()
            low = href.lower()
            if low.startswith("mailto:"):
                self.mailtos.add(href[7:])
            elif low.startswith("tel:"):
                self.tels.add(href[4:])
            elif href and not low.startswith(("javascript:", "#")):
                self.links.append((href, ""))
                self._cur_link = len(self.links) - 1
        elif tag == "script":
            if (a.get("type") or "").lower() == "application/ld+json":
                self._in_jsonld = True
            else:
                self._skip += 1
        elif tag in ("style", "noscript", "svg"):
            self._skip += 1
        elif tag == "form":
            self.has_form = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            if self._in_jsonld:
                self._in_jsonld = False
            elif self._skip > 0:
                self._skip -= 1
        elif tag in ("style", "noscript", "svg"):
            if self._skip > 0:
                self._skip -= 1
        elif tag == "a":
            self._cur_link = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_jsonld:
            self.jsonld.append(data)
        elif self._skip == 0:
            if data.strip():
                self.text.append(data.strip())
            if self._cur_link is not None:
                href, txt = self.links[self._cur_link]
                self.links[self._cur_link] = (href, (txt + " " + data.strip()).strip()[:120])


def decode_cfemail(hexstr: str) -> str:
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except (ValueError, IndexError):
        return ""


def extract_emails(html: str, ex: _Extractor) -> Set[str]:
    found: Set[str] = set()
    for m in ex.mailtos:
        for part in m.split(","):
            e = clean_email(part)
            if e:
                found.add(e)
    for h in ex.cf_emails:
        e = clean_email(decode_cfemail(h))
        if e:
            found.add(e)
    for blob in ex.jsonld:
        for m in EMAIL_RE.findall(blob):
            e = clean_email(m)
            if e:
                found.add(e)
    # raw-HTML pass: drop comments (agency credits) and form placeholders, and unescape inline JSON/JS
    # so "\triverside@x.com" does not read as "triverside@x.com"
    raw = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    raw = re.sub(r"\bplaceholder\s*=\s*(?:\"[^\"]*\"|'[^']*')", " ", raw, flags=re.I)
    raw = re.sub(r"\\u0040", "@", raw, flags=re.I)
    raw = re.sub(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[nrtfbv/\\])", " ", raw)
    # de-obfuscated forms: "name [at] domain [dot] com", "name(at)domain.com"
    deob = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", raw, flags=re.I)
    deob = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", deob, flags=re.I)
    for m in EMAIL_RE.findall(deob):
        e = clean_email(m)
        if e:
            found.add(e)
    return found


def fetch(url: str, timeout: int = 15) -> Tuple[str, int, str]:
    """Return (final_url, status, html). Raises on network failure."""
    status, headers, body, final = http_request(
        "GET", url, {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5", "Accept-Language": "en"},
        timeout=timeout, retries=1, retry_statuses=(429, 503), allow_statuses=(400, 401, 403, 404, 405, 406, 410, 500, 502),
        insecure_fallback=True, max_bytes=MAX_BYTES)
    ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if status == 200 and ("html" not in ctype and "xml" not in ctype and ctype):
        return final, status, ""
    charset = "utf-8"
    m = re.search(r"charset=([\w\-]+)", ctype)
    if m:
        charset = m.group(1)
    try:
        return final, status, body.decode(charset, "replace")
    except LookupError:
        return final, status, body.decode("utf-8", "replace")


def _robots_ok(base: str, path: str, cache: Dict[str, Any]) -> bool:
    host = urllib.parse.urlsplit(base).netloc
    rp = cache.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _s, _h, body, _u = http_request("GET", urllib.parse.urljoin(base, "/robots.txt"), timeout=8, retries=0,
                                            allow_statuses=(400, 401, 403, 404, 410, 500, 502, 503),
                                            insecure_fallback=True, max_bytes=200_000)
            rp.parse(body.decode("utf-8", "replace").splitlines() if _s == 200 else [])
        except Exception:
            rp.parse([])
        cache[host] = rp
    try:
        return rp.can_fetch("LeadGenEmployee", urllib.parse.urljoin(base, path))
    except Exception:
        return True


def pick_pages(base: str, links: List[Tuple[str, str]], max_extra: int) -> List[str]:
    host = urllib.parse.urlsplit(base).netloc.lower().replace("www.", "")
    scored: List[Tuple[int, str]] = []
    seen: Set[str] = set()
    for href, text in links:
        full = urllib.parse.urljoin(base, href)
        p = urllib.parse.urlsplit(full)
        if p.scheme not in ("http", "https") or p.netloc.lower().replace("www.", "") != host:
            continue
        path = p.path.rstrip("/") or "/"
        if path == "/" or path.lower().endswith((".pdf", ".jpg", ".png", ".zip", ".mp4")):
            continue
        key = path.lower()
        if key in seen:
            continue
        hay = (path + " " + text).lower()
        if not CONTACT_HINT.search(hay):
            continue
        seen.add(key)
        rank = next((i for i, w in enumerate(PRIORITY) if w in hay), len(PRIORITY))
        scored.append((rank, f"{p.scheme}://{p.netloc}{path}"))
    scored.sort()
    return [u for _r, u in scored[:max_extra]]


def detect_signals(all_html: str, final_url: str, ex_home: _Extractor, page_count: int, emails_found: bool) -> Dict[str, Any]:
    low = all_html.lower()
    sig: Dict[str, Any] = {}
    for name, pat in SIGNAL_PATTERNS.items():
        if re.search(pat, low):
            sig[name] = True
    years = [int(y) for y in _COPYRIGHT_RE.findall(all_html)] + [int(y) for y in _YEAR_RANGE_RE.findall(all_html)]
    if years:
        y = max(years)
        sig["copyright_year"] = y
        if y < datetime.now().year - 1:
            sig["site_stale"] = True
    sig["https"] = final_url.startswith("https://")
    sig["mobile_viewport"] = ex_home.has_viewport
    sig["has_form"] = ex_home.has_form or "<form" in low
    sig["pages_crawled"] = page_count
    sig["email_on_site"] = emails_found
    cms = [k for k in sig if k.startswith("cms_")]
    if cms:
        sig["cms"] = cms[0][4:]
    if ex_home.generator:
        sig["generator"] = ex_home.generator[:60]
    return sig


def crawl_site(website: str, max_pages: int = 6, delay: float = 0.6, robots_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Crawl one site. Returns dict with emails{email: url}, phones, socials, title, description, signals, pages, error."""
    robots_cache = robots_cache if robots_cache is not None else {}
    out: Dict[str, Any] = {"emails": {}, "phones": [], "socials": {}, "title": "", "description": "",
                           "signals": {}, "pages": 0, "error": None, "final_url": website, "status": None}
    if not _robots_ok(website, urllib.parse.urlsplit(website).path or "/", robots_cache):
        out["error"] = "robots_disallowed"  # the site asked crawlers to stay out, homepage included
        return out
    try:
        final, status, html = fetch(website)
    except HttpError as e:
        out["error"] = f"http_{e.status}"
        return out
    except Exception as e:
        out["error"] = type(e).__name__.lower()[:40]
        return out
    out["status"] = status
    if status != 200 or not html:
        out["error"] = f"http_{status}" if status != 200 else "not_html"
        return out
    out["final_url"] = final
    base = final
    ex = _Extractor()
    try:
        ex.feed(html)
    except Exception:
        pass
    all_html = [html]
    out["title"] = re.sub(r"\s+", " ", ex.title).strip()[:200]
    out["description"] = re.sub(r"\s+", " ", ex.meta_desc).strip()[:500]
    pages = 1
    for e in extract_emails(html, ex):
        out["emails"].setdefault(e, final)
    tels = set(ex.tels)
    for href, _t in ex.links:
        f = social_field_for(href) if "://" in href else None
        if f and f not in out["socials"]:
            out["socials"][f] = href.split("?")[0][:200]
    candidates = pick_pages(base, ex.links, max_pages - 1)
    if not candidates:
        candidates = [urllib.parse.urljoin(base, p) for p in FALLBACK_PATHS[:2]]
    for url in candidates:
        if pages >= max_pages:
            break
        if not _robots_ok(base, urllib.parse.urlsplit(url).path, robots_cache):
            continue
        time.sleep(delay)
        try:
            _f, st, h2 = fetch(url, timeout=12)
        except Exception:
            continue
        if st != 200 or not h2:
            continue
        pages += 1
        ex2 = _Extractor()
        try:
            ex2.feed(h2)
        except Exception:
            continue
        all_html.append(h2)
        for e in extract_emails(h2, ex2):
            out["emails"].setdefault(e, url)
        tels.update(ex2.tels)
        for href, _t in ex2.links:
            f = social_field_for(href) if "://" in href else None
            if f and f not in out["socials"]:
                out["socials"][f] = href.split("?")[0][:200]
    phones = []
    for t in tels:
        p = normalize_phone(urllib.parse.unquote(t).split("?")[0])
        if p and p not in phones:
            phones.append(p)
    if not phones:
        text = " ".join(ex.text)
        for m in _PHONE_RE.findall(text)[:3]:
            p = normalize_phone(m)
            if p and p not in phones:
                phones.append(p)
    out["phones"] = phones
    out["pages"] = pages
    out["signals"] = detect_signals("\n".join(all_html), final, ex, pages, bool(out["emails"]))
    return out


def _confidence(email: str, etype: str) -> int:
    return {"personal": 85, "role": 80, "personal_webmail": 65, "third_party": 25}.get(etype, 50)


def run(conn, limit: Optional[int] = None, workers: int = 6, recrawl: bool = False, max_pages: int = 6,
        only_ids: Optional[List[int]] = None, delay: float = 0.6, retry_errors: bool = False, log=print) -> Dict[str, Any]:
    workers = max(1, int(workers or 1))
    where = "website IS NOT NULL AND website != ''"
    if retry_errors:
        where += " AND (crawl_status IS NULL OR crawl_status != 'ok')"
    elif not recrawl:
        where += " AND crawl_status IS NULL"
    if only_ids:
        where += f" AND id IN ({','.join(str(int(i)) for i in only_ids)})"
    sql = f"SELECT id, name, website, domain FROM companies WHERE {where} ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    stats = {"companies": len(rows), "ok": 0, "errors": 0, "emails": 0, "new_contacts": 0, "phones_added": 0}
    if not rows:
        log("  nothing to crawl (every site is crawled; --retry-errors retries failed sites, --recrawl redoes all)")
        return stats
    log(f"  crawling {len(rows)} sites with {workers} workers, up to {max_pages} pages each ...")
    robots_cache: Dict[str, Any] = {}
    done = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(crawl_site, r["website"], max_pages, delay, robots_cache): r for r in rows}
        for fut in concurrent.futures.as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # never let one site kill the run
                res = {"error": type(e).__name__, "emails": {}, "phones": [], "socials": {}, "signals": {}, "pages": 0,
                       "title": "", "description": "", "final_url": r["website"]}
            done += 1
            fields: Dict[str, Any] = {"crawl_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      "crawl_pages": res.get("pages", 0)}
            if res.get("error"):
                fields["crawl_status"] = "error"
                fields["crawl_error"] = res["error"]
                stats["errors"] += 1
            else:
                fields["crawl_status"] = "ok"
                fields["crawl_error"] = None
                fields["signals"] = json.dumps(res["signals"])
                stats["ok"] += 1
                comp = db.get_company(conn, r["id"])
                if comp is not None:
                    if not comp["description"] and (res["description"] or res["title"]):
                        fields["description"] = res["description"] or res["title"]
                    if not comp["phone"] and res["phones"]:
                        fields["phone"] = res["phones"][0]
                        stats["phones_added"] += 1
                    for f, url in res["socials"].items():
                        if not comp[f]:
                            fields[f] = url
                    for email, page in res["emails"].items():
                        etype = classify_email(email, r["domain"] or "", r["name"] or "")
                        _cid, created = db.upsert_contact(conn, r["id"], {
                            "email": email, "email_type": etype, "email_source": "crawl",
                            "email_confidence": _confidence(email, etype), "source_ref": page[:300]})
                        stats["emails"] += 1
                        if created:
                            stats["new_contacts"] += 1
            db.update_company(conn, r["id"], **fields)
            if done % 10 == 0 or done == len(rows):
                conn.commit()
                el = time.time() - t0
                log(f"    {done}/{len(rows)} sites | ok {stats['ok']} err {stats['errors']} | emails {stats['emails']} | {el:.0f}s")
    conn.commit()
    return stats
