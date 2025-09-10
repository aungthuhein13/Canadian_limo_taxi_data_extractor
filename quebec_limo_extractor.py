# Create a ready-to-run Python script that queries Google Places API for
# "limousine service" across Quebec, Canada using Text Search + Details.
# It paginates, dedupes by place_id, and saves a CSV similar to the user's Ontario file.
#
# After you get an API key from Google Cloud, run:
#   python fetch_quebec_limo_places.py --api-key YOUR_API_KEY
#

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
    # Construct a row with stable set of columns (similar to your Ontario file core fields)
    place_id = d.get("place_id")
    geom = d.get("geometry", {}).get("location", {}) if isinstance(d.get("geometry"), dict) else {}
    url = d.get("url")  # Google Maps URL (if present in Details)
    # If URL not provided, build a generic maps link by search query fallback:
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
    parser.add_argument("--out", default="quebec_limo_places.csv", help="Output CSV filename")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to wait between Text Search pages")
    parser.add_argument("--details-sleep", type=float, default=0.12, help="Seconds to wait between Details requests")
    parser.add_argument("--max-per-query", type=int, default=180, help="Max results per single Text Search query")
    parser.add_argument("--no-province-wide", action="store_true", help="Skip the broad 'Quebec, Canada' query")
    parser.add_argument("--major-cities-only", action="store_true", help="Search only major cities (faster)")
    parser.add_argument("--no-french", action="store_true", help="Skip French language queries")
    parser.add_argument("--rural-only", action="store_true", help="Search only rural/regional areas")
    args = parser.parse_args()

    # Comprehensive query list covering major cities, smaller towns, and rural areas
    # with both English and French search terms
    major_cities = [
        # Major urban centers - English terms
        "limousine service in Montreal, Quebec, Canada",
        "taxi service in Montreal, Quebec, Canada",
        "chauffeur service in Montreal, Quebec, Canada",
        "limousine service in Quebec City, Quebec, Canada", 
        "taxi service in Quebec City, Quebec, Canada",
        "limousine service in Laval, Quebec, Canada",
        "taxi service in Laval, Quebec, Canada",
        "limousine service in Gatineau, Quebec, Canada",
        "taxi service in Gatineau, Quebec, Canada",
        "limousine service in Longueuil, Quebec, Canada",
        "limousine service in Sherbrooke, Quebec, Canada",
        "taxi service in Sherbrooke, Quebec, Canada",
        
        # Major cities - French terms
        "service de limousine à Montréal, Québec, Canada",
        "service de taxi à Montréal, Québec, Canada",
        "transport avec chauffeur à Montréal, Québec, Canada",
        "service de limousine à Québec, Québec, Canada",
        "service de taxi à Québec, Québec, Canada",
        "service de limousine à Laval, Québec, Canada",
        "service de taxi à Laval, Québec, Canada",
        "service de limousine à Gatineau, Québec, Canada",
        "service de taxi à Gatineau, Québec, Canada",
        # Additional search variations for comprehensive coverage
        "transportation service in Montreal, Quebec, Canada",
        "car service in Montreal, Quebec, Canada", 
        "private driver in Montreal, Quebec, Canada",
        "airport shuttle in Montreal, Quebec, Canada",
        "transportation service in Quebec City, Quebec, Canada",
        "car service in Quebec City, Quebec, Canada",
        "private driver in Quebec City, Quebec, Canada",
        "airport shuttle in Quebec City, Quebec, Canada",
        
        # French additional variations
        "service de transport à Montréal, Québec, Canada",
        "service de voiture à Montréal, Québec, Canada",
        "chauffeur privé à Montréal, Québec, Canada",
        "navette aéroport à Montréal, Québec, Canada",
        "service de transport à Québec, Québec, Canada",
        "service de voiture à Québec, Québec, Canada",
        "chauffeur privé à Québec, Québec, Canada",
        "navette aéroport à Québec, Québec, Canada",
    ]
    
    # Medium and smaller cities/towns
    medium_cities = [
        # English terms
        "limousine service in Saguenay, Quebec, Canada",
        "taxi service in Saguenay, Quebec, Canada", 
        "limousine service in Lévis, Quebec, Canada",
        "taxi service in Lévis, Quebec, Canada",
        "limousine service in Trois-Rivières, Quebec, Canada",
        "taxi service in Trois-Rivières, Quebec, Canada",
        "limousine service in Terrebonne, Quebec, Canada",
        "limousine service in Repentigny, Quebec, Canada",
        "limousine service in Brossard, Quebec, Canada",
        "limousine service in Drummondville, Quebec, Canada",
        "taxi service in Drummondville, Quebec, Canada",
        "limousine service in Saint-Jean-sur-Richelieu, Quebec, Canada",
        "taxi service in Saint-Jean-sur-Richelieu, Quebec, Canada",
        "limousine service in Granby, Quebec, Canada",
        "taxi service in Granby, Quebec, Canada",
        "limousine service in Blainville, Quebec, Canada",
        "limousine service in Saint-Jérôme, Quebec, Canada",
        "taxi service in Saint-Jérôme, Quebec, Canada",
        "limousine service in Mirabel, Quebec, Canada",
        "limousine service in Shawinigan, Quebec, Canada",
        "taxi service in Shawinigan, Quebec, Canada",
        "limousine service in Rimouski, Quebec, Canada",
        "taxi service in Rimouski, Quebec, Canada",
        "limousine service in Chicoutimi, Quebec, Canada",
        "taxi service in Chicoutimi, Quebec, Canada",
        "limousine service in Saint-Hyacinthe, Quebec, Canada",
        "taxi service in Saint-Hyacinthe, Quebec, Canada",
        "limousine service in Joliette, Quebec, Canada",
        "taxi service in Joliette, Quebec, Canada",
        "limousine service in Victoriaville, Quebec, Canada",
        "taxi service in Victoriaville, Quebec, Canada",
        "limousine service in Val-d'Or, Quebec, Canada",
        "taxi service in Val-d'Or, Quebec, Canada",
        "limousine service in Sept-Îles, Quebec, Canada",
        "taxi service in Sept-Îles, Quebec, Canada",
        "limousine service in Rouyn-Noranda, Quebec, Canada",
        "taxi service in Rouyn-Noranda, Quebec, Canada",
        
        # French terms for medium cities
        "service de limousine à Saguenay, Québec, Canada",
        "service de taxi à Saguenay, Québec, Canada",
        "service de limousine à Lévis, Québec, Canada", 
        "service de taxi à Lévis, Québec, Canada",
        "service de limousine à Trois-Rivières, Québec, Canada",
        "service de taxi à Trois-Rivières, Québec, Canada",
        "service de limousine à Drummondville, Québec, Canada",
        "service de taxi à Drummondville, Québec, Canada",
        "service de limousine à Saint-Jean-sur-Richelieu, Québec, Canada",
        "service de taxi à Saint-Jean-sur-Richelieu, Québec, Canada",
        "service de limousine à Granby, Québec, Canada",
        "service de taxi à Granby, Québec, Canada",
        "service de limousine à Saint-Jérôme, Québec, Canada",
        "service de taxi à Saint-Jérôme, Québec, Canada",
        "service de limousine à Shawinigan, Québec, Canada",
        "service de taxi à Shawinigan, Québec, Canada",
        "service de limousine à Rimouski, Québec, Canada",
        "service de taxi à Rimouski, Québec, Canada",
        "service de limousine à Chicoutimi, Québec, Canada",
        "service de taxi à Chicoutimi, Québec, Canada",
        "service de limousine à Saint-Hyacinthe, Québec, Canada",
        "service de taxi à Saint-Hyacinthe, Québec, Canada",
        "service de limousine à Joliette, Québec, Canada",
        "service de taxi à Joliette, Québec, Canada",
        "service de limousine à Victoriaville, Québec, Canada",
        "service de taxi à Victoriaville, Québec, Canada",
        "service de limousine à Val-d'Or, Québec, Canada",
        "service de taxi à Val-d'Or, Québec, Canada",
        "service de limousine à Sept-Îles, Québec, Canada",
        "service de taxi à Sept-Îles, Québec, Canada",
        "service de limousine à Rouyn-Noranda, Québec, Canada",
        "service de taxi à Rouyn-Noranda, Québec, Canada",
    ]
    
    # Rural and smaller communities
    rural_queries = [
        # Regional/rural areas - English
        "taxi service in Gaspésie, Quebec, Canada",
        "limousine service in Gaspésie, Quebec, Canada",
        "taxi service in Abitibi, Quebec, Canada",
        "limousine service in Abitibi, Quebec, Canada",
        "taxi service in Saguenay-Lac-Saint-Jean, Quebec, Canada",
        "limousine service in Saguenay-Lac-Saint-Jean, Quebec, Canada",
        "taxi service in Mauricie, Quebec, Canada",
        "limousine service in Mauricie, Quebec, Canada",
        "taxi service in Bas-Saint-Laurent, Quebec, Canada",
        "limousine service in Bas-Saint-Laurent, Quebec, Canada",
        "taxi service in Côte-Nord, Quebec, Canada",
        "limousine service in Côte-Nord, Quebec, Canada",
        "taxi service in Estrie, Quebec, Canada",
        "limousine service in Estrie, Quebec, Canada",
        "taxi service in Outaouais, Quebec, Canada",
        "limousine service in Outaouais, Quebec, Canada",
        "taxi service in Chaudière-Appalaches, Quebec, Canada",
        "limousine service in Chaudière-Appalaches, Quebec, Canada",
        
        # Regional/rural areas - French
        "service de taxi en Gaspésie, Québec, Canada",
        "service de limousine en Gaspésie, Québec, Canada",
        "service de taxi en Abitibi, Québec, Canada",
        "service de limousine en Abitibi, Québec, Canada",
        "service de taxi au Saguenay-Lac-Saint-Jean, Québec, Canada",
        "service de limousine au Saguenay-Lac-Saint-Jean, Québec, Canada",
        "service de taxi en Mauricie, Québec, Canada",
        "service de limousine en Mauricie, Québec, Canada",
        "service de taxi au Bas-Saint-Laurent, Québec, Canada",
        "service de limousine au Bas-Saint-Laurent, Québec, Canada",
        "service de taxi sur la Côte-Nord, Québec, Canada",
        "service de limousine sur la Côte-Nord, Québec, Canada",
        "service de taxi en Estrie, Québec, Canada",
        "service de limousine en Estrie, Québec, Canada",
        "service de taxi en Outaouais, Québec, Canada",
        "service de limousine en Outaouais, Québec, Canada",
        "service de taxi en Chaudière-Appalaches, Québec, Canada",
        "service de limousine en Chaudière-Appalaches, Québec, Canada",
        
        # Smaller towns - English
        "taxi service in Alma, Quebec, Canada",
        "taxi service in Dolbeau-Mistassini, Quebec, Canada",
        "taxi service in Roberval, Quebec, Canada",
        "taxi service in La Tuque, Quebec, Canada",
        "taxi service in Magog, Quebec, Canada",
        "taxi service in Cowansville, Quebec, Canada",
        "taxi service in Thetford Mines, Quebec, Canada",
        "taxi service in Montmagny, Quebec, Canada",
        "taxi service in Rivière-du-Loup, Quebec, Canada",
        "taxi service in Matane, Quebec, Canada",
        "taxi service in Gaspé, Quebec, Canada",
        "taxi service in New Carlisle, Quebec, Canada",
        "taxi service in Baie-Comeau, Quebec, Canada",
        "taxi service in Port-Cartier, Quebec, Canada",
        "taxi service in Fermont, Quebec, Canada",
        "taxi service in Amos, Quebec, Canada",
        "taxi service in La Sarre, Quebec, Canada",
        "taxi service in Malartic, Quebec, Canada",
        
        # Smaller towns - French
        "service de taxi à Alma, Québec, Canada",
        "service de taxi à Dolbeau-Mistassini, Québec, Canada",
        "service de taxi à Roberval, Québec, Canada",
        "service de taxi à La Tuque, Québec, Canada",
        "service de taxi à Magog, Québec, Canada",
        "service de taxi à Cowansville, Québec, Canada",
        "service de taxi à Thetford Mines, Québec, Canada",
        "service de taxi à Montmagny, Québec, Canada",
        "service de taxi à Rivière-du-Loup, Québec, Canada",
        "service de taxi à Matane, Québec, Canada",
        "service de taxi à Gaspé, Québec, Canada",
        "service de taxi à New Carlisle, Québec, Canada",
        "service de taxi à Baie-Comeau, Québec, Canada",
        "service de taxi à Port-Cartier, Québec, Canada",
        "service de taxi à Fermont, Québec, Canada",
        "service de taxi à Amos, Québec, Canada",
        "service de taxi à La Sarre, Québec, Canada",
        "service de taxi à Malartic, Québec, Canada",
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
        print(f"[INFO] Using comprehensive search: {len(city_queries)} queries")
    
    # Filter out French queries if requested
    if args.no_french:
        city_queries = [q for q in city_queries if not any(french_word in q.lower() for french_word in 
                       ['service de', 'à montréal', 'à québec', 'à laval', 'à gatineau', 'à sherbrooke', 
                        'en gaspésie', 'en abitibi', 'au saguenay', 'en mauricie', 'au bas-saint-laurent',
                        'sur la côte-nord', 'en estrie', 'en outaouais', 'en chaudière-appalaches'])]
        print(f"[INFO] Filtered out French queries, remaining: {len(city_queries)} queries")
    
    if not args.no_province_wide:
        city_queries.insert(0, "limousine service in Quebec, Canada")
        city_queries.insert(1, "taxi service in Quebec, Canada")
        if not args.no_french:
            city_queries.insert(2, "service de limousine au Québec, Canada")
            city_queries.insert(3, "service de taxi au Québec, Canada")

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