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
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from selenium.common.exceptions import TimeoutException, WebDriverException

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_page(url, max_retries=3, timeout=30):
    """
    Uses Chrome (via Selenium) to render JavaScript and return page HTML.
    Handles dynamic loading and infinite scroll for Zumiez, with anti-bot bypass.
    """
    ua = UserAgent()
    for attempt in range(max_retries):
        user_agent = ua.random
        logging.info(f"Using user agent: {user_agent}")

        options = Options()
        options.headless = os.getenv("CI", "false").lower() == "true"  # Headless in CI
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        chromedriver_path = "/usr/local/bin/chromedriver" if os.getenv("CI") else ChromeDriverManager().install()
        service = Service(executable_path=chromedriver_path)

        driver = None
        try:
            logging.info(f"Fetching {url} (Attempt {attempt + 1})")
            logging.info(f"Using chromedriver at {service.path}")

            driver_attempts = 3
            for driver_attempt in range(driver_attempts):
                try:
                    logging.info(f"Initializing WebDriver (Attempt {driver_attempt + 1})")
                    driver = webdriver.Chrome(service=service, options=options)
                    logging.info("WebDriver initialized successfully")
                    break
                except TimeoutException as e:
                    logging.error(f"TimeoutException during WebDriver init: {e}")
                    if driver_attempt < driver_attempts - 1:
                        time.sleep(5)
                        continue
                    else:
                        raise

            driver.set_page_load_timeout(timeout)
            time.sleep(random.uniform(1, 3))
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            if "zumiez.com" in url:
                time.sleep(random.uniform(3, 5))
                logging.info("Initial wait for dynamic content")

                current_url = driver.current_url
                if "stash" in current_url.lower():
                    logging.error("Redirected to Stash page, retrying")
                    driver.quit()
                    continue

                logging.info("Attempting infinite scroll")
                max_scroll_attempts = 5
                scroll_attempts = 0
                previous_item_count = 0

                while scroll_attempts < max_scroll_attempts:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(random.uniform(2, 4))
                    current_items = len(driver.find_elements(By.CSS_SELECTOR, "li.ProductCard"))
                    logging.info(f"Scroll attempt {scroll_attempts + 1}: found {current_items} items")

                    current_url = driver.current_url
                    if "stash" in current_url.lower():
                        logging.error("Redirected to Stash page during scrolling")
                        driver.quit()
                        return None

                    if current_items == previous_item_count and current_items > 0:
                        logging.info("No more items to load")
                        break

                    previous_item_count = current_items
                    scroll_attempts += 1

                time.sleep(random.uniform(2, 4))
                logging.info("Final wait for AJAX content")

                try:
                    driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(random.uniform(1, 2))
                    count_element = WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".CategoryPage-ItemsCount"))
                    )
                    WebDriverWait(driver, 15).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, ".CategoryPage-ItemsCount"))
                    )
                    total_items_text = count_element.text
                    total_items = int(re.search(r'\d+', total_items_text).group())
                    logging.info(f"Page reports {total_items} items")
                except Exception as e:
                    logging.warning(f"Could not find total item count: {e}")
                    debug_html = driver.page_source
                    save_debug_file("zumiez_debug_item_count.html", debug_html)
                    logging.info("Saved page source for debugging")

            html = driver.page_source
            logging.info(f"Successfully fetched {url}")
            return html

        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logging.error(f"Max retries reached for {url}")
                return None
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logging.warning(f"Error quitting driver: {e}")

def save_debug_file(filename, content):
    """Safely save debug files to the current working directory."""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Debug file saved: {filename}")
    except Exception as e:
        logging.error(f"Failed to save debug file {filename}: {e}")

class Scraper:
    def __init__(self, name, url, part):
        self.name = name
        self.url = url
        self.part = part

    def scrape(self):
        html = fetch_page(self.url)
        return self.parse(html)

    def parse(self, html):
        raise NotImplementedError

