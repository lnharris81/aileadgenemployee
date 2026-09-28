"""OpenStreetMap sourcing via the Overpass API. Free, no key. Coverage varies by area; pair with crawl."""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import db
from ..util import http_request, HttpError, clean_email
from . import base_record, geocode

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Friendly category -> list of tag filters. Each filter is "k=v" or "k~regex"; join with ";" for AND.
PRESETS: Dict[str, List[str]] = {
    "dentist": ["amenity=dentist", "healthcare=dentist"],
    "doctor": ["amenity=doctors", "healthcare=doctor"],
    "clinic": ["amenity=clinic", "healthcare=clinic"],
    "chiropractor": ["healthcare=chiropractor", "healthcare:speciality~chiropract"],
    "physiotherapist": ["healthcare=physiotherapist"],
    "psychotherapist": ["healthcare=psychotherapist", "healthcare:speciality~psych"],
    "optician": ["shop=optician", "healthcare=optometrist"],
    "veterinary": ["amenity=veterinary"],
    "pharmacy": ["amenity=pharmacy"],
    "lawyer": ["office=lawyer"],
    "accountant": ["office=accountant", "office=tax_advisor"],
    "insurance": ["office=insurance"],
    "real_estate": ["office=estate_agent"],
    "financial_advisor": ["office=financial_advisor", "office=financial"],
    "marketing_agency": ["office=advertising_agency", "office=marketing"],
    "it_company": ["office=it"],
    "architect": ["office=architect"],
    "coworking": ["office=coworking"],
    "restaurant": ["amenity=restaurant"],
    "cafe": ["amenity=cafe"],
    "bar": ["amenity=bar", "amenity=pub"],
    "fast_food": ["amenity=fast_food"],
    "gym": ["leisure=fitness_centre"],
    "yoga": ["leisure=fitness_centre;sport=yoga", "leisure=sports_centre;sport=yoga"],
    "martial_arts": ["leisure=sports_centre;sport~martial|boxing|jiu|karate|taekwondo"],
    "hair_salon": ["shop=hairdresser"],
    "barber": ["shop=hairdresser;male=yes", "shop=hairdresser;name~barber"],
    "beauty_salon": ["shop=beauty"],
    "nail_salon": ["shop=beauty;beauty=nails"],
    "spa": ["shop=massage", "leisure=spa", "shop=beauty;beauty=spa"],
    "tattoo": ["shop=tattoo"],
    "car_repair": ["shop=car_repair"],
    "car_dealer": ["shop=car"],
    "car_wash": ["amenity=car_wash"],
    "tyres": ["shop=tyres"],
    "plumber": ["craft=plumber"],
    "electrician": ["craft=electrician"],
    "hvac": ["craft=hvac"],
    "roofer": ["craft=roofer"],
    "painter": ["craft=painter"],
    "carpenter": ["craft=carpenter", "craft=joiner"],
    "landscaper": ["craft=gardener", "shop=garden_centre", "craft=landscaper"],
    "builder": ["craft=builder", "office=construction_company"],
    "locksmith": ["craft=locksmith", "shop=locksmith"],
    "cleaning": ["craft=cleaning", "shop=dry_cleaning", "shop=laundry"],
    "photographer": ["craft=photographer", "shop=photo"],
    "hotel": ["tourism=hotel", "tourism=motel", "tourism=guest_house"],
    "childcare": ["amenity=kindergarten", "amenity=childcare"],
    "school": ["amenity=school"],
    "driving_school": ["amenity=driving_school"],
    "florist": ["shop=florist"],
    "bakery": ["shop=bakery"],
    "butcher": ["shop=butcher"],
    "pet_grooming": ["shop=pet_grooming"],
    "pet_store": ["shop=pet"],
    "jeweler": ["shop=jewelry"],
    "furniture": ["shop=furniture"],
    "bike_shop": ["shop=bicycle"],
    "funeral": ["shop=funeral_directors", "amenity=funeral_hall"],
    "storage": ["shop=storage_rental"],
    "moving": ["office=moving_company", "shop=moving"],
    "travel_agency": ["shop=travel_agency"],
    "church": ["amenity=place_of_worship"],
    "dance_school": ["leisure=dance", "amenity=dancing_school"],
    "music_school": ["amenity=music_school"],
    "tutoring": ["office=educational_institution", "amenity=prep_school"],
    "event_venue": ["amenity=events_venue"],
    "wedding": ["shop=wedding", "office=wedding_planner"],
}


def _filter_clause(f: str) -> str:
    parts = []
    for cond in f.split(";"):
        cond = cond.strip()
        if "~" in cond and ("=" not in cond or cond.index("~") < cond.index("=")):
            k, v = cond.split("~", 1)
            v = v.strip()
            if v.startswith("(?i)"):  # Overpass has no inline flags; its ",i" suffix does the same
                v = v[4:]
            parts.append(f'["{k.strip()}"~"{v}",i]')
        elif "=" in cond:
            k, v = cond.split("=", 1)
            parts.append(f'["{k.strip()}"="{v.strip()}"]')
        elif cond:
            parts.append(f'["{cond}"]')
    return "".join(parts)


