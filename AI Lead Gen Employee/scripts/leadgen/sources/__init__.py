"""Sourcing providers. Each exposes run(conn, icp, **opts) -> stats dict and writes companies."""
from typing import Any, Dict, Optional

from ..util import normalize_website, normalize_phone, social_field_for, clean_email


def base_record(name: str, website: str = "", phone: str = "", country: str = "US", **extra: Any) -> Dict[str, Any]:
    """Build a company record with normalized website/domain/phone. Social URLs given as website are re-homed."""
    rec: Dict[str, Any] = {"name": (name or "").strip()}
    site, domain, kind = normalize_website(website)
    if kind == "site":
        rec["website"], rec["domain"] = site, domain
    elif kind == "social":
        field = social_field_for(site)
        if field:
            rec[field] = site
    rec["phone"] = normalize_phone(phone, country)
    for k, v in extra.items():
        if v not in (None, ""):
            rec[k] = v
    if "country" not in rec and country:
        rec["country"] = country
    return rec


def geocode(place: str) -> Optional[Dict[str, Any]]:
    """Free geocoding via OpenStreetMap Nominatim. Returns {lat, lon, bbox:(s,w,n,e), display_name} or None."""
    import time
    from ..util import http_json
    url = "https://nominatim.openstreetmap.org/search"
    data = http_json("GET", url, params={"q": place, "format": "jsonv2", "limit": 1, "addressdetails": 0})
    time.sleep(1.0)  # Nominatim usage policy: max 1 request/second
    if not data:
        return None
    hit = data[0]
    s, n, w, e = (float(x) for x in hit["boundingbox"])
    return {"lat": float(hit["lat"]), "lon": float(hit["lon"]), "bbox": (s, w, n, e),
            "display_name": hit.get("display_name", place)}