class ZumiezScraper(Scraper):
    def parse(self, html):
        if not html:
            logging.error("No HTML to parse")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        save_debug_file(f"zumiez_debug_{self.part.lower()}.html", html)
        product_grid = soup.select("li.ProductCard")
        logging.info(f"Found {len(product_grid)} product containers")

        for product in product_grid:
            try:
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

                name_el = product.select_one(".ProductCard-Name")
                name = name_el.get_text(strip=True) if name_el else link.find("img", alt=True).get("alt", "").strip()
                if not name:
                    logging.warning(f"No name found for {href}")
                    continue

                if self.part == "Wheels":
                    if not any(brand in name for brand in ["Bones", "Powell", "Spitfire", "OJ"]):
                        logging.info(f"Skipping product not from Bones, Powell, Spitfire, or OJ: {name}")
                        continue

                sale_price_el = product.select_one(".ProductPrice-PriceValue")
                original_price_el = product.select_one(".ProductCardPrice-HighPrice")
                sale_price = sale_price_el.get_text(strip=True).replace("$", "") if sale_price_el else None
                original_price = original_price_el.get_text(strip=True).replace("$", "") if original_price_el else None

                if not sale_price:
                    logging.warning(f"No sale price found for {href}")
                    continue

                availability = "Check store"
                products.append({
                    "name": name,
                    "url": href,
                    "price_new": sale_price,
                    "price_old": original_price,
                    "availability": availability,
                    "part": self.part
                })
                logging.info(f"Parsed product: {name}")

            except Exception as e:
                logging.error(f"Error parsing product: {e}")
                continue

        logging.info(f"Parsed {len(products)} products")
        return products

class SkateWarehouseScraper(Scraper):
    def parse(self, html):
        if not html:
            logging.error("No HTML to parse")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        save_debug_file(f"skatewarehouse_debug_{self.part.lower()}.html", html)

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]

            # Skip non-product links
            if not href.startswith("/products/") and not href.startswith("/product/"):
                continue

            # Filter based on part type
            if self.part == "Wheels" and "Wheels" not in text:
                continue
            if self.part == "Trucks" and "Truck" not in text:
                continue
            if self.part == "Bearings" and "Bearings" not in text:
                continue

            if href.startswith("/"):
                href = "https://www.skatewarehouse.com" + href
            if href in seen:
                logging.info(f"Duplicate URL skipped: {href}")
                continue

            prices = re.findall(r"\$(\d+\.\d{2})", text)
            if not prices:
                continue

            name = text.split(f"${prices[0]}")[0].strip()
            if not name:
                logging.warning(f"No name found for {href}")
                continue

            if self.part == "Wheels":
                if not any(brand in name for brand in ["Bones", "Powell", "Spitfire", "OJ"]):
                    logging.info(f"Skipping product not from Bones, Powell, Spitfire, or OJ: {name}")
                    continue
            elif self.part == "Trucks":
                if not any(brand in name for brand in ["Independent", "Indy", "Ace"]):
                    logging.info(f"Skipping product not from Independent or Ace Trucks: {name}")
                    continue

            seen.add(href)
            price_old = prices[1] if len(prices) > 1 else None
            products.append({
                "name": name,
                "url": href,
                "price_new": prices[0],
                "price_old": price_old,
                "availability": "Check store",
                "part": self.part
            })
            logging.info(f"Parsed product: {name}")

        logging.info(f"Parsed {len(products)} products")
        return products

class CCSScraper(Scraper):
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
            name = title_el.get_text(strip=True)

            if self.part == "Wheels":
                if not any(brand in name for brand in ["Bones", "Powell", "Spitfire", "OJ"]):
                    logging.info(f"Skipping product not from Bones, Powell, Spitfire, or OJ: {name}")
                    continue

            seen.add(href)
            old_el = prod.select_one(".product-price--compare")
            products.append({
                "name": name,
                "url": href,
                "price_new": sale_el.get_text(strip=True),
                "price_old": old_el.get_text(strip=True) if old_el else None,
                "availability": "Check store",
                "part": self.part
            })
        return products

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
                    "new": it["price_new"],
                    "name": it["name"]
                })
        curr_urls = {i["url"] for i in items}
        for url, pi in prev_map.items():
            if url not in curr_urls:
                diffs.append({"type": "removed", "item": pi})
        if diffs:
            changes[site] = diffs
    return changes

