"""JTclima -> OpenAI Ads product feed (SFTP snapshot). Pulls the public WooCommerce Store API on
jtclima.bg and writes feed/jtclima_openai_products.csv (+ .csv.gz) in OpenAI's product schema
(developers.openai.com/commerce/specs/file-upload/products). Stdlib only.
Only heat-pump products are marked is_ads_eligible=true; the rest stay in the feed for search only.
Refuses to overwrite the feed if the fetch looks wrong."""
import csv, gzip, html, json, re, shutil, sys, time, urllib.parse, urllib.request

BASE = "https://jtclima.bg/wp-json/wc/store/v1/products?per_page=100&page=%d"
OUT = "feed/jtclima_openai_products.csv"
MIN_ROWS = 300
SELLER = "JT Clima"
SELLER_URL = "https://jtclima.bg/"
# Category names (any level) that make a product eligible for ChatGPT Ads.
ADS_CATEGORY_KEYS = ("термопомп",)  # термопомпи, термопомпа моноблок/сплит, термопомпени бойлери, за басейни
MIN_PRICE = 300  # EUR, effective price (sale if any, else regular) - cheaper products are left out of the feed
HEADER = ["item_id", "title", "description", "url", "brand", "seller_name", "seller_url", "image_url",
          "additional_image_urls", "availability", "price", "sale_price", "condition", "product_category",
          "is_ads_eligible"]


def get(page):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE % page, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
        except Exception as e:  # network / WAF / json
            last = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit("Store API page %d failed: %r" % (page, last))


def text(s, n):
    s = re.sub(r"</?(p|div|li|ul|ol|br|h\d|tr|td|th|table)\b[^>]*>", " ", s or "", flags=re.I)  # block tags -> space
    s = html.unescape(re.sub(r"<[^>]+>", "", s))  # inline tags (<strong>11</strong>.<strong>2</strong>) -> nothing
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0]


def money(v, pr):
    mu = pr.get("currency_minor_unit", 2)
    return "%.*f %s" % (mu, int(v) / 10 ** mu, pr.get("currency_code", "EUR"))


def iri(u):
    """Percent-encode non-ASCII (Cyrillic) path characters; keep URLs that are already encoded."""
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(p.path, safe="/%")))


def category_path(cats):
    """Root-to-leaf path, ordered by the depth of each category's /product-category/ URL."""
    def depth(c):
        return len([s for s in urllib.parse.urlsplit(c.get("link", "")).path.split("/") if s])
    names = [html.unescape(c["name"]) for c in sorted(cats, key=depth) if not c["name"].isdigit()]
    return " > ".join(dict.fromkeys(names))


def brand_of(r, name):
    for a in r.get("attributes", []):
        if a.get("taxonomy") == "pa_proizvoditel" and a.get("terms"):
            return html.unescape(a["terms"][0]["name"])
    if r.get("brands"):
        return html.unescape(r["brands"][0]["name"])
    lat = [t.strip(",;") for t in name.split() if re.search(r"[A-Za-z]", t)]
    return lat[0] if lat else SELLER


products, page = [], 1
while page <= 30:
    data = get(page)
    if not data:
        break
    products += data
    page += 1
    if len(data) < 100:
        break

rows, skipped, eligible, below_min = [], 0, 0, 0
for r in products:
    pr = r["prices"]
    if not pr.get("regular_price") or pr["regular_price"] == "0" or not r.get("images"):
        skipped += 1
        continue
    name = text(r["name"], 150)
    desc = text((r.get("short_description") or "") + " " + (r.get("description") or ""), 5000) or name
    cats = r.get("categories", [])
    path = category_path(cats)
    sale = ""
    if pr.get("sale_price") and int(pr["sale_price"]) < int(pr["regular_price"]):
        sale = money(pr["sale_price"], pr)
    effective = int(pr["sale_price"] if sale else pr["regular_price"]) / 10 ** pr.get("currency_minor_unit", 2)
    if effective < MIN_PRICE:
        below_min += 1
        continue
    ads = any(k in path.lower() for k in ADS_CATEGORY_KEYS)
    eligible += ads
    if r.get("is_in_stock", True):
        avail = "in_stock"
    elif r.get("is_on_backorder"):
        avail = "backorder"
    else:
        avail = "out_of_stock"
    imgs = [iri(i["src"]) for i in r["images"]]
    rows.append([str(r["id"]), name, desc, iri(r["permalink"]), brand_of(r, name), SELLER, SELLER_URL, imgs[0],
                 ",".join(u.replace(",", "%2C") for u in imgs[1:10]), avail, money(pr["regular_price"], pr), sale,
                 "new", path, "true" if ads else "false"])

if len(rows) < MIN_ROWS:
    raise SystemExit("Only %d products (min %d) - feed NOT overwritten" % (len(rows), MIN_ROWS))

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    w.writerow(HEADER)
    w.writerows(rows)
with open(OUT, "rb") as src, gzip.open(OUT + ".gz", "wb") as dst:
    shutil.copyfileobj(src, dst)
print("%d fetched, %d written (%d ads-eligible heat pumps), %d skipped (no price / no image), %d below %d EUR"
      % (len(products), len(rows), eligible, skipped, below_min, MIN_PRICE))
