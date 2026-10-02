"""JTclima -> Google Ads Custom feed (Business data). Pulls the WooCommerce Store API on jtclima.bg
and writes feed/jtclima_dynamic_remarketing_feed.csv in Google's Custom feed template column order.
Stdlib only. Refuses to overwrite the feed if the fetch looks wrong."""
import csv, html, json, re, sys, time, urllib.request

BASE = "https://jtclima.bg/wp-json/wc/store/v1/products?per_page=100&page=%d"
OUT = "feed/jtclima_dynamic_remarketing_feed.csv"
MIN_ROWS = 300
MIN_PRICE = 300  # EUR - products priced below this (sale price if any, else regular) are left out of the feed
HEADER = ["ID", "ID2", "Item title", "Final URL", "Image URL", "Item subtitle", "Item description",
          "Item category", "Price", "Sale price", "Contextual keywords", "Item address", "Tracking template",
          "Custom parameter", "Final mobile URL", "Android app link", "iOS app link", "iOS app store ID",
          "Formatted price", "Formatted sale price"]


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


def clip(s, n=25):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] if " " in s[:n] else s[:n]


def fmt(v, pr):
    """Bulgarian display price: '1 779,00 €' (non-breaking spaces so it never wraps)."""
    mu = pr.get("currency_minor_unit", 2)
    num = "{:,.{p}f}".format(int(v) / 10 ** mu, p=mu).replace(",", "\u00a0").replace(".", ",")
    cur = pr.get("currency_code", "EUR")
    return num + "\u00a0" + {"EUR": "€"}.get(cur, cur)

def money(v, pr):
    mu = pr.get("currency_minor_unit", 2)
    return "%s %s" % ("%.*f" % (mu, int(v) / 10 ** mu), pr.get("currency_code", "EUR"))


# Product type word put in front of the title (Google Ads item titles are max 25 chars).
# Name keywords win (they are specific); category keywords are the fallback.
NAME_TYPES = [("термопомпен бойлер", "Бойлер"), ("термопомп", "Термопомпа"), ("климатик", "Климатик"),
              ("буфер", "Буфер"), ("бойлер", "Бойлер"), ("конвектор", "Конвектор"), ("котел", "Котел"), ("котли", "Котел")]
CAT_TYPES = [("термопомпени бойлери", "Бойлер"), ("термопомп", "Термопомпа"), ("климатик", "Климатик"),
             ("касет", "Климатик"), ("канал", "Климатик"), ("колон", "Климатик"), ("таван", "Климатик"),
             ("вътрешни тела", "Вътрешно тяло"), ("външни тела", "Външно тяло"), ("бойлер", "Бойлер"),
             ("буфер", "Буфер"), ("конвектор", "Конвектор"), ("котли", "Котел")]

def product_type(cats, name):
    n = name.lower()
    for key, label in NAME_TYPES:
        if key in n:
            return label
    c = " ".join(cats).lower()
    for key, label in CAT_TYPES:
        if key in c:
            return label
    return ""

def with_type(ptype, brand, model, base, n=25):
    """'<type> <brand> <model>' if it fits in n chars, else drop the brand, else the model."""
    if not ptype or not (brand or model):
        return base
    for parts in ((ptype, brand, model), (ptype, model), (ptype, brand)):
        t = " ".join(dict.fromkeys(p for p in parts if p))
        if len(t) <= n and t != ptype:
            return t
    return clip(ptype + " " + base, n)

products, page = [], 1
while page <= 30:
    data = get(page)
    if not data:
        break
    products += data
    page += 1
    if len(data) < 100:
        break

rows, skipped, below_min = [], 0, 0
for r in products:
    pr = r["prices"]
    if not pr.get("price") or pr["price"] == "0" or not r.get("is_in_stock", True):
        skipped += 1
        continue
    name = html.unescape(r["name"])
    toks = [t.strip(",;") for t in name.split()]
    lat = [t for t in toks if re.search(r"[A-Za-z]", t)]
    brand = lat[0] if lat else ""
    model = next((t for t in reversed(toks) if re.search(r"\d", t) and re.search(r"[A-Za-z]", t)), "")
    title = clip(" ".join(dict.fromkeys([brand, model])).strip() or name)
    cyr = " ".join(t for t in toks if not re.search(r"[A-Za-z0-9]", t))
    cats = [html.unescape(c["name"]) for c in r.get("categories", []) if not c["name"].isdigit()]
    cat = cats[0] if cats else ""
    title = with_type(product_type(cats, name), brand, model, title)
    price = money(pr["regular_price"], pr)
    sale = money(pr["sale_price"], pr) if pr["sale_price"] and pr["sale_price"] != pr["regular_price"] else ""
    mu = pr.get("currency_minor_unit", 2)
    effective = int(pr["sale_price"] if sale else pr["regular_price"]) / 10 ** mu
    if effective < MIN_PRICE:
        below_min += 1
        continue
    img = r["images"][0]["src"] if r.get("images") else ""
    kw = ";".join(dict.fromkeys(([clip(cyr, 60)] if cyr else []) + cats))
    rows.append([r["id"], "", title, r["permalink"], img, clip(cat), clip(cyr), cat, price, sale, kw] + [""] * 7 + [fmt(pr["regular_price"], pr), fmt(pr["sale_price"], pr) if sale else ""])

if len(rows) < MIN_ROWS:
    raise SystemExit("Only %d products (min %d) - feed NOT overwritten" % (len(rows), MIN_ROWS))

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(HEADER)
    w.writerows(rows)
print("%d fetched, %d written, %d skipped (no price / out of stock), %d below %d EUR" % (len(products), len(rows), skipped, below_min, MIN_PRICE))
