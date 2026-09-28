"""Email verification. Local: syntax, disposable, MX/A via DNS. Providers: Hunter, Instantly."""
import time
from typing import Any, Dict, Optional, Tuple

from . import db
from .util import EMAIL_RE, is_disposable, email_domain, dns_check, http_json, HttpError, now_iso

STATUSES = ("unverified", "valid", "invalid", "catch_all", "risky", "unknown")


def local_check(conn, email: str, use_cache: bool = True) -> Tuple[str, str]:
    """Return (verify_status, detail). 'unknown' + 'mx_ok' means the mailbox domain accepts mail but we did not prove the box."""
    if not EMAIL_RE.fullmatch(email):
        return "invalid", "syntax"
    if is_disposable(email):
        return "invalid", "disposable"
    dom = email_domain(email)
    cached = db.dns_cached(conn, dom) if use_cache else None
    if cached is not None and cached["has_mx"] is not None:
        has_mx, has_a = cached["has_mx"], cached["has_a"]
    else:
        r = dns_check(dom)
        has_mx, has_a = r["has_mx"], r["has_a"]
        if has_mx is not None:  # never cache "could not tell": a network blip must not stick
            db.dns_store(conn, dom, has_mx, has_a)
    if has_mx:
        return "unknown", "mx_ok"
    if has_mx is None:
        return "unknown", "mx_unchecked" if has_a in (True, None) else "no_dns"
    if has_a:
        return "unknown", "a_only"
    return "invalid", "no_mx"


def hunter_verify(api_key: str, email: str) -> Tuple[str, str]:
    data = http_json("GET", "https://api.hunter.io/v2/email-verifier", params={"email": email, "api_key": api_key}, timeout=40)
    d = data.get("data") or {}
    st = d.get("status") or "unknown"
    mapped = {"valid": "valid", "invalid": "invalid", "accept_all": "catch_all", "webmail": "risky",
              "disposable": "invalid", "unknown": "unknown"}.get(st, "unknown")
    return mapped, f"hunter:{st}:score={d.get('score')}"


def instantly_verify(api_key: str, email: str, polls: int = 4, wait: float = 4.0) -> Tuple[str, str]:
    h = {"Authorization": f"Bearer {api_key}"}
    data = http_json("POST", "https://api.instantly.ai/api/v2/email-verification", h, {"email": email}, timeout=40)
    vs = data.get("verification_status")
    for _ in range(polls):
        if vs != "pending":
            break
        time.sleep(wait)
        data = http_json("GET", f"https://api.instantly.ai/api/v2/email-verification/{email}", h, timeout=40)
        vs = data.get("verification_status")
    catch_all = data.get("catch_all")
    if vs == "verified":
        return ("catch_all" if catch_all is True else "valid"), f"instantly:verified:catch_all={catch_all}"
    if vs == "invalid":
        return "invalid", "instantly:invalid"
    return "unknown", f"instantly:{vs}"


def run(conn, provider: str = "local", limit: Optional[int] = None, max_requests: int = 100,
        statuses=("unverified", "unknown"), only_qualified: bool = False, api_key: Optional[str] = None,
        recheck: bool = False, log=print) -> Dict[str, Any]:
    where = "c.email IS NOT NULL AND c.status != 'do_not_contact'"
    if not recheck:
        placeholders = ",".join("?" * len(statuses))
        where += f" AND c.verify_status IN ({placeholders})"
        params: Tuple[Any, ...] = tuple(statuses)
    else:
        params = ()
    if provider == "local":
        where += " AND (c.verify_provider IS NULL OR c.verify_provider = 'local')"
    else:
        where += " AND (c.verify_provider IS NULL OR c.verify_provider = 'local')"  # do not re-spend on provider-checked
    if only_qualified:
        where += " AND co.qualified = 1"
    sql = (f"SELECT c.id, c.email, c.email_source FROM contacts c JOIN companies co ON co.id = c.company_id "
           f"WHERE {where} ORDER BY COALESCE(co.score, 0) DESC, c.email_confidence DESC, c.id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    stats: Dict[str, Any] = {"provider": provider, "checked": 0, "valid": 0, "invalid": 0, "catch_all": 0,
                             "risky": 0, "unknown": 0, "requests": 0}
    log(f"  verify ({provider}): {len(rows)} contacts to check" + (f", cap {max_requests} requests" if provider != "local" else ""))
    for r in rows:
        if provider != "local" and stats["requests"] >= max_requests:
            log(f"  hit --max-requests {max_requests}")
            break
        email = r["email"]
        try:
            if provider == "local":
                status, detail = local_check(conn, email, use_cache=not recheck)
            elif provider == "hunter":
                status, detail = local_check(conn, email)
                if status != "invalid":
                    status, detail = hunter_verify(api_key or "", email)
                    stats["requests"] += 1
                    db.log_usage(conn, "hunter", "email-verifier", 1)
            elif provider == "instantly":
                status, detail = local_check(conn, email)
                if status != "invalid":
                    status, detail = instantly_verify(api_key or "", email)
                    stats["requests"] += 1
                    db.log_usage(conn, "instantly", "email-verification", 1)
            else:
                raise SystemExit(f"unknown verify provider {provider}")
        except HttpError as e:
            if e.status in (401, 403):
                raise SystemExit(f"{provider} rejected the API key: {e.body[:200]}")
            if e.status == 429:
                log(f"  {provider} rate limit hit; stopping.")
                break
            log(f"  ! {email}: HTTP {e.status}")
            continue
        db.update_contact(conn, r["id"], verify_status=status, verify_provider=provider, verify_detail=detail,
                          verify_at=now_iso())
        stats["checked"] += 1
        stats[status] = stats.get(status, 0) + 1
        if stats["checked"] % 25 == 0:
            conn.commit()
            log(f"    {stats['checked']}/{len(rows)} | valid {stats['valid']} invalid {stats['invalid']} catch_all {stats['catch_all']} unknown {stats['unknown']}")
    conn.commit()
    return stats
