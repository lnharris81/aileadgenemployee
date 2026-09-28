"""Google Places API (New) Text Search with grid tiling to get past the 60-result cap. Paid per request."""
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import db
from ..util import http_json, HttpError
from . import base_record, geocode

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.addressComponents", "places.websiteUri",
    "places.nationalPhoneNumber", "places.internationalPhoneNumber", "places.rating", "places.userRatingCount",
    "places.primaryType", "places.types", "places.businessStatus", "places.googleMapsUri", "places.location",
    "nextPageToken",
])


def search_text(api_key: str, query: str, rect: Optional[Tuple[float, float, float, float]] = None,
                circle: Optional[Tuple[float, float, float]] = None, page_token: Optional[str] = None,
                included_type: Optional[str] = None, region_code: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"textQuery": query, "pageSize": 20}
    if rect:
        s, w, n, e = rect
        body["locationRestriction"] = {"rectangle": {"low": {"latitude": s, "longitude": w},
                                                     "high": {"latitude": n, "longitude": e}}}
    elif circle:
        lat, lng, radius_m = circle
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": min(radius_m, 50000)}}
    if page_token:
        body["pageToken"] = page_token
    if included_type:
        body["includedType"] = included_type
    if region_code:
        body["regionCode"] = region_code
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    return http_json("POST", ENDPOINT, headers, body, timeout=30)


def grid_cells(lat: float, lng: float, radius_km: float, cell_km: float) -> List[Tuple[float, float, float, float]]:
    dlat = cell_km / 111.0
    dlng = cell_km / (111.0 * max(math.cos(math.radians(lat)), 0.1))
    n = max(1, int(math.ceil(radius_km / cell_km)))
    cells = []
    for i in range(-n, n):
        for j in range(-n, n):
            s = lat + i * dlat
            w = lng + j * dlng
            # keep only cells whose centre is inside the circle
            cy, cx = s + dlat / 2, w + dlng / 2
            if math.hypot((cy - lat) * 111.0, (cx - lng) * 111.0 * math.cos(math.radians(lat))) <= radius_km + cell_km / 2:
                cells.append((s, w, s + dlat, w + dlng))
    return cells


def place_to_record(p: Dict[str, Any], query: str, country: str) -> Optional[Dict[str, Any]]:
    name = (p.get("displayName") or {}).get("text")
    if not name:
        return None
    if p.get("businessStatus") == "CLOSED_PERMANENTLY":
        return None
    city = state = postal = ctry = ""
    for comp in p.get("addressComponents") or []:
        types = comp.get("types") or []
        if "locality" in types or ("postal_town" in types and not city):
            city = comp.get("longText") or city
        elif "administrative_area_level_1" in types:
            state = comp.get("shortText") or state
        elif "postal_code" in types:
            postal = comp.get("longText") or postal
        elif "country" in types:
            ctry = comp.get("shortText") or ctry
    loc = p.get("location") or {}
    return base_record(
        name, p.get("websiteUri") or "", p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or "",
        ctry or country,
        address=p.get("formattedAddress"), city=city or None, state=state or None, postal_code=postal or None,
        lat=loc.get("latitude"), lng=loc.get("longitude"),
        category=p.get("primaryType") or query, rating=p.get("rating"), review_count=p.get("userRatingCount"),
        google_maps_url=p.get("googleMapsUri"), source_ref=f"places:{p.get('id')}",
    )


def run(conn, icp: Dict[str, Any], api_key: str, queries: List[str], places: Optional[List[str]] = None,
        center: Optional[str] = None, radius_km: Optional[float] = None, cell_km: Optional[float] = None,
        max_requests: int = 100, included_type: Optional[str] = None, limit: Optional[int] = None,
        dry_run: bool = False, log=print) -> Dict[str, Any]:
    country = icp["geography"].get("country") or "US"
    radius_km = radius_km or icp["geography"].get("radius_km") or 15
    cell_km = cell_km if cell_km is not None else icp["sources"].get("places_cell_km")
    centers: List[Tuple[str, float, float]] = []
    if center:
        lat, lng = (float(x) for x in center.split(","))
        centers.append((center, lat, lng))
    for p in places or []:
        g = geocode(p)
        if g:
            centers.append((g["display_name"], g["lat"], g["lon"]))
        else:
            log(f"  ! could not geocode '{p}'")
    if not centers:
        raise SystemExit("No search centers. Give --place or --center lat,lng.")
    if not queries:
        raise SystemExit("No queries. Give --query (repeatable) or set sources.places_queries in icp.json.")

    jobs: List[Tuple[str, str, Optional[Tuple[float, float, float, float]], Optional[Tuple[float, float, float]]]] = []
    for label, lat, lng in centers:
        if cell_km:
            for cell in grid_cells(lat, lng, radius_km, cell_km):
                for q in queries:
                    jobs.append((label, q, cell, None))
        else:
            for q in queries:
                jobs.append((label, q, None, (lat, lng, radius_km * 1000)))
    est = len(jobs) * 3
    log(f"  Places plan: {len(centers)} center(s) x {len(queries)} query(ies)"
        + (f" x grid cells (cell {cell_km} km, radius {radius_km} km)" if cell_km else " (single 60-result search each)")
        + f" = {len(jobs)} searches, up to {est} requests (cap --max-requests {max_requests}).")
    stats = {"jobs": len(jobs), "requests": 0, "places": 0, "created": 0, "merged": 0, "skipped": 0}
    if dry_run:
        return stats
    seen = set()
    for label, q, rect, circle in jobs:
        token = None
        for _page in range(3):
            if stats["requests"] >= max_requests:
                log(f"  hit --max-requests {max_requests}; stopping. Raise it to continue.")
                conn.commit()
                return stats
            try:
                data = search_text(api_key, q, rect, circle, token, included_type, country if len(country) == 2 else None)
            except HttpError as e:
                log(f"  ! Places error {e.status}: {e.body[:200]}")
                if e.status in (400, 401, 403):
                    raise SystemExit("Places request rejected. Check GOOGLE_PLACES_API_KEY and that Places API (New) is enabled.")
                break
            stats["requests"] += 1
            db.log_usage(conn, "google_places", "searchText", 1)
            for p in data.get("places") or []:
                pid = p.get("id")
                if pid in seen:
                    continue
                seen.add(pid)
                stats["places"] += 1
                rec = place_to_record(p, q, country)
                if not rec:
                    stats["skipped"] += 1
                    continue
                rec["tags"] = "area:" + re.sub(r"[,\s]+", " ", label.split(",")[0]).strip()[:40]
                _cid, created = db.upsert_company(conn, rec, "places")
                stats["created" if created else "merged"] += 1
                if limit and stats["created"] >= limit:
                    conn.commit()
                    log(f"  reached --limit {limit}")
                    return stats
            conn.commit()
            token = data.get("nextPageToken")
            if not token:
                break
            time.sleep(0.3)
        log(f"    '{q}' @ {label[:40]}{' cell' if rect else ''}: {stats['created']} new so far ({stats['requests']} req)")
    return stats
