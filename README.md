# JTclima Google Ads feed

Daily-refreshed product feed for **Google Ads > Business data > Custom** (dynamic remarketing), built from the
public WooCommerce Store API of jtclima.bg. Product data only (names, prices, links, images) - all already public on the site.

Feed URL for Google Ads (scheduled fetch):
https://raw.githubusercontent.com/martingalabov-jpg/jtclima-feed/main/feed/jtclima_dynamic_remarketing_feed.csv

* `build_feed.py` - generates the CSV (stdlib only). Refuses to overwrite it if fewer than 300 products come back.
* `.github/workflows/refresh-feed.yml` - runs it every day and commits the result.
* `ID` = WooCommerce product ID = the `item_id` the site pushes to the dataLayer (GTM sends it as `dynx_itemid`).