def build_query(filters: List[str], bbox: Tuple[float, float, float, float], timeout: int = 180) -> str:
    s, w, n, e = bbox
    body = "\n".join(f'  nwr{_filter_clause(f)}["name"]({s},{w},{n},{e});' for f in filters)
    return f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout center tags;"


def run_overpass(query: str) -> Dict[str, Any]:
    import json
    import urllib.parse
    last: Optional[Exception] = None
    for url in OVERPASS_URLS:
        for attempt in range(3):
            try:
                status, _h, body, _u = http_request(
                    "POST", url, {"Content-Type": "application/x-www-form-urlencoded"},
                    urllib.parse.urlencode({"data": query}).encode(), timeout=240, retries=0)
                return json.loads(body.decode("utf-8"))
            except HttpError as e:
                last = e
                if e.status in (429, 504, 503):
                    time.sleep(10 * (attempt + 1))
                    continue
                break
            except Exception as e:  # network
                last = e
                time.sleep(5)
    raise SystemExit(f"Overpass failed on all mirrors: {last}")


def element_to_record(el: Dict[str, Any], category: str, country: str) -> Optional[Dict[str, Any]]:
    t = el.get("tags") or {}
    name = t.get("name") or t.get("brand")
    if not name:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    website = t.get("website") or t.get("contact:website") or t.get("url") or ""
    phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or ""
    addr = " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x)
    if not addr and t.get("addr:full"):
        addr = t["addr:full"]
    rec = base_record(
        name, website, phone.split(";")[0], t.get("addr:country") or country,
        address=addr or None, city=t.get("addr:city"), state=t.get("addr:state"), postal_code=t.get("addr:postcode"),
        lat=lat, lng=lon, category=category,
        facebook_url=t.get("contact:facebook"), instagram_url=t.get("contact:instagram"),
        linkedin_url=t.get("contact:linkedin"), twitter_url=t.get("contact:twitter"),
        source_ref=f"osm:{el.get('type')}/{el.get('id')}",
    )
    email = clean_email((t.get("email") or t.get("contact:email") or "").split(";")[0])
    if email:
        rec["_email"] = email
    return rec


def run(conn, icp: Dict[str, Any], places: Optional[List[str]] = None, bbox: Optional[str] = None,
        categories: Optional[List[str]] = None, tags: Optional[List[str]] = None, limit: Optional[int] = None,
        dry_run: bool = False, log=print) -> Dict[str, Any]:
    from ..util import classify_email
    country = icp["geography"].get("country") or "US"
    filters: List[Tuple[str, List[str]]] = []
    for c in categories or []:
        if c not in PRESETS:
            raise SystemExit(f"Unknown OSM category '{c}'. Known: {', '.join(sorted(PRESETS))}. Or pass --tags k=v.")
        filters.append((c, PRESETS[c]))
    for tg in tags or []:
        filters.append((tg, [tg]))
    if not filters:
        raise SystemExit("Give --category (see leadgen source osm --list-categories) or --tags k=v.")

    areas: List[Tuple[str, Tuple[float, float, float, float]]] = []
    if bbox:
        try:
            s, w, n, e = (float(x) for x in bbox.split(","))
        except ValueError:
            raise SystemExit("--bbox needs four numbers: south,west,north,east (for example 30.1,-97.9,30.5,-97.5)")
        areas.append((f"bbox {bbox}", (s, w, n, e)))
    for p in places or []:
        g = geocode(p)
        if not g:
            log(f"  ! could not geocode '{p}', skipping")
            continue
        areas.append((g["display_name"], g["bbox"]))
    if not areas:
        raise SystemExit("No areas to search. Give --place or --bbox.")

    stats = {"areas": len(areas), "elements": 0, "created": 0, "merged": 0, "skipped_nameless": 0, "emails": 0}
    seen_refs = set()
    for label, bb in areas:
        for cat, flist in filters:
            q = build_query(flist, bb)
            log(f"  Overpass: {cat} in {label[:60]} ...")
            if dry_run:
                log(q)
                continue
            data = run_overpass(q)
            db.log_usage(conn, "overpass", "interpreter", 1)
            els = data.get("elements") or []
            stats["elements"] += len(els)
            for el in els:
                rec = element_to_record(el, cat, country)
                if not rec:
                    stats["skipped_nameless"] += 1
                    continue
                if rec["source_ref"] in seen_refs:
                    continue
                seen_refs.add(rec["source_ref"])
                email = rec.pop("_email", None)
                rec["tags"] = "area:" + re.sub(r"[,\s]+", " ", label.split(",")[0] if bbox is None else label).strip()[:40]
                cid, created = db.upsert_company(conn, rec, "osm")
                stats["created" if created else "merged"] += 1
                if email:
                    db.upsert_contact(conn, cid, {"email": email, "email_type": classify_email(email, rec.get("domain", "")),
                                                  "email_source": "osm", "email_confidence": 70, "source_ref": rec["source_ref"]})
                    stats["emails"] += 1
                if limit and stats["created"] >= limit:
                    conn.commit()
                    log(f"  reached --limit {limit}")
                    return stats
            conn.commit()
            log(f"    {len(els)} elements, {stats['created']} new companies so far")
            time.sleep(2)
    return stats
