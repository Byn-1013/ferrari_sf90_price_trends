
from playwright.sync_api import sync_playwright
import re
import pandas as pd
from datetime import datetime, timedelta
from dateutil import tz

BASE_URL = "https://www.autotempest.com/trends?make=ferrari&model=sf90stradale&year_buckets=2020-2021%2C2022-2024&zip=90210"

TZ = tz.gettz("Europe/London")
TODAY = datetime.now(TZ).date()

def parse_date(label: str, today: datetime.date = TODAY) -> str:
    s = label.strip()
    if s.lower() == "today":
        return today.isoformat()
    m = re.match(r"(\d+)\s+days?\s+ago", s, re.IGNORECASE)
    if m:
        d = today - timedelta(days=int(m.group(1)))
        return d.isoformat()
    m2 = re.match(r"([A-Za-z]{3,})\s+(\d{1,2})(?:st|nd|rd|th)?", s)
    if m2:
        mon, day = m2.group(1), int(m2.group(2))
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(f"{day} {mon} {today.year}", fmt).date().isoformat()
            except ValueError:
                pass
    # last resort
    try:
        return pd.to_datetime(s).date().isoformat()
    except Exception:
        return s

def scrape_listings(page):
    # Returns list of dicts with title, raw_date_label, date, price_usd
    items = []
    cards = page.locator("section:has-text('All') ~ div >> css=div:has(h3)")
    count = cards.count()
    for i in range(count):
        card = cards.nth(i)
        title = card.locator("h3").inner_text().strip()
        price_text = None
        date_text = None
        # price is the first line starting with $ within the card
        price_candidates = card.locator(":text('$')")
        if price_candidates.count() > 0:
            price_text = price_candidates.nth(0).inner_text().strip()
        # find a date-ish line within the card
        all_text = card.inner_text().splitlines()
        for ln in all_text:
            ln = ln.strip()
            if re.match(r"(?i)today|\d+\s+days?\s+ago|[A-Za-z]{3,}\s+\d{1,2}(?:st|nd|rd|th)?", ln):
                date_text = ln
                break
        if price_text and date_text:
            price = int(re.sub(r"[^\d]", "", price_text))
            items.append({
                "title": title,
                "raw_date_label": date_text,
                "date": parse_date(date_text),
                "price_usd": price
            })
    return items

def click_all_more_results(page, max_clicks=200):
    clicks = 0
    while clicks < max_clicks:
        # 'More Results' button may load more via JS; try several selectors
        btn = page.locator("text=More Results")
        if btn.count() == 0 or not btn.first().is_enabled():
            break
        try:
            btn.first().click()
            page.wait_for_timeout(1200)
            clicks += 1
        except Exception:
            break
    return clicks

def collect_chart_network_data(page):
    # Listen to XHR/Fetch responses that might contain chart series
    captured = []
    def handle_response(response):
        try:
            url = response.url
            if "trends" in url or "chart" in url or "series" in url:
                if "application/json" in (response.headers or {}).get("content-type", ""):
                    captured.append({"url": url, "json": response.json()})
        except Exception:
            pass
    page.on("response", handle_response)
    return captured

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        captured = collect_chart_network_data(page)
        page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        click_all_more_results(page)
        data = scrape_listings(page)
        browser.close()
    df = pd.DataFrame(data, columns=["date", "price_usd", "raw_date_label", "title"])
    df.to_csv("sf90_autotempest_listings_full.csv", index=False)
    print(f"Saved {len(df)} rows to sf90_autotempest_listings_full.csv")
    # Optionally also dump any captured chart data for inspection
    try:
        import json
        with open("sf90_chart_network_dump.json", "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2, default=str)
        print(f"Captured {len(captured)} chart-related network payload(s).")
    except Exception as e:
        print("No chart data captured or error writing:", e)

run()
