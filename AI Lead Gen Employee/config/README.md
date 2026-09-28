# config/

`icp.json` is the Ideal Customer Profile for the current campaign. It ships blank: `leadgen init`
writes an empty profile and nothing runs until it is filled in. Tell the employee about your business
(or run `/define-icp`) and it writes this file. `examples/` holds finished profiles for five industries
to start from; `leadgen config examples` lists them.

| Key | What it does |
|---|---|
| `campaign` | Slug used in export filenames and connector tags. |
| `offer` | What you sell, in one line. Shown in the report header and used by Claude to pick keywords and signals. |
| `niche` | Plain-language description of who you want. |
| `geography.places` | Place names for `leadgen source osm`, `leadgen source places`, and the Apollo location filter in `leadgen run`. Geocoded with OpenStreetMap Nominatim. |
| `geography.country` | Two-letter code. Drives phone normalization. |
| `geography.radius_km` | Search radius around each place for Google Places grid search. |
| `company.keywords` | Any match in name, category, industry, or description adds score. |
| `company.exclude_keywords` | Any match disqualifies the company. |
| `company.employees_min` / `employees_max` | Only applied when headcount is known (Apollo). |
| `company.min_rating` / `min_reviews` | Only applied when ratings are known (Google Places). |
| `company.require_website` | Disqualify companies with no website. |
| `contacts.titles` | Title keywords for choosing the primary contact (a match adds score) and for Apollo people search. |
| `contacts.seniorities` | Apollo seniority filters. |
| `contacts.accept_role_email` | Whether info@ / office@ style mailboxes count as leads. |
| `contacts.prefer_personal_email` | When a company has both, pick the named person's address over the role inbox as the primary contact. |
| `signals.bonus` | Score adjustments keyed on crawl signals. Prefix `no_` to reward the absence of a signal. See docs/PIPELINE.md for the signal list. |
| `scoring.qualify_threshold` | Minimum score to be marked qualified. |
| `scoring.weights` | Override any default weight (see `leadgen score --explain`). |
| `sources.*` | Defaults for the sourcing commands so `leadgen run` can work without flags. |
| `targets.leads` | How many qualified leads you want. `leadgen status` shows progress against it. |
