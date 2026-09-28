"""Paths, .env, ICP config with defaults, API key presence."""
import copy
import json
import os
from typing import Any, Dict, List, Optional

from .util import load_dotenv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_DIR = os.path.join(ROOT, "config")
ICP_PATH = os.path.join(CONFIG_DIR, "icp.json")
EXAMPLES_DIR = os.path.join(CONFIG_DIR, "examples")
ICP_EXAMPLE = os.path.join(EXAMPLES_DIR, "local-service-dentists.json")
DATA_DIR = os.environ.get("LEADGEN_DATA_DIR") or os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "leadgen.db")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
RAW_DIR = os.path.join(DATA_DIR, "raw")

KEYS = {
    "GOOGLE_PLACES_API_KEY": "Google Places sourcing (paid)",
    "APOLLO_API_KEY": "Apollo companies + contacts (paid plan)",
    "HUNTER_API_KEY": "Hunter contacts, pattern, verification",
    "INSTANTLY_API_KEY": "Instantly push + verification",
    "GHL_API_KEY": "GoHighLevel push",
    "GHL_LOCATION_ID": "GoHighLevel sub-account id",
}

DEFAULT_ICP: Dict[str, Any] = {
    "campaign": "",
    "offer": "",
    "niche": "",
    "geography": {"places": [], "country": "US", "radius_km": 15},
    "company": {"keywords": [], "exclude_keywords": [], "employees_min": None, "employees_max": None,
                "min_rating": None, "min_reviews": None, "require_website": False},
    "contacts": {"titles": [], "seniorities": [], "accept_role_email": True, "prefer_personal_email": True},
    "signals": {"bonus": {}},
    "scoring": {"qualify_threshold": 40, "weights": {}},
    "sources": {"osm_categories": [], "osm_tags": [], "places_queries": [], "places_cell_km": None,
                "apollo_keywords": [], "apollo_employee_ranges": []},
    "targets": {"leads": 500},
}


def load_env() -> int:
    return load_dotenv(os.path.join(ROOT, ".env"))


def _merge(base: Dict[str, Any], over: Dict[str, Any], path: str = "") -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(out.get(k), dict):
            if isinstance(v, dict):
                out[k] = _merge(out[k], v, f"{path}{k}.")
            elif v is not None:  # null keeps the defaults; anything else is a mistake worth naming
                raise SystemExit(f"config/icp.json: \"{path}{k}\" must be an object like in config/examples/, not {v!r}")
        else:
            out[k] = v
    return out


def blank_icp() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_ICP)


def load_icp(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or ICP_PATH  # resolved at call time so tests and LEADGEN_DATA_DIR overrides take effect
    if not os.path.exists(path):
        return blank_icp()
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise SystemExit(f"config/icp.json is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise SystemExit("config/icp.json must be a JSON object like the files in config/examples/")
    return _merge(DEFAULT_ICP, data)


def is_configured(icp: Dict[str, Any]) -> bool:
    """True once a real campaign exists: a name, somewhere to look, and something to look for."""
    return bool(icp.get("campaign")) and bool(icp["geography"]["places"] or icp["sources"]["apollo_keywords"]) \
        and bool(icp["company"]["keywords"] or icp["sources"]["osm_categories"] or icp["sources"]["osm_tags"]
            or icp["sources"]["places_queries"] or icp["sources"]["apollo_keywords"])


NOT_CONFIGURED = ("No campaign configured yet. Describe your business and who you want to reach (or run /define-icp) "
                  "and the employee will write config/icp.json before finding anything.")


def validate_icp(icp: Dict[str, Any]) -> List[str]:
    problems = []
    lists = [("geography", "places"), ("company", "keywords"), ("company", "exclude_keywords"), ("contacts", "titles"),
             ("contacts", "seniorities"), ("sources", "osm_categories"), ("sources", "osm_tags"), ("sources", "places_queries"),
             ("sources", "apollo_keywords"), ("sources", "apollo_employee_ranges")]
    for sec, key in lists:
        v = icp[sec].get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            problems.append(f"{sec}.{key} must be a list of text values, like [\"dental\", \"dentist\"]")
    if not isinstance(icp.get("campaign") or "", str):
        problems.append("campaign must be text, like \"austin-dentists\"")
        return problems
    if not icp.get("campaign"):
        problems.append("campaign is empty: the ICP has not been defined yet (run /define-icp)")
    elif " " in icp["campaign"]:
        problems.append("campaign must be a slug with no spaces (used in filenames)")
    elif icp["campaign"].startswith("example-"):
        problems.append("campaign still has an example name: config/examples/ profiles are starting points; "
                        "rename the campaign and set your own niche, places, and keywords")
    if not icp["geography"]["places"] and not icp["sources"]["apollo_keywords"]:
        problems.append("geography.places is empty and no apollo_keywords set: nothing to source")
    if not icp["company"]["keywords"]:
        problems.append("company.keywords is empty: scoring cannot reward niche fit")
    thr = icp["scoring"].get("qualify_threshold")
    if not isinstance(thr, (int, float)):
        problems.append("scoring.qualify_threshold must be a number")
    from .crawl import SIGNAL_PATTERNS  # late import: crawl pulls in the HTTP stack
    known = set(SIGNAL_PATTERNS) | {"site_stale", "https", "mobile_viewport", "has_form", "email_on_site"}
    for k, v in (icp["signals"].get("bonus") or {}).items():
        if not isinstance(v, (int, float)):
            problems.append(f"signals.bonus.{k} must be a number")
        if (k[3:] if k.startswith("no_") else k) not in known:
            problems.append(f"signals.bonus.{k} is not a signal the crawler detects, so it never scores "
                            f"(valid names: {', '.join(sorted(known))}; prefix no_ to reward absence)")
    return problems


def key_status() -> Dict[str, bool]:
    return {k: bool(os.environ.get(k, "").strip()) for k in KEYS}


def require_key(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(f"{name} is not set. Add it to .env (see .env.example). Needed for: {KEYS.get(name, name)}")
    return val
