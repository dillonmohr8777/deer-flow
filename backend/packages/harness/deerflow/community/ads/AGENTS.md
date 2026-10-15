# Read-only ads tools

`google_ads_report` (GAQL) and `meta_ads_insights` (Insights GET). Read-only by construction: Google only calls `googleAds:search`, Meta only GETs `/insights`.

- Credentials are per user: `{DEER_FLOW_HOME}/users/<user_id>/integrations/ads/credentials.json` (chmod 600), resolved with `get_effective_user_id()`. No env or global fallback, so one user can never read another's tokens.
- Client scoping: `google_ads.allowed_customer_ids` / `meta_ads.allowed_account_ids` in that file are the only IDs a user can query.
- File shape: `{"google_ads": {"client_id", "client_secret", "refresh_token", "login_customer_id", "allowed_customer_ids": [...], "developer_token"?}, "meta_ads": {"access_token", "allowed_account_ids": [...]}}`.
- GAQL guard (`validate_gaql`): single SELECT, FROM one of campaign/ad_group/keyword_view/search_term_view/customer, no mutate-like words (string literals ignored), LIMIT capped at 1000.
- Every result carries a `source` stamp (platform, ISO read time, masked account). Missing metrics are `null`, never 0. `derive.best_month` needs spend >= 150 and >= 5 conversions/leads.
- Tests (`backend/tests/test_ads_readonly_tools.py`) mock HTTP; the one live test needs `DEER_FLOW_ADS_LIVE_GOOGLE_CUSTOMER` and `DEER_FLOW_RUN_LIVE_TESTS=1`.
