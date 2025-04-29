#!/usr/bin/env python3
# Requirements: requests, beautifulsoup4, selenium, webdriver-manager
# Install with:
#   pip install requests beautifulsoup4 selenium webdriver-manager

import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

def fetch_page(url):
    """
    Uses headless Firefox (via Selenium) to render JavaScript and return page HTML,
    dismissing Zumiez 'load more' behavior.
    """
    options = Options()
    options.headless = True
    options.set_preference("permissions.default.geo", 2)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("permissions.default.desktop-notification", 2)

    service = Service(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    driver.get(url)
    WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")

    # Zumiez: click any 'load more' buttons
    if "zumiez.com" in url:
        while True:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "button.load-more-button, button.load-more, .load-more-btn")
                driver.execute_script("arguments[0].scrollIntoView();", btn)
                btn.click()
                time.sleep(1)
            except:
                break

    time.sleep(2)
    html = driver.page_source
    driver.quit()
    return html

class Scraper:
    def __init__(self, name, url):
        self.name = name
        self.url = url

    def scrape(self):
        html = fetch_page(self.url)
        return self.parse(html)

    def parse(self, html):
        raise NotImplementedError

class ZumiezScraper(Scraper):
    def __init__(self):
        super().__init__(
            "Zumiez",
            "https://www.zumiez.com/skate/components/wheels.html?customFilters=promotion_flag:Sale"
        )

    def parse(self, html):
        """
        Parse Zumiez sale wheels by locating product links and extracting names/prices.
        """
        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        # 1) Find every link to a skateboard-wheels product page
        for link in soup.find_all("a", href=re.compile(r"-skateboard-wheels\.html$")):
            href = link["href"]
            if href.startswith("/"):
                href = "https://www.zumiez.com" + href
            if href in seen:
                continue
            seen.add(href)

            # 2) Derive the product name
            name = link.get_text(strip=True)
            if not name and (img := link.find("img")):
                name = img.get("alt", "").strip()

            # 3) Climb up the DOM to grab the first $XX.XX you find
            price_new = None
            parent = link
            for _ in range(4):
                parent = parent.parent
                if not parent:
                    break
                txt = parent.get_text(separator=" ", strip=True)
                m = re.search(r"\$(\d+\.\d{2})", txt)
                if m:
                    price_new = m.group(1)
                    break

            # 4) Record it
            products.append({
                "name": name,
                "url": href,
                "price_new": price_new,
                "price_old": None
            })

        return products

class SkateWarehouseScraper(Scraper):
    def __init__(self):
        super().__init__(
            "SkateWarehouse",
            "https://www.skatewarehouse.com/Clearance_Skateboard_Wheels/catpage-SALEWHEELS.html"
        )

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if "Wheels" not in text:
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.skatewarehouse.com" + href
            if href in seen:
                continue
            prices = re.findall(r"\$(\d+\.\d{2})", text)
            if not prices:
                continue
            name = text.split(f"${prices[0]}")[0].strip()
            price_old = prices[1] if len(prices) > 1 else None
            seen.add(href)
            products.append({
                "name": name,
                "url": href,
                "price_new": prices[0],
                "price_old": price_old
            })
        return products

class CCSScraper(Scraper):
    def __init__(self):
        super().__init__(
            "CCS",
            "https://shop.ccs.com/collections/clearance/skateboard-wheels"
        )

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        for prod in soup.select(".product-item"):
            title_el = prod.select_one(".product-title")
            sale_el = prod.select_one(".product-price--sale") or prod.select_one(".product-price")
            link_el = prod.select_one("a")
            if not (title_el and sale_el and link_el):
                continue
            href = link_el.get("href")
            if href.startswith("/"):
                href = "https://shop.ccs.com" + href
            if href in seen:
                continue
            seen.add(href)
            old_el = prod.select_one(".product-price--compare")
            products.append({
                "name": title_el.get_text(strip=True),
                "url": href,
                "price_new": sale_el.get_text(strip=True),
                "price_old": old_el.get_text(strip=True) if old_el else None
            })
        return products

# Utility functions
def load_previous(path="previous_data.json"):
    return json.load(open(path)) if os.path.exists(path) else {}

def save_current(data, path="previous_data.json"):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def compare(prev, curr):
    changes = {}
    for site, items in curr.items():
        prev_map = {i["url"]: i for i in prev.get(site, [])}
        diffs = []
        for it in items:
            pi = prev_map.get(it["url"])
            if not pi:
                diffs.append({"type": "new", "item": it})
            elif it["price_new"] != pi.get("price_new"):
                diffs.append({
                    "type": "price_change",
                    "url": it["url"],
                    "old": pi.get("price_new"),
                    "new": it["price_new"]
                })
        curr_urls = {i["url"] for i in items}
        for url, pi in prev_map.items():
            if url not in curr_urls:
                diffs.append({"type": "removed", "item": pi})
        if diffs:
            changes[site] = diffs
    return changes

def main():
    scrapers = [ZumiezScraper(), SkateWarehouseScraper(), CCSScraper()]
    current = {s.name: s.scrape() for s in scrapers}

    # Print summary
    for site, items in current.items():
        print(f"{site}: {len(items)} items scraped")

    previous = load_previous()
    diffs = compare(previous, current)
    if diffs:
        print("Changes detected:")
        for site, changes in diffs.items():
            print(f"\n{site}:")
            for c in changes:
                if c["type"] == "new":
                    print(f"  New: {c['item']['name']} at {c['item']['price_new']}")
                elif c["type"] == "price_change":
                    print(f"  Price change: {c['old']} -> {c['new']} | {c['url']}")
                elif c["type"] == "removed":
                    print(f"  Removed: {c['item']['name']}")
    else:
        print("No changes detected.")

    save_current(current)

if __name__ == "__main__"