# AI Lead Gen Employee

A Claude Code project that works as a lead generation employee. Tell it who you sell to and where, and it builds a large, clean lead list with a point-of-contact email for each company, then hands you a CSV or pushes the leads into Instantly or GoHighLevel.

It runs on stock Python 3.9+ with no packages to install (macOS: if `python3` is not found, run `xcode-select --install` once; Windows: install Python from python.org and tick "Add to PATH"). The free path (no API keys) already produces real lists; keys add coverage, named contacts, verification, and push.

## Quick start
Open this folder in Claude Code (desktop app: Code tab, pick the folder) and say **"set this up for me"**.
The employee checks your machine, asks what you sell and who you want to reach, writes the campaign
profile, and then builds the list. It ships with no niche or city configured; it asks you.

From a terminal instead:
```
python3 scripts/leadgen.py init                 # blank config/icp.json and .env
python3 scripts/leadgen.py config examples      # five industry profiles to copy from
python3 scripts/leadgen.py doctor --network     # what works with the keys you have
python3 scripts/leadgen.py run                  # source -> crawl -> verify -> score -> export, once icp.json is filled in
python3 scripts/leadgen.py report --open        # the interactive dashboard
```

## What you get
`run` uses only free sources unless you add keys. With Places, Apollo, or Hunter keys in `.env` it also calls those, within default caps (100 Places requests, 1 Apollo page, 25 Hunter requests per run).

A CSV in `data/exports/` with one row per company (or per contact with `--all-contacts`):
company, website, domain, **email**, email type (personal / role / webmail), email source, confidence, verify status, contact name and title, phones, address, city, state, category, rating, reviews, social links, description, ICP score with reasons, website signals, and the source reference for every row.

## How it works
| Stage | Command | Free? | What happens |
|---|---|---|---|
| Source | `source osm` | yes | OpenStreetMap businesses by category and place |
| Source | `source places` | paid | Google Places text search, grid-tiled to beat the 60-result cap |
| Source | `source apollo` | paid | Apollo B2B company search by keyword, location, headcount |
| Source | `source csv`, `add` | yes | Your own lists, or companies Claude finds by web research |
| Enrich | `crawl` | yes | Polite crawl of each site: emails (incl. obfuscated), phones, socials, signals |
| Enrich | `contacts hunter` / `apollo` / `pattern` | paid / paid / free | Named decision makers, email pattern, pattern-filled addresses |
| Verify | `verify --provider local` | yes | Syntax, disposable, MX record |
| Verify | `verify --provider hunter` / `instantly` | paid | Mailbox-level deliverability |
| Qualify | `score` | yes | Explainable ICP score, primary contact per company |
| Deliver | `export` | yes | generic, instantly, ghl, smartlead, lemlist CSV formats |
| Deliver | `report` | yes | one-file interactive HTML dashboard: overview, searchable lead explorer with a detail drawer per lead, zoomable map, insights; light and dark |
| Deliver | `push instantly` / `push ghl` | keys | API push, dry-run first, `--yes` to go live |

Everything is stored in `data/leadgen.db` (SQLite) and deduplicated by domain. Re-running any stage only does new work.

## Skills (Claude procedures)
`/setup`, `/define-icp`, `/find-leads`, `/research-leads`, `/enrich-leads`, `/qualify-leads`, `/export-leads`, `/push-leads`, and `/lead-data-rules`. Each is a checklist in `.claude/skills/<name>/SKILL.md` that keeps results consistent from run to run.

## Keys (all optional, in `.env`)
`GOOGLE_PLACES_API_KEY`, `APOLLO_API_KEY`, `HUNTER_API_KEY`, `INSTANTLY_API_KEY`, `GHL_API_KEY` + `GHL_LOCATION_ID`. `doctor` tells you which are set without printing them.

## Docs
- `docs/PIPELINE.md` stages, schema, statuses, signals, scoring weights.
- `docs/SOURCES.md` each provider, coverage, cost, and how to get volume.
- `docs/CONNECTORS.md` Instantly and GoHighLevel setup and behavior.
- `config/README.md` every key in `icp.json`.

## Tests
```
python3 -m unittest discover -s scripts/tests -q
```
No network needed.

## Rules the employee follows
Finds and qualifies, never sends. Every row has a source. Guessed emails stay flagged until verified. Invalid and suppressed contacts never leave the system. Paid steps have caps. Pushes are dry-run until you say yes. See `.claude/skills/lead-data-rules/SKILL.md` for the compliance notes per country.
