"""Shared helpers: HTTP with retries, .env loading, domain / phone / email normalization, DNS."""
import gzip
import json
import os
import random
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def user_agent() -> str:
    contact = os.environ.get("CRAWLER_CONTACT", "").strip()
    base = "LeadGenEmployee/1.0 (lead research; respects robots.txt"
    return base + (f"; {contact})" if contact else ")")


# ---------------------------------------------------------------- .env

def load_dotenv(path: str) -> int:
    """Load KEY=VALUE lines into os.environ without overriding existing vars. Returns count loaded."""
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if key and val and key not in os.environ:
                os.environ[key] = val
                n += 1
    return n


# ---------------------------------------------------------------- HTTP

class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body


def http_request(method: str, url: str, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None,
                 timeout: int = 30, retries: int = 3, retry_statuses=(429, 500, 502, 503, 504),
                 backoff: float = 1.5, allow_statuses=(), insecure_fallback: bool = False,
                 max_bytes: Optional[int] = None) -> Tuple[int, Dict[str, str], bytes, str]:
    """Return (status, headers, body, final_url). Retries on network errors and retry_statuses."""
    hdrs = {"User-Agent": user_agent(), "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    ctx = ssl.create_default_context()
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read(max_bytes) if max_bytes else resp.read()
                if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                    try:
                        body = gzip.decompress(body)
                    except Exception:
                        pass
                return resp.status, dict(resp.headers), body, resp.geturl()
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code in allow_statuses:
                return e.code, dict(e.headers or {}), body, url
            last_err = HttpError(e.code, url, body.decode("utf-8", "replace"))
            if e.code in retry_statuses and attempt < retries:
                ra = e.headers.get("Retry-After") if e.headers else None
                sleep = float(ra) if ra and ra.strip().isdigit() else backoff * (2 ** attempt) + random.random()
                time.sleep(min(sleep, 60))
                continue
            raise last_err
        except ssl.SSLCertVerificationError as e:
            if insecure_fallback and ctx.verify_mode != ssl.CERT_NONE:
                ctx = ssl._create_unverified_context()  # public pages only; never used for API calls
                continue
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt) + random.random())
                continue
            raise
    assert last_err is not None
    raise last_err


def http_json(method: str, url: str, headers: Optional[Dict[str, str]] = None, body: Any = None,
              params: Optional[Dict[str, Any]] = None, timeout: int = 30, retries: int = 3) -> Any:
    """JSON in, JSON out. Query params appended when given."""
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "", [])}
        if clean:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    status, _h, raw, _u = http_request(method, url, hdrs, data, timeout=timeout, retries=retries)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HttpError(status, url, "non-JSON response: " + raw[:200].decode("utf-8", "replace"))


class RateLimiter:
    """Simple per-process throttle: at most `per_second` calls per second."""

    def __init__(self, per_second: float):
        self.min_gap = 1.0 / per_second if per_second > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_gap <= 0:
            return
        gap = time.monotonic() - self._last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last = time.monotonic()


# ---------------------------------------------------------------- websites / domains

PLATFORM_HOSTS = {
    "facebook.com": "facebook_url", "fb.com": "facebook_url", "m.facebook.com": "facebook_url",
    "instagram.com": "instagram_url",
    "linkedin.com": "linkedin_url",
    "twitter.com": "twitter_url", "x.com": "twitter_url",
    "youtube.com": "youtube_url", "youtu.be": "youtube_url",
    "tiktok.com": "tiktok_url",
    "yelp.com": "yelp_url",
}
# Listing / aggregator hosts that are not the business's own site.
NON_COMPANY_HOSTS = {
    "google.com", "goo.gl", "g.page", "maps.app.goo.gl", "bing.com", "yahoo.com", "linktr.ee",
    "nextdoor.com", "angi.com", "homeadvisor.com", "thumbtack.com", "houzz.com", "zillow.com",
    "realtor.com", "tripadvisor.com", "doordash.com", "ubereats.com", "grubhub.com", "booksy.com",
    "vagaro.com", "mindbodyonline.com", "zocdoc.com", "healthgrades.com", "psychologytoday.com",
    "avvo.com", "justia.com", "findlaw.com", "lawyers.com", "yellowpages.com", "bbb.org",
    "mapquest.com", "foursquare.com", "opentable.com", "resy.com", "toasttab.com", "wa.me",
    "whatsapp.com", "t.me", "apple.com", "wikipedia.org",
}
# Site builders where the host is per-business but the domain is useless for email lookups.
SITE_BUILDER_SUFFIXES = (
    ".wixsite.com", ".square.site", ".business.site", ".godaddysites.com", ".weebly.com",
    ".webnode.com", ".webnode.page", ".wordpress.com", ".blogspot.com", ".squarespace.com",
    ".mystrikingly.com", ".carrd.co", ".webflow.io", ".my.canva.site", ".jimdosite.com",
    ".ueniweb.com", ".setmore.com", ".site123.me", ".yolasite.com",
)


