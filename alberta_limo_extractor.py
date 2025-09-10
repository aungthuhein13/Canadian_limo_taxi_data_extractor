# Alberta Limousine and Taxi Service Extractor
# Adapted from tesst.py for Alberta, Canada using Google Places API
# 
# Usage:
#   python alberta_limo_extractor.py --api-key YOUR_API_KEY

import argparse
import csv
import time
import sys
import requests
from collections import OrderedDict

TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL    = "https://maps.googleapis.com/maps/api/place/details/json"

# Fields to request from Place Details
DETAIL_FIELDS = ",".join([
    "place_id",
    "name",
    "formatted_address",
    "formatted_phone_number",
    "international_phone_number",
    "website",
    "url",
    "types",
    "rating",
    "user_ratings_total",
    "geometry/location",
    "opening_hours",
])


def places_text_search(query, api_key, sleep_seconds=2.0, max_per_query=180):
    """
    Generator that yields results from Places Text Search, handling pagination.
    Google returns up to 60 results (3 pages) per query. We expose a cap via max_per_query.
    """
    params = {"query": query, "key": api_key}
    fetched = 0
    while True:
        r = requests.get(TEXTSEARCH_URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[WARN] TextSearch HTTP {r.status_code} for query={query}", file=sys.stderr)
            return
        data = r.json()
        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            # Common statuses: OVER_QUERY_LIMIT, REQUEST_DENIED, INVALID_REQUEST
            print(f"[WARN] TextSearch status={status} for query={query} | {data.get('error_message','')}", file=sys.stderr)
            if status == "OVER_QUERY_LIMIT":
                time.sleep(5)
                continue
            if status == "INVALID_REQUEST":
                time.sleep(2)
                continue
            return
        results = data.get("results", [])
        for item in results:
            yield item
            fetched += 1
            if fetched >= max_per_query:
                return
        next_token = data.get("next_page_token")
        if not next_token:
            return
        # Google requires a short wait before next_page_token becomes active
        time.sleep(sleep_seconds)
        params = {"pagetoken": next_token, "key": api_key}


def place_details(place_id, api_key, sleep_seconds=0.12, retries=3):
    """
    Fetch detailed info for a place_id. Retries some transient errors and rate limits.
    """
    params = {"place_id": place_id, "fields": DETAIL_FIELDS, "key": api_key}
    for attempt in range(1, retries+1):
        r = requests.get(DETAILS_URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[WARN] Details HTTP {r.status_code} for place_id={place_id}", file=sys.stderr)
            time.sleep(sleep_seconds * attempt)
            continue
        data = r.json()
        status = data.get("status")
        if status == "OK":
            return data.get("result", {})
        elif status in ("OVER_QUERY_LIMIT", "RESOURCE_EXHAUSTED"):
            # back off a bit
            time.sleep(max(1.0, sleep_seconds * (attempt*5)))
            continue
        elif status in ("INVALID_REQUEST", "UNKNOWN_ERROR"):
            time.sleep(sleep_seconds * attempt)
            continue
        else:
            # ZERO_RESULTS or REQUEST_DENIED etc.
            return {}
    return {}


def normalize_types(types):
    if not types: return ""
    try:
        return ",".join(types)
    except Exception:
        return ""


def row_from_details(d):
    # Construct a row with stable set of columns
    place_id = d.get("place_id")
    geom = d.get("geometry", {}).get("location", {}) if isinstance(d.get("geometry"), dict) else {}
    url = d.get("url")  # Google Maps URL (if present in Details)
    maps_link = url if url else (f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}" if place_id else None)

    return OrderedDict([
        ("google_place_url", maps_link),
        ("business_name", d.get("name")),
        ("business_website", d.get("website")),
        ("business_phone", d.get("formatted_phone_number")),
        ("intl_phone", d.get("international_phone_number")),
        ("type", None),
        ("sub_types", normalize_types(d.get("types"))),
        ("full_address", d.get("formatted_address")),
        ("latitude", geom.get("lat")),
        ("longitude", geom.get("lng")),
        ("rating", d.get("rating")),
        ("user_ratings_total", d.get("user_ratings_total")),
        ("google_id", place_id),
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", required=True, help="Google Maps/Places API key")
    parser.add_argument("--out", default="alberta_limo_places.csv", help="Output CSV filename")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to wait between Text Search pages")
    parser.add_argument("--details-sleep", type=float, default=0.12, help="Seconds to wait between Details requests")
    parser.add_argument("--max-per-query", type=int, default=180, help="Max results per single Text Search query")
    parser.add_argument("--no-province-wide", action="store_true", help="Skip the broad 'Alberta, Canada' query")
    parser.add_argument("--major-cities-only", action="store_true", help="Search only major cities (faster)")
    parser.add_argument("--rural-only", action="store_true", help="Search only rural/regional areas")
    args = parser.parse_args()

    # Comprehensive Alberta city and town coverage
    major_cities = [
        # Major urban centers - Multiple search terms
        "limousine service in Calgary, Alberta, Canada",
        "taxi service in Calgary, Alberta, Canada",
        "chauffeur service in Calgary, Alberta, Canada",
        "transportation service in Calgary, Alberta, Canada",
        "car service in Calgary, Alberta, Canada",
        "private driver in Calgary, Alberta, Canada",
        "airport shuttle in Calgary, Alberta, Canada",
        
        "limousine service in Edmonton, Alberta, Canada",
        "taxi service in Edmonton, Alberta, Canada",
        "chauffeur service in Edmonton, Alberta, Canada",
        "transportation service in Edmonton, Alberta, Canada",
        "car service in Edmonton, Alberta, Canada", 
        "private driver in Edmonton, Alberta, Canada",
        "airport shuttle in Edmonton, Alberta, Canada",
        
        "limousine service in Red Deer, Alberta, Canada",
        "taxi service in Red Deer, Alberta, Canada",
        "limousine service in Lethbridge, Alberta, Canada",
        "taxi service in Lethbridge, Alberta, Canada",
        "limousine service in Medicine Hat, Alberta, Canada",
        "taxi service in Medicine Hat, Alberta, Canada",
        "limousine service in Fort McMurray, Alberta, Canada",
        "taxi service in Fort McMurray, Alberta, Canada",
    ]
    
    # Medium cities and regional centers
    medium_cities = [
        "limousine service in Grande Prairie, Alberta, Canada",
        "taxi service in Grande Prairie, Alberta, Canada",
        "limousine service in Airdrie, Alberta, Canada", 
        "taxi service in Airdrie, Alberta, Canada",
        "limousine service in Spruce Grove, Alberta, Canada",
        "taxi service in Spruce Grove, Alberta, Canada",
        "limousine service in Okotoks, Alberta, Canada",
        "taxi service in Okotoks, Alberta, Canada",
        "limousine service in Lloydminster, Alberta, Canada",
        "taxi service in Lloydminster, Alberta, Canada",
        "limousine service in Camrose, Alberta, Canada",
        "taxi service in Camrose, Alberta, Canada",
        "limousine service in Wetaskiwin, Alberta, Canada", 
        "taxi service in Wetaskiwin, Alberta, Canada",
        "limousine service in Leduc, Alberta, Canada",
        "taxi service in Leduc, Alberta, Canada",
        "limousine service in Cochrane, Alberta, Canada",
        "taxi service in Cochrane, Alberta, Canada",
        "limousine service in Chestermere, Alberta, Canada",
        "taxi service in Chestermere, Alberta, Canada",
        "limousine service in Beaumont, Alberta, Canada",
        "taxi service in Beaumont, Alberta, Canada",
        "limousine service in Fort Saskatchewan, Alberta, Canada",
        "taxi service in Fort Saskatchewan, Alberta, Canada",
        "limousine service in St. Albert, Alberta, Canada",
        "taxi service in St. Albert, Alberta, Canada",
        "limousine service in Sherwood Park, Alberta, Canada",
        "taxi service in Sherwood Park, Alberta, Canada",
        "limousine service in Sylvan Lake, Alberta, Canada",
        "taxi service in Sylvan Lake, Alberta, Canada",
        "limousine service in Canmore, Alberta, Canada",
        "taxi service in Canmore, Alberta, Canada",
        "limousine service in Banff, Alberta, Canada",
        "taxi service in Banff, Alberta, Canada",
        "limousine service in Jasper, Alberta, Canada",
        "taxi service in Jasper, Alberta, Canada",
    ]
    
    # Rural areas, smaller towns, and regional areas
    rural_queries = [
        # Oil sands and northern regions
        "taxi service in Fort Chipewyan, Alberta, Canada",
        "taxi service in High Level, Alberta, Canada", 
        "taxi service in Peace River, Alberta, Canada",
        "taxi service in Slave Lake, Alberta, Canada",
        "taxi service in Athabasca, Alberta, Canada",
        "taxi service in Cold Lake, Alberta, Canada",
        "taxi service in Bonnyville, Alberta, Canada",
        "taxi service in Lac La Biche, Alberta, Canada",
        
        # Central Alberta
        "taxi service in Innisfail, Alberta, Canada",
        "taxi service in Olds, Alberta, Canada", 
        "taxi service in Didsbury, Alberta, Canada",
        "taxi service in Sundre, Alberta, Canada",
        "taxi service in Rocky Mountain House, Alberta, Canada",
        "taxi service in Stettler, Alberta, Canada",
        "taxi service in Drumheller, Alberta, Canada",
        "taxi service in Hanna, Alberta, Canada",
        "taxi service in Coronation, Alberta, Canada",
        "taxi service in Castor, Alberta, Canada",
        
        # Southern Alberta
        "taxi service in Pincher Creek, Alberta, Canada",
        "taxi service in Blairmore, Alberta, Canada",
        "taxi service in Cardston, Alberta, Canada",
        "taxi service in Magrath, Alberta, Canada",
        "taxi service in Taber, Alberta, Canada",
        "taxi service in Coaldale, Alberta, Canada", 
        "taxi service in Picture Butte, Alberta, Canada",
        "taxi service in Milk River, Alberta, Canada",
        "taxi service in Bow Island, Alberta, Canada",
        "taxi service in Foremost, Alberta, Canada",
        
        # Eastern Alberta
        "taxi service in Vegreville, Alberta, Canada",
        "taxi service in Vermilion, Alberta, Canada",
        "taxi service in Wainwright, Alberta, Canada",
        "taxi service in Provost, Alberta, Canada",
        "taxi service in Consort, Alberta, Canada",
        "taxi service in Hardisty, Alberta, Canada",
        "taxi service in Kitscoty, Alberta, Canada",
        
        # Western Alberta / Foothills
        "taxi service in High River, Alberta, Canada",
        "taxi service in Nanton, Alberta, Canada",
        "taxi service in Claresholm, Alberta, Canada",
        "taxi service in Vulcan, Alberta, Canada",
        "taxi service in Strathmore, Alberta, Canada",
        "taxi service in Three Hills, Alberta, Canada",
        "taxi service in Bassano, Alberta, Canada",
        
        # Northwestern Alberta
        "taxi service in Whitecourt, Alberta, Canada",
        "taxi service in Edson, Alberta, Canada",
        "taxi service in Hinton, Alberta, Canada",
        "taxi service in Fox Creek, Alberta, Canada",
        "taxi service in Valleyview, Alberta, Canada",
        "taxi service in Fairview, Alberta, Canada",
        "taxi service in Manning, Alberta, Canada",
        "taxi service in Rainbow Lake, Alberta, Canada",
        
        # Regional searches
        "taxi service in Alberta Rockies, Canada",
        "limousine service in Alberta Rockies, Canada",
        "taxi service in Wood Buffalo, Alberta, Canada",
        "taxi service in Mackenzie County, Alberta, Canada",
        "taxi service in Municipal District of Opportunity, Alberta, Canada",
        "taxi service in Regional Municipality of Wood Buffalo, Alberta, Canada",
    ]
    
    # Combine all queries based on user options
    if args.major_cities_only:
        city_queries = major_cities
        print(f"[INFO] Using major cities only: {len(city_queries)} queries")
    elif args.rural_only:
        city_queries = rural_queries
        print(f"[INFO] Using rural/regional areas only: {len(city_queries)} queries")
    else:
        city_queries = major_cities + medium_cities + rural_queries
        print(f"[INFO] Using comprehensive Alberta search: {len(city_queries)} queries")
    
    if not args.no_province_wide:
        city_queries.insert(0, "limousine service in Alberta, Canada")
        city_queries.insert(1, "taxi service in Alberta, Canada")
        city_queries.insert(2, "transportation service in Alberta, Canada")

    # 1) Discover place_ids across all queries
    seen_place_ids = set()
    place_ids = []
    total_queries = len(city_queries)
    
    for i, q in enumerate(city_queries, 1):
        print(f"[INFO] Text Search ({i}/{total_queries}): {q}")
        query_results = 0
        for item in places_text_search(q, args.api_key, sleep_seconds=args.sleep, max_per_query=args.max_per_query):
            pid = item.get("place_id")
            if pid and pid not in seen_place_ids:
                seen_place_ids.add(pid)
                place_ids.append(pid)
            query_results += 1
        print(f"      Found {query_results} results, {len(place_ids)} unique total")
        
        # Progress update every 10 queries
        if i % 10 == 0 or i == total_queries:
            print(f"[PROGRESS] Completed {i}/{total_queries} queries, {len(place_ids)} unique places found")
    
    print(f"[INFO] Search complete! Found {len(place_ids)} unique places across {total_queries} queries")

    # 2) Enrich via Details
    print(f"[INFO] Fetching details for {len(place_ids)} places...")
    rows = []
    for i, pid in enumerate(place_ids, 1):
        if i % 25 == 0:
            print(f"  ... {i}/{len(place_ids)}")
        det = place_details(pid, args.api_key, sleep_seconds=args.details_sleep)
        if det:
            rows.append(row_from_details(det))
        time.sleep(args.details_sleep)

    # 3) Write CSV
    if rows:
        fieldnames = list(rows[0].keys())
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"[DONE] Wrote {len(rows)} rows to {args.out}")
    else:
        print("[DONE] No rows found. Try adjusting queries or API key/quota.")
    

if __name__ == "__main__":
    main()
