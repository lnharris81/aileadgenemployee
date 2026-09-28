# Connectors

Both connectors are dry-run by default. Without `--yes` they resolve the target, print two sample payloads and the count, and stop. Nothing here sends email.

## Instantly (API v2)
Endpoints used (from `https://api.instantly.ai/openapi/api_v2.json`): `GET /api/v2/campaigns` (resolve by name), `GET/POST /api/v2/lead-lists` (resolve or create a list), `POST /api/v2/leads/add` (bulk add, batches of 100), `POST /api/v2/email-verification` and `GET /api/v2/email-verification/{email}` (verify). Auth: `Authorization: Bearer <key>`.

Setup: Instantly -> Settings -> Integrations -> API keys -> create a key with scopes `campaigns:read`, `leads:create`, `lead_lists:read`, `lead_lists:create`, and `email_verification:create` if you want verification. Put it in `.env` as `INSTANTLY_API_KEY`.

Usage:
```
python3 scripts/leadgen.py push instantly --list "my-campaign leads"        # safest: a list, attach to a campaign later
python3 scripts/leadgen.py push instantly --campaign "My Campaign"       # by name (exact, case-insensitive) or campaign id
python3 scripts/leadgen.py push instantly --campaign ... --yes                  # live
```
Each lead carries email, first/last name, company, website, phone, job title, and custom variables (`city`, `state`, `country`, `category`, `domain`, `rating`, `review_count`, `verify_status`, `email_type`, `score`, `signals`, `source`, `lead_id`, `google_maps_url`, `description`) usable as `{{city}}` etc. in sequences.
Options: `--verify-on-import` (Instantly verifies with its credits), `--no-skip-workspace` (default skips leads already anywhere in the workspace), `--batch 100`, `--repush`. A warning is printed when the target campaign is active.
Result fields reported: leads_uploaded, skipped_count, duplicated_leads, invalid_email_count, in_blocklist.

## GoHighLevel (API v2, LeadConnector)
Endpoint: `POST https://services.leadconnectorhq.com/contacts/upsert` with headers `Authorization: Bearer <token>`, `Version: 2021-07-28` (override with `GHL_API_VERSION`). Upsert matches on email (and phone) inside the location, so re-runs update instead of duplicating.

Setup: Agency or sub-account -> Settings -> Private Integrations -> create token with `contacts.write` and `contacts.readonly`. Put it in `.env` as `GHL_API_KEY`. The sub-account id (Settings -> Business Profile, or the id in the dashboard URL) goes in `GHL_LOCATION_ID`.

Usage:
```
python3 scripts/leadgen.py push ghl --tag lead-gen-employee --tag my-campaign
python3 scripts/leadgen.py push ghl --tag ... --yes
```
Each contact carries first/last name (or the company name as `name` when no person is known), email, phone, companyName, website, address, city, state, postalCode, country, `source` = "Lead Gen Employee", and tags (your `--tag` values plus the campaign slug and category). Tags overwrite the contact's existing tags. Requests are throttled to 8 per second under the 100-per-10-seconds burst limit.

## Other tools
Smartlead and lemlist: `export --format smartlead` or `lemlist` and upload the CSV. Any other tool: `export --format generic` and map columns in its importer.

## Adding a connector
Create `scripts/leadgen/connectors/<tool>.py` with `build_<thing>(row)` (pure function, unit-testable) and `push(conn, key, rows, ..., yes=False, log=print)`. Keep dry-run as the default, record results in `contacts.pushed`, call `db.log_usage`, and add a `push <tool>` subparser in `cli.py`. Add a test for the payload builder in `scripts/tests/test_leadgen.py`.