def _host_of(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.netloc or p.path.split("/")[0]).lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _matches_host(host: str, table) -> Optional[str]:
    parts = host.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in table:
            return cand
    return None


def normalize_website(raw: Optional[str]) -> Tuple[str, str, str]:
    """Return (website, domain, kind). kind: 'site', 'social', 'non_company', or '' when empty/invalid.

    website keeps the scheme (https added when missing). domain drops 'www.'.
    """
    if not raw:
        return "", "", ""
    s = raw.strip().strip("<>\"' ")
    if not s or " " in s.split("?")[0] or "@" in s.split("/")[0]:
        return "", "", ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
        s = "https://" + s
    parts = urllib.parse.urlsplit(s)
    if parts.scheme not in ("http", "https"):
        return "", "", ""
    host = _host_of(s)
    if not host or "." not in host or len(host) > 253:
        return "", "", ""
    if _matches_host(host, PLATFORM_HOSTS):
        return s, "", "social"
    if _matches_host(host, NON_COMPANY_HOSTS):
        return s, "", "non_company"
    path = parts.path.rstrip("/")
    website = f"{parts.scheme}://{host}{path}"
    return website, host, "site"


def is_site_builder_domain(domain: str) -> bool:
    return any(domain.endswith(sfx) for sfx in SITE_BUILDER_SUFFIXES)


def social_field_for(url: str) -> Optional[str]:
    host = _host_of(url)
    key = _matches_host(host, PLATFORM_HOSTS)
    return PLATFORM_HOSTS[key] if key else None


# ---------------------------------------------------------------- phones

def normalize_phone(raw: Optional[str], country: str = "US") -> str:
    if not raw:
        return ""
    raw = raw.strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits if 7 <= len(digits) <= 15 else ""
    if country.upper() in ("US", "CA"):
        if len(digits) == 10:
            return "+1" + digits
        if len(digits) == 11 and digits[0] == "1":
            return "+" + digits
    if country.upper() in ("GB", "UK") and digits.startswith("0") and len(digits) in (10, 11):
        return "+44" + digits[1:]
    if country.upper() == "AU" and digits.startswith("0") and len(digits) == 10:
        return "+61" + digits[1:]
    return digits if 7 <= len(digits) <= 15 else ""


# ---------------------------------------------------------------- names / dedup

_SUFFIX_TOKENS = {"llc", "inc", "ltd", "co", "corp", "corporation", "company", "pllc", "pc", "pa", "dds",
                  "dmd", "md", "the", "and", "of", "llp", "lp", "plc", "gmbh", "pty", "limited", "incorporated"}


def slug_name(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    tokens = [t for t in tokens if t not in _SUFFIX_TOKENS]
    return "-".join(tokens)


def dedup_key(domain: str, phone: str, name: str, city: str) -> str:
    if domain:
        return "d:" + domain
    if phone:
        return "p:" + phone
    return "n:" + slug_name(name) + "|" + slug_name(city or "")


# ---------------------------------------------------------------- emails

EMAIL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24}")