def calculate_percent_off(price_new, price_old):
    try:
        new = float(price_new)
        old = float(price_old)
        if old <= 0:
            return "N/A"
        percent_off = ((old - new) / old) * 100
        return f"{percent_off:.2f}%"
    except (ValueError, TypeError):
        return "N/A"

def generate_html_chart(data, changes, output_file="sale_items_chart.html"):
    """
    Generate an HTML chart with current sale items and historical changes for all sites.
    Includes a Store column, Part column, % Off column, and sorting functionality.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sale Items and Changes</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #f4f4f4;
            }
            h1, h2 {
                text-align: center;
                color: #333;
            }
            h2 {
                margin-top: 40px;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                background-color: #fff;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
            }
            th, td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }
            th {
                background-color: #007bff;
                color: white;
                cursor: pointer;
            }
            th:hover {
                background-color: #0056b3;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            tr:hover {
                background-color: #f1f1f1;
            }
            a {
                color: #007bff;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            .new {
                background-color: #e6ffe6;
            }
            .price-change {
                background-color: #fff3cd;
            }
            .removed {
                background-color: #ffe6e6;
            }
            .section {
                margin-bottom: 40px;
            }
        </style>
        <script>
            function sortTable(tableId, colIndex, isNumeric = false) {
                const table = document.getElementById(tableId);
                let rows = Array.from(table.rows).slice(1); // Skip header row
                const isAsc = table.rows[0].cells[colIndex].getAttribute('data-sort') !== 'asc';
                
                rows.sort((a, b) => {
                    let aValue = a.cells[colIndex].innerText.trim();
                    let bValue = b.cells[colIndex].innerText.trim();
                    
                    if (isNumeric) {
                        aValue = parseFloat(aValue.replace('%', '')) || 0;
                        bValue = parseFloat(bValue.replace('%', '')) || 0;
                        return isAsc ? aValue - bValue : bValue - aValue;
                    } else {
                        return isAsc ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
                    }
                });
                
                // Update sort direction
                table.rows[0].cells[colIndex].setAttribute('data-sort', isAsc ? 'asc' : 'desc');
                
                // Re-append sorted rows
                const tbody = table.getElementsByTagName('tbody')[0];
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
            }
        </script>
    </head>
    <body>
        <h1>Sale Items and Changes</h1>
    """

    # Current Sale Items - Single table with Store and Part columns
    html_content += """
        <div class="section">
            <h2>Current Sale Items</h2>
            <table id="table-all">
                <thead>
                    <tr>
                        <th onclick="sortTable('table-all', 0)">Store</th>
                        <th onclick="sortTable('table-all', 1)">Part</th>
                        <th onclick="sortTable('table-all', 2)">Product Name</th>
                        <th onclick="sortTable('table-all', 3, true)">New Price ($)</th>
                        <th onclick="sortTable('table-all', 4, true)">Old Price ($)</th>
                        <th onclick="sortTable('table-all', 5, true)">% Off</th>
                        <th onclick="sortTable('table-all', 6)">Availability</th>
                    </tr>
                </thead>
                <tbody>
    """
    all_items = []
    for site, items in data.items():
        if not items:
            continue
        for item in items:
            all_items.append(item)

    for item in all_items:
        percent_off = calculate_percent_off(item["price_new"], item["price_old"])
        html_content += f"""
                <tr>
                    <td>{item['store']}</td>
                    <td>{item['part']}</td>
                    <td><a href="{item['url']}" target="_blank">{item['name']}</a></td>
                    <td>{item['price_new']}</td>
                    <td>{item['price_old'] if item['price_old'] else 'N/A'}</td>
                    <td>{percent_off}</td>
                    <td>{item['availability']}</td>
                </tr>
        """
    html_content += """
                </tbody>
            </table>
        </div>
    """

    # Historical Changes for each site
    html_content += """
        <div class="section">
            <h2>Historical Changes</h2>
    """
    if not changes:
        html_content += "<p>No changes detected since the last run.</p>"
    else:
        for site, site_changes in changes.items():
            html_content += f"<h3>{site}</h3>"

            # New Items
            new_items = [change for change in site_changes if change["type"] == "new"]
            if new_items:
                html_content += """
                <h4>New Items</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Product Name</th>
                            <th>New Price ($)</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in new_items:
                    item = change["item"]
                    html_content += f"""
                        <tr class="new">
                            <td><a href="{item['url']}" target="_blank">{item['name']}</a></td>
                            <td>{item['price_new']}</td>
                        </tr>
                    """
                html_content += """
                    </tbody>
                </table>
                """

            # Price Changes
            price_changes = [change for change in site_changes if change["type"] == "price_change"]
            if price_changes:
                html_content += """
                <h4>Price Changes</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Product Name</th>
                            <th>Old Price ($)</th>
                            <th>New Price ($)</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in price_changes:
                    html_content += f"""
                        <tr class="price-change">
                            <td><a href="{change['url']}" target="_blank">{change['name']}</a></td>
                            <td>{change['old']}</td>
                            <td>{change['new']}</td>
                        </tr>
                    """
                html_content += """
                    </tbody>
                </table>
                """

            # Removed Items
            removed_items = [change for change in site_changes if change["type"] == "removed"]
            if removed_items:
                html_content += """
                <h4>Removed Items</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Product Name</th>
                            <th>Last Known Price ($)</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in removed_items:
                    item = change["item"]
                    html_content += f"""
                        <tr class="removed">
                            <td>{item['name']}</td>
                            <td>{item['price_new']}</td>
                        </tr>
                    """
                html_content += """
                    </tbody>
                </table>
                """

    html_content += """
        </div>
    </body>
    </html>
    """

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"Generated HTML chart at {output_file}")

def main():
    scrapers = [
        ZumiezScraper("Zumiez", "https://www.zumiez.com/skate/components/wheels.html?customFilters=brand:Bones,OJ%20Wheels,Powell,Spitfire;promotion_flag:Sale", "Wheels"),
        SkateWarehouseScraper("SkateWarehouse", "https://www.skatewarehouse.com/searchresults.html?filter_cat=SALEWHEELS&filter_type=Wheels#filter_cat=SALEWHEELS&filter_type=Wheels&brand_str%5B%5D=Bones%20Wheels&brand_str%5B%5D=Spitfire&opt_page=1&opt_sort=alphaAtoZ&opt_perpage=20", "Wheels"),
        CCSScraper("CCS", "https://shop.ccs.com/collections/clearance/skateboard-wheels", "Wheels"),
        ZumiezScraper("Zumiez", "https://www.zumiez.com/skate/components/trucks.html?customFilters=brand:Ace%20Trucks,Independent;promotion_flag:Sale", "Trucks"),
        SkateWarehouseScraper("SkateWarehouse", "https://www.skatewarehouse.com/Clearance_Skateboard_Trucks/catpage-SALETRUCKS.html", "Trucks"),
        SkateWarehouseScraper("SkateWarehouse", "https://www.skatewarehouse.com/Clearance_Skateboard_Parts/catpage-BOXLSHOES.html", "Bearings")
    ]

    current = {f"{s.name}_{s.part}": s.scrape() for s in scrapers}

    for site, items in current.items():
        print(f"{site}: {len(items)} items scraped")

    combined_data = {}
    for site_key, items in current.items():
        store, part = site_key.split("_")
        combined_items = []
        for item in items:
            item["store"] = store
        combined_items.extend(items)
        combined_data[site_key] = combined_items

    previous = load_previous()
    diffs = compare(previous, combined_data)
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

    generate_html_chart(combined_data, diffs)
    save_current(combined_data)

if __name__ == "__main__":
    main()