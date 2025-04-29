#!/usr/bin/env python3
# Requirements: requests, beautifulsoup4, selenium, webdriver-manager, fake-useragent
# Install with:
#   pip install requests beautifulsoup4 selenium webdriver-manager fake-useragent

import os
import re
import json
import time
import logging
import random
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
from fake_useragent import UserAgent

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_page(url, max_retries=3, timeout=10):
    """
    Uses Firefox (via Selenium) to render JavaScript and return page HTML.
    Handles dynamic loading and infinite scroll for Zumiez, with anti-bot bypass.
    """
    ua = UserAgent()
    options = Options()
    options.headless = False  # Disable headless mode to avoid detection
    options.set_preference("permissions.default.geo", 2)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("permissions.default.desktop-notification", 2)
    options.add_argument(f'--user-agent={ua.random}')
    options.add_argument('--width=1920')  # Set window size to mimic real browser
    options.add_argument('--height=1080')

    service = Service(GeckoDriverManager().install())
    
    for attempt in range(max_retries):
        driver = None
        try:
            logging.info(f"Fetching {url} (Attempt {attempt + 1})")
            driver = webdriver.Firefox(service=service, options=options)
            driver.set_page_load_timeout(timeout)  # Set timeout to avoid long waits
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Zumiez: handle dynamic loading and infinite scroll
            if "zumiez.com" in url:
                # Initial wait for dynamic content to load
                time.sleep(random.uniform(5, 7))
                logging.info("Initial wait for dynamic content")

                # Check if redirected to an unexpected page (e.g., "Stash")
                current_url = driver.current_url
                if "stash" in current_url.lower():
                    logging.error("Redirected to Stash page, likely due to anti-bot protection")
                    return None

                # Try to get the total item count from the page (e.g., "19 items found")
                try:
                    # Wait for the item count element to be visible
                    count_element = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, ".CategoryPage-ItemsCount, .ProductGrid-Header-count, .results-count, [class*='count'], .product-count, h1 + div, span[class*='count'], .ProductGrid-Count, .ProductGrid-Header span"))
                    )
                    total_items_text = count_element.text
                    total_items = int(re.search(r'\d+', total_items_text).group())
                    logging.info(f"Page reports {total_items} items")
                except:
                    total_items = None
                    logging.warning("Could not find total item count on page")

                # Infinite scroll to load all items
                logging.info("Attempting infinite scroll")
                max_scroll_attempts = 20
                scroll_attempts = 0
                previous_item_count = 0

                while scroll_attempts < max_scroll_attempts:
                    # Scroll to the bottom
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(random.uniform(6, 9))  # Increased wait time with randomness

                    # Check current number of product containers
                    current_items = len(driver.find_elements(By.CSS_SELECTOR, "li.ProductCard"))
                    logging.info(f"Scroll attempt {scroll_attempts + 1}: found {current_items} items")

                    # Check if redirected during scrolling
                    current_url = driver.current_url
                    if "stash" in current_url.lower():
                        logging.error("Redirected to Stash page during scrolling")
                        return None

                    # If we have a total item count, stop when we reach it
                    if total_items and current_items >= total_items:
                        logging.info(f"Reached target item count: {current_items}/{total_items}")
                        break

                    # If no new items loaded, stop
                    if current_items == previous_item_count and current_items > 0:
                        logging.info("No more items to load (infinite scroll)")
                        break

                    previous_item_count = current_items
                    scroll_attempts += 1

                # Final wait for any remaining AJAX content
                time.sleep(random.uniform(3, 5))
                logging.info("Final wait for AJAX content")

            html = driver.page_source
            logging.info(f"Successfully fetched {url}")
            return html

        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logging.error(f"Max retries reached for {url}")
                return None
        finally:
            if driver:
                driver.quit()

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
            "https://www.zumiez.com/skate/components/wheels.html?customFilters=brand:Bones,OJ%20Wheels,Spitfire;promotion_flag:Sale"
        )

    def parse(self, html):
        """
        Parse Zumiez sale wheels using specific selectors for products, names, and prices.
        Includes store availability for location-specific data (currently disabled).
        """
        if not html:
            logging.error("No HTML to parse")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        # Save raw HTML for debugging
        with open("zumiez_debug.html", "w", encoding="utf-8") as f:
            f.write(html)

        # Product container selector
        product_grid = soup.select("li.ProductCard")
        logging.info(f"Found {len(product_grid)} product containers")

        for product in product_grid:
            try:
                # Find product link
                link = product.select_one("a.ProductCard-Link")
                if not link:
                    logging.warning("No link found for product")
                    continue
                href = link["href"]
                if href.startswith("/"):
                    href = "https://www.zumiez.com" + href
                if href in seen:
                    logging.info(f"Duplicate URL skipped: {href}")
                    continue
                seen.add(href)

                # Extract name
                name_el = product.select_one(".ProductCard-Name")
                name = name_el.get_text(strip=True) if name_el else link.find("img", alt=True).get("alt", "").strip()
                if not name:
                    logging.warning(f"No name found for {href}")
                    continue

                # Extract prices
                sale_price_el = product.select_one(".ProductPrice-PriceValue")
                original_price_el = product.select_one(".ProductCardPrice-HighPrice")
                sale_price = sale_price_el.get_text(strip=True).replace("$", "") if sale_price_el else None
                original_price = original_price_el.get_text(strip=True).replace("$", "") if original_price_el else None

                if not sale_price:
                    logging.warning(f"No sale price found for {href}")
                    continue

                # Check store availability (disabled for now to speed up the script)
                availability = "Check store"
                """
                product_count = 0  # Counter for limiting product page fetches
                if product_count < 3:  # Limit to 3 products to avoid slowing down the script
                    availability_el = product.select_one(".store-availability, .availability")
                    if availability_el:
                        availability = availability_el.get_text(strip=True)
                    else:
                        product_html = fetch_page(href, timeout=10)
                        if product_html:
                            product_soup = BeautifulSoup(product_html, "html.parser")
                            availability = product_soup.select_one(".pickup-availability, .store-pickup-info, .availability, [class*='pickup'], [data-store-availability]").get_text(strip=True) if product_soup.select_one(".pickup-availability, .store-pickup-info, .availability, [class*='pickup'], [data-store-availability]") else "Not available in-store"
                        product_count += 1
                """

                products.append({
                    "name": name,
                    "url": href,
                    "price_new": sale_price,
                    "price_old": original_price,
                    "availability": availability
                })
                logging.info(f"Parsed product: {name}")

            except Exception as e:
                logging.error(f"Error parsing product: {e}")
                continue

        logging.info(f"Parsed {len(products)} products")
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

if __name__ == "__main__":
    main()