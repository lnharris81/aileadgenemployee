"""Email pattern inference: fill emails for named contacts when the company's pattern is known.

Generated addresses are marked email_source='pattern' with low confidence and must be verified before use.
"""
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from .. import db
from ..util import classify_email

PATTERNS = ["{first}.{last}", "{first}", "{f}{last}", "{first}{last}", "{first}_{last}", "{f}.{last}", "{last}",
            "{last}.{first}", "{first}{l}", "{f}_{last}", "{last}{first}", "{first}-{last}"]


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z]", "", (s or "").lower())
    return s


def apply(pattern: str, first: str, last: str) -> str:
    f, l = _norm(first), _norm(last)
    if not f and not l:
        return ""
    local = (pattern.replace("{first}", f).replace("{last}", l)
             .replace("{f}", f[:1]).replace("{l}", l[:1]))
    return local if local and "{" not in local else ""


def infer(examples: List[Dict[str, str]]) -> Optional[str]:
    """examples: [{email, first_name, last_name}] on the company domain. Returns the majority pattern."""
    votes: Counter = Counter()
    for ex in examples:
        local = ex["email"].split("@")[0].lower()
        for p in PATTERNS:
            if apply(p, ex.get("first_name", ""), ex.get("last_name", "")) == local:
                votes[p] += 1
                break
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def run(conn, icp: Dict[str, Any], limit: Optional[int] = None, log=print) -> Dict[str, Any]:
    stats = {"companies_with_pattern": 0, "inferred": 0, "generated": 0}
    companies = [dict(r) for r in conn.execute(
        "SELECT id, domain, email_pattern FROM companies WHERE domain IS NOT NULL AND domain != ''").fetchall()]
    for c in companies:
        contacts = [dict(r) for r in db.company_contacts(conn, c["id"])]
        pattern = c["email_pattern"]
        if not pattern:
            examples = [k for k in contacts if k["email"] and k["first_name"] and k["last_name"]
                        and k["email"].endswith("@" + c["domain"]) and k["email_type"] == "personal"]
            pattern = infer(examples)
            if pattern:
                db.update_company(conn, c["id"], email_pattern="inferred:" + pattern)
                stats["inferred"] += 1
        if not pattern:
            continue
        stats["companies_with_pattern"] += 1
        pat = pattern.replace("inferred:", "")
        for k in contacts:
            if k["email"] or not (k["first_name"] and k["last_name"]):
                continue
            local = apply(pat, k["first_name"], k["last_name"])
            if not local:
                continue
            email = f"{local}@{c['domain']}"
            if conn.execute("SELECT 1 FROM contacts WHERE email = ?", (email,)).fetchone():
                continue
            db.update_contact(conn, k["id"], email=email, email_type=classify_email(email, c["domain"]),
                              email_source="pattern", email_confidence=35, verify_status="unverified")
            stats["generated"] += 1
            if limit and stats["generated"] >= limit:
                conn.commit()
                return stats
    conn.commit()
    return stats
