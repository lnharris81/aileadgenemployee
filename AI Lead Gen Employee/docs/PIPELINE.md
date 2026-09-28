# Pipeline reference

## Stages and state
Each command reads and writes `data/leadgen.db`. Companies move through: sourced (`crawl_status` NULL) -> crawled (`ok` / `error`) -> scored (`score`, `qualified` 0/1). Contacts move through `verify_status`: `unverified` -> `unknown` (local check, `verify_detail` says `mx_ok`, `a_only`, `mx_unchecked`) -> `valid` / `catch_all` / `risky` / `invalid` (provider). Contact `status`: `new` -> `pushed`, or `do_not_contact` (suppressed).

```
source osm/places/apollo/csv/add      companies (+ contacts when the source has emails)
crawl                                  contacts (email_source=crawl), company phone/socials/description/signals
contacts hunter / apollo / pattern     contacts with names, titles, emails, pattern
verify local / hunter / instantly      contacts.verify_status
score                                  companies.score / qualified, contacts.is_primary
export / push                          reads only, marks contacts.pushed
report                                 reads only, writes data/exports/<campaign>_report_<ts>.html
```

## Tables
**companies**: id, dedup_key, name, domain, website, phone, address, city, state, postal_code, country, lat, lng, category, industry, employees, description, rating, review_count, linkedin_url, facebook_url, instagram_url, twitter_url, youtube_url, tiktok_url, yelp_url, google_maps_url, email_pattern, signals (JSON), source, sources (JSON list), source_ref, crawl_status, crawl_at, crawl_pages, crawl_error, contact_providers (JSON list), score, score_reasons, qualified, tags, notes, timestamps.

**contacts**: id, company_id, email (unique), email_type (`personal`, `role`, `personal_webmail`, `third_party`), email_source (`crawl`, `osm`, `csv`, `hunter`, `apollo`, `pattern`, `web_research`), email_confidence (0-100), first_name, last_name, title, seniority, department, linkedin_url, phone, verify_status, verify_provider, verify_detail, verify_at, is_primary, status, pushed (JSON), source_ref, timestamps.

**suppression**: kind (`email` / `domain`), value, reason. **runs**: every command with args and stats. **api_usage**: paid calls per provider. **dns_cache**: MX/A results per domain.

## Dedup
Companies merge on domain first, then on a key built from phone, then from normalized name + city. Merging fills blank fields only and appends the new source to `sources`. Contacts merge on email, then on (company, first name, last name). A social URL given as the website is moved to the matching `*_url` column instead.

## Crawl signals (in `companies.signals`)
`booking_widget`, `chat_widget`, `analytics_pixel`, `cms_wordpress`, `cms_wix`, `cms_squarespace`, `cms_shopify`, `cms_godaddy`, `cms_weebly`, `cms_webflow`, `cms_duda`, `cms_hubspot`, `cms_ghl`, `ecommerce`, `reviews_widget`, `email_marketing`, `ai_or_chatbot`, `financing_or_pricing`, `hiring`, `site_stale` (copyright year older than last year), `copyright_year`, `https`, `mobile_viewport`, `has_form`, `email_on_site`, `pages_crawled`, `cms`, `generator`.

Use them in `icp.json` under `signals.bonus`. `"no_booking_widget": 15` rewards sites without a booking tool; `"cms_wix": 5` rewards Wix sites.

## Scoring
Default weights (override under `scoring.weights`):
```
has_email +25   personal_email +10   verified_email +15   catch_all_email +5   mx_ok_email +5
has_phone +10   has_website +10      keyword_match +10    title_match +10      has_social +3
rating_ok +5    no_email -15         third_party_email_only -10   pattern_email_only -5
rating_below_min -20   reviews_below_min -10
```
Disqualifiers (score kept, `qualified` = 0, reason starts with `DISQUALIFIED`): an `exclude_keywords` hit in name/category/industry/description, suppressed domain, `require_website` with no site, headcount outside `employees_min/max`.
Qualified = not disqualified and score >= `scoring.qualify_threshold`. `score --explain` prints the live table.

Primary contact per company is chosen by: has email, not suppressed, not invalid, provider-verified first, title match, personal > webmail > role > third party, not pattern-guessed, then confidence.

Email types are judged against the company's domain and name. An address on another organization's domain is `third_party`, even a role mailbox (`info@webagency.com`). When it was found by the crawler (web agency credit, WordPress author, parent company, form placeholder) it is kept for reference but never becomes primary, never exports, and never pushes. Provider or CSV contacts on another domain stay usable, ranked last, with `third_party_email_only` applied.

## Export selection
Default: qualified companies, one row each (the primary contact), emails that are not invalid and not suppressed, contacts not already pushed to that target (push only). Flags: `--all`, `--all-contacts`, `--verified-only`, `--no-unverified`, `--include-no-email`, `--min-score`, `--source`, `--limit`.
