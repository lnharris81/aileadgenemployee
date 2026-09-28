# Sources

## OpenStreetMap (Overpass) - free
`source osm --category <preset> --place "City, ST"` or `--tags amenity=dentist` or `--bbox s,w,n,e`.
Places are geocoded with Nominatim (1 request per second, by policy). The query asks for every named node/way/relation matching the tags inside the place's bounding box. Presets: `source osm --list-categories`. Raw tags accept `k=v`, `k~regex`, and `;` for AND (`shop=hairdresser;male=yes`).

Coverage: excellent for restaurants, cafes, shops, clinics, salons, gyms in cities; thinner for home-service trades (plumbers, roofers) which often have no storefront. Website and phone tags exist on roughly 30 to 60 percent of entries depending on the area. Fill gaps with `/research-leads` or Google Places.

Volume: run several places (suburbs) and several categories. Big bounding boxes can time out on the public server; split them. Two mirrors are tried automatically; on 429/504 the client waits and retries.

## Google Places API (New) - paid
`source places --place "City, ST" --query "dentist" --query "dental office" --cell-km 4 --max-requests 100`
Text Search returns at most 60 results per query (3 pages of 20). `--cell-km` tiles a square of `radius_km` around the place into cells and searches each cell with a `locationRestriction`, which is how you reach thousands. `--dry-run` prints the plan and the request estimate. Each request is billed at the Places "Enterprise" tier because the field mask includes website and phone; check current pricing in Google Cloud. `--type dentist` adds an `includedType` filter.

Fields captured: name, address components, website, national and international phone, rating, review count, primary type, business status (permanently closed places are skipped), Maps URL, coordinates. Best data quality of the sources.

Setup: Google Cloud project -> enable "Places API (New)" -> API key restricted to that API -> `GOOGLE_PLACES_API_KEY`.

## Apollo.io - paid plan
`source apollo --keyword "dental" --location "Texas, US" --employees 1,10 --employees 11,50 --pages 1`
The default is 1 page; raise `--pages` only after the user agrees to the credits. Organization search costs 1 credit per page of up to 100 companies and requires a paid Apollo plan for API search. Filters: industry keyword tags, HQ locations, headcount ranges. Captures website, phone, city/state, industry, headcount, LinkedIn, description.

People: `contacts apollo --max-credits 50 --per-company 1` searches decision makers by the company domains already in the store plus `contacts.titles` / `contacts.seniorities` from `icp.json` (search is free), then reveals emails with `people/match` (1 credit per revealed email). Verified addresses arrive as `verify_status=valid`.

## Hunter.io - paid, free tier
`contacts hunter --only-qualified --max-requests 50`
One request per company domain returns up to 10 named people with titles, seniority, department, confidence, plus the domain's email pattern (`{first}.{last}` style) which `contacts pattern` uses to fill addresses for other named people. Domain search skips site-builder hosts (wixsite.com and similar) where it would return nothing. `verify --provider hunter` checks single addresses.

## CSV and web research - free
`source csv file.csv` maps common headers automatically (Business Name, Website, Phone, Email, City, First Name...). Override with `--map field=Column`. Rows with an email or a first+last name also create a contact.
`add --name .. --website .. --ref <url>` records one company from research with its provenance. `set <id> --website ..` fills a missing site so the crawler can run.

## Choosing sources by niche
| Niche | Start with | Then |
|---|---|---|
| Local storefront (dentists, salons, gyms, restaurants) | osm | places grid for completeness |
| Home services (roofers, HVAC, plumbers) | places grid | osm craft=* tags, research for associations |
| Professional services (law, accounting, agencies) | osm office=* + places | apollo for named partners |
| B2B / SaaS / manufacturers | apollo | research (associations, directories) |
| Existing list | csv | crawl + verify |