ROLE_PREFIXES = {
    "info", "contact", "hello", "hi", "sales", "office", "admin", "support", "help", "billing", "careers",
    "jobs", "press", "media", "marketing", "hr", "team", "enquiries", "inquiries", "enquiry", "inquiry",
    "reception", "frontdesk", "bookings", "booking", "appointments", "appointment", "service", "services",
    "customerservice", "mail", "email", "general", "webmaster", "postmaster", "noreply", "no-reply",
    "donotreply", "newsletter", "orders", "accounts", "accounting", "finance", "legal", "privacy",
    "security", "abuse", "feedback", "questions", "schedule", "scheduling", "staff", "management",
    "reservations", "events", "care", "patients", "patient", "clinic", "front", "desk", "welcome", "ask",
}
WEBMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "comcast.net", "att.net", "sbcglobal.net",
    "verizon.net", "bellsouth.net", "cox.net", "charter.net", "protonmail.com", "proton.me", "mail.com",
    "gmx.com", "gmx.net", "yahoo.co.uk", "hotmail.co.uk", "outlook.co.uk", "btinternet.com", "rocketmail.com",
    "zoho.com", "hey.com", "fastmail.com", "earthlink.net", "optonline.net", "roadrunner.com", "rr.com",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com",
    "sharklasers.com", "trashmail.com", "getnada.com", "dispostable.com", "fakeinbox.com", "maildrop.cc",
    "throwawaymail.com", "mohmal.com", "emailondeck.com", "mintemail.com", "tempr.email", "discard.email",
    "spamgourmet.com", "guerrillamail.net", "grr.la", "mailnesia.com", "tempail.com", "burnermail.io",
}
JUNK_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "yourdomain.com", "email.com", "yoursite.com",
    "company.com", "test.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "sentry.wixpress.com",
    "mysite.com", "website.com", "address.com", "mail.com.invalid", "domain.tld", "site.com", "yourcompany.com",
    "emailaddress.com", "youremail.com", "yourname.com", "placeholder.com", "2x.png", "w3.org", "schema.org",
    "googleapis.com", "gstatic.com", "cloudflare.com", "jquery.com", "wordpress.org", "wp.com", "npmjs.com",
    "github.com", "gravatar.com", "godaddy.com", "squarespace.com", "wix.com", "shopify.com", "hubspot.com",
    "mailchimp.com", "constantcontact.com", "leadconnectorhq.com", "msgsndr.com", "elementor.com",
    "dominio.com", "domaine.com", "ejemplo.com", "exemple.com", "beispiel.de", "esempio.it",  # translated form hints
}
_PLACEHOLDER_LOCALS = {"you", "name", "email", "user", "username", "yourname", "your", "someone", "example",
                       "test", "firstname", "first", "last", "lastname", "youremail", "your-email", "e-mail",
                       "emailaddress", "address", "sample", "demo", "noreply", "no-reply", "donotreply"}
# form hints and template text, junk on any domain (placeholder="example@joesdental.com")
_ALWAYS_PLACEHOLDER_LOCALS = {"example", "yourname", "youremail", "your-email", "your.email", "firstname", "lastname",
                              "first.last", "firstname.lastname", "emailaddress", "john.doe", "johndoe", "jane.doe", "janedoe"}
# page text glued to an address: "(737) 242-7455info@x.com"
_PHONE_PREFIX_RE = re.compile(r"^(?:\d{1,4}[-.])*\d{3}[-.]\d{4}(?=[a-z])")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".css", ".js")


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def clean_email(raw: Optional[str]) -> str:
    """Lowercase, strip junk. Returns '' if it is not a plausible real address."""
    if not raw:
        return ""
    e = urllib.parse.unquote(raw.strip()).strip().lower()
    if e.startswith("mailto:"):
        e = e[7:]
    e = e.split("?")[0].strip().strip(".,;:()[]<>\"'")
    if not EMAIL_RE.fullmatch(e):
        return ""
    local, dom = e.split("@", 1)
    local = _PHONE_PREFIX_RE.sub("", local)
    e = local + "@" + dom
    if local in _ALWAYS_PLACEHOLDER_LOCALS:
        return ""
    if len(e) > 254 or len(local) > 64:
        return ""
    if dom.endswith(_IMAGE_EXT) or local.endswith(_IMAGE_EXT):
        return ""
    if "u003e" in e or "u003c" in e or ".." in e:
        return ""
    if dom in JUNK_EMAIL_DOMAINS or _matches_host(dom, JUNK_EMAIL_DOMAINS):
        return ""
    if local in _PLACEHOLDER_LOCALS and (dom in WEBMAIL_DOMAINS or dom in JUNK_EMAIL_DOMAINS):
        return ""
    if re.fullmatch(r"[0-9a-f]{20,}", local):  # hashed tracking addresses
        return ""
    return e


_NAME_SUFFIXES = ("the", "co", "inc", "llc", "pllc", "pc", "pa", "ltd", "llp", "corp", "company", "group", "dds", "dmd")


def _same_org(dom: str, company_domain: str, company_name: str = "") -> bool:
    cd = company_domain.lower()
    if dom == cd or dom.endswith("." + cd) or cd.endswith("." + dom):
        return True
    dl, cl = dom.split(".")[0], cd.split(".")[0]
    # same registrable label (joesdental.com vs joesdental.net)
    if dl == cl and len(dl) > 4:
        return True
    # brand variants (celebratedental.com vs celebratedentalaustin.com)
    short, long_ = sorted((dl, cl), key=len)
    if len(short) >= 7 and short in long_:
        return True
    # domain built from the business name ("Sola Smile Co." -> solasmileaustin.com)
    words = [w for w in re.split(r"[^a-z0-9]+", (company_name or "").lower()) if w]
    while words and words[-1] in _NAME_SUFFIXES:
        words.pop()
    core = "".join(w for w in words if w != "the")
    return len(core) >= 6 and len(dl) >= 6 and (dl.startswith(core) or core.startswith(dl))


def classify_email(email: str, company_domain: str = "", company_name: str = "") -> str:
    """'role' (info@ etc), 'personal' (on company domain), 'personal_webmail' (gmail etc), 'third_party' (some other org).
    A role mailbox on another organization's domain (info@webagency.com) is third_party, not role."""
    local, dom = email.lower().split("@", 1)
    base = re.split(r"[._\-+]", local)[0]
    is_role = local in ROLE_PREFIXES or base in ROLE_PREFIXES
    if dom in WEBMAIL_DOMAINS:
        return "role" if is_role else "personal_webmail"
    if company_domain and not _same_org(dom, company_domain, company_name):
        return "third_party"
    return "role" if is_role else "personal"


def is_offsite_crawl_email(contact: Dict[str, Any]) -> bool:
    """A crawled address on someone else's domain: web agency credit, WordPress author, parent company.
    Kept in the store for reference, never a primary contact, never exported or pushed."""
    return contact.get("email_type") == "third_party" and contact.get("email_source") == "crawl"


def is_disposable(email: str) -> bool:
    return email_domain(email) in DISPOSABLE_DOMAINS


# ---------------------------------------------------------------- DNS

def _run(cmd, timeout=8) -> Optional[str]:
    """stdout of a command, or None when it could not run or timed out."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return out.stdout or ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeError):
        return None


def _mx_from_dig(out: Optional[str]) -> Optional[bool]:
    """Only a definite DNS answer counts. Timeouts, SERVFAIL, and no network are None, never "no MX"."""
    if not out:
        return None
    m = re.search(r"status:\s*([A-Z]+)", out)
    if not m:
        return None
    if m.group(1) == "NXDOMAIN":
        return False
    if m.group(1) != "NOERROR":
        return None
    hosts = re.findall(r"\sIN\s+MX\s+\d+\s+(\S+)", out)
    return any(h != "." for h in hosts)  # a lone "0 ." is a null MX: the domain takes no mail


def _mx_from_nslookup(out: Optional[str]) -> Optional[bool]:
    if not out:
        return None
    low = out.lower()
    if "mail exchanger" in low:
        return True
    if "non-existent domain" in low or "nxdomain" in low:
        return False
    return None  # "no answer", timeouts, and server failures read the same on some systems: undetermined


def dns_check(domain: str) -> Dict[str, Optional[bool]]:
    """Return {'has_mx': bool|None, 'has_a': bool|None}. None means could not determine (for example, offline)."""
    res: Dict[str, Optional[bool]] = {"has_mx": None, "has_a": None}
    if shutil.which("dig"):
        res["has_mx"] = _mx_from_dig(_run(["dig", "+time=3", "+tries=2", "MX", domain]))
    elif shutil.which("nslookup"):
        res["has_mx"] = _mx_from_nslookup(_run(["nslookup", "-type=mx", domain]))
    try:
        socket.getaddrinfo(domain, None)
        res["has_a"] = True
    except socket.gaierror:
        res["has_a"] = False if res["has_mx"] is False else None  # offline also raises gaierror; only trust it next to a definite DNS answer
    except Exception:
        res["has_a"] = None
    return res


# ---------------------------------------------------------------- misc

def parse_json(s: Optional[str], default):
    """Decode a JSON column. Bad JSON, or a value of a different shape than `default` (a list where a dict belongs), gives `default`."""
    if not s:
        return default
    try:
        val = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
    if default is not None and not isinstance(val, type(default)):
        return default
    return val


def first_nonempty(*vals) -> str:
    for v in vals:
        if v:
            return str(v).strip()
    return ""


def text_has_any(text: str, needles) -> Optional[str]:
    t = (text or "").lower()
    for n in needles or []:
        if n and n.lower() in t:
            return n
    return None
