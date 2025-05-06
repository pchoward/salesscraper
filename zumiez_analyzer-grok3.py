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
import datetime
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

def fetch_page(url, max_retries=3, timeout=45):
    ua = UserAgent()
    for attempt in range(max_retries):
        user_agent = ua.random
        logging.info(f"Using user agent: {user_agent}")

        options = Options()
        options.headless = os.getenv("CI", "false").lower() == "true"
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # CI-specific options
        if os.getenv("CI"):
            unique_dir = f"/tmp/chrome_user_data_{int(time.time())}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
            options.add_argument(f"--user-data-dir={unique_dir}")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            logging.info(f"Using unique user data directory: {unique_dir}")

        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") if os.getenv("CI") else ChromeDriverManager().install()
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
            time.sleep(random.uniform(2, 5))
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            time.sleep(random.uniform(5, 8))
            logging.info("Initial wait for dynamic content")
            
            current_url = driver.current_url
            if "stash" in current_url.lower():
                logging.error("Redirected to Stash page, retrying")
                driver.quit()
                time.sleep(random.uniform(5, 10))
                continue

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "li.ProductCard, .product-card, .product-item, a[href*='deck'], a[href*='wheels'], a[href*='truck'], a[href*='bearings']"))
                )
                logging.info("Product listings detected")
            except Exception as e:
                logging.warning(f"Could not detect product listings: {e}")

            logging.info("Attempting infinite scroll")
            max_scroll_attempts = 8
            scroll_attempts = 0
            previous_item_count = 0

            while scroll_attempts < max_scroll_attempts:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(3, 6))
                current_items = len(driver.find_elements(By.CSS_SELECTOR, "li.ProductCard, .product-card, .product-item, a[href*='deck'], a[href*='wheels'], a[href*='truck'], a[href*='bearings']"))
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

            time.sleep(random.uniform(3, 6))
            logging.info("Final wait for AJAX content")

            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(random.uniform(2, 4))

            html = driver.page_source
            logging.info(f"Successfully fetched {url}")
            return html

        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt + random.uniform(5, 10))
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

                # Log discount percentage for decks
                if self.part == "Decks":
                    percent_off = calculate_percent_off(sale_price, original_price)
                    logging.info(f"Deck {name}: {percent_off} off")
                    try:
                        percent_off_value = float(percent_off.strip("%"))
                        if percent_off_value < 30:
                            logging.info(f"Skipping deck with less than 30% off: {name} ({percent_off})")
                            continue
                    except (ValueError, TypeError):
                        logging.info(f"Skipping deck with invalid % off: {name} ({percent_off})")
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

            # Skip non-product links (relaxed filter)
            if not any(part in href.lower() for part in ["wheels", "truck", "bearings", "deck"]) and not any(brand.lower() in href.lower() for brand in ["bones", "spitfire", "independent", "bronson"]):
                continue

            # Filter based on part type
            if self.part == "Wheels" and "Wheels" not in text:
                continue
            if self.part == "Trucks" and "Truck" not in text:
                continue
            if self.part == "Bearings" and "Bearings" not in text:
                continue
            if self.part == "Decks" and "Deck" not in text:
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
            elif self.part == "Decks":
                # Calculate % off and filter for 30%+ discount
                price_new = prices[0]
                price_old = prices[1] if len(prices) > 1 else None
                percent_off = calculate_percent_off(price_new, price_old)
                logging.info(f"Deck {name}: {percent_off} off")
                try:
                    percent_off_value = float(percent_off.strip("%"))
                    if percent_off_value < 30:
                        logging.info(f"Skipping deck with less than 30% off: {name} ({percent_off})")
                        continue
                except (ValueError, TypeError):
                    logging.info(f"Skipping deck with invalid % off: {name} ({percent_off})")
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
        if not html:
            logging.error("No HTML to parse")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        save_debug_file(f"ccs_debug_{self.part.lower()}.html", html)

        for prod in soup.select(".product-item"):
            try:
                title_el = prod.select_one(".product-title")
                sale_el = prod.select_one(".product-price--sale") or prod.select_one(".product-price")
                link_el = prod.select_one("a")
                if not (title_el and sale_el and link_el):
                    logging.warning("Missing title, price, or link for product")
                    continue

                name = title_el.get_text(strip=True)
                if not name:
                    logging.warning("No name found for product")
                    continue

                href = link_el.get("href")
                if href.startswith("/"):
                    href = "https://shop.ccs.com" + href
                if href in seen:
                    logging.info(f"Duplicate URL skipped: {href}")
                    continue
                seen.add(href)

                price_text = sale_el.get_text(strip=True)
                prices = re.findall(r"\$(\d+\.\d{2})", price_text)
                if not prices:
                    logging.warning(f"No prices found for {href}")
                    continue
                price_new = prices[0]
                price_old = prices[1] if len(prices) > 1 else None

                # For decks, filter for 30%+ discount
                if self.part == "Decks":
                    percent_off = calculate_percent_off(price_new, price_old)
                    logging.info(f"Deck {name}: {percent_off} off")
                    try:
                        percent_off_value = float(percent_off.strip("%"))
                        if percent_off_value < 30:
                            logging.info(f"Skipping deck with less than 30% off: {name} ({percent_off})")
                            continue
                    except (ValueError, TypeError):
                        logging.info(f"Skipping deck with invalid % off: {name} ({percent_off})")
                        continue

                if self.part == "Wheels":
                    if not any(brand in name for brand in ["Bones", "Powell", "Spitfire", "OJ"]):
                        logging.info(f"Skipping product not from Bones, Powell, Spitfire, or OJ: {name}")
                        continue

                products.append({
                    "name": name,
                    "url": href,
                    "price_new": price_new,
                    "price_old": price_old,
                    "availability": "Check store",
                    "part": self.part
                })
                logging.info(f"Parsed product: {name}")

            except Exception as e:
                logging.error(f"Error parsing product: {e}")
                continue

        logging.info(f"Parsed {len(products)} products")
        return products

class ZumiezDecksScraper(ZumiezScraper):
    def __init__(self):
        super().__init__("Zumiez", "https://www.zumiez.com/skate/skateboard-decks.html?customFilters=promotion_flag:Sale", "Decks")

class TacticsDecksScraper(Scraper):
    def __init__(self):
        super().__init__("Tactics", "https://www.tactics.com/skateboard-decks/sale", "Decks")

    def parse(self, html):
        if not html:
            logging.error("No HTML to parse")
            return []

        soup = BeautifulSoup(html, "html.parser")
        products = []
        seen = set()

        save_debug_file(f"tactics_debug_decks.html", html)

        product_containers = soup.select(".product-card")
        logging.info(f"Found {len(product_containers)} product containers")

        for container in product_containers:
            try:
                link = container.select_one("a[href]")
                if not link:
                    logging.warning("No link found for product")
                    continue
                href = link["href"]
                if href.startswith("/"):
                    href = "https://www.tactics.com" + href
                if href in seen:
                    logging.info(f"Duplicate URL skipped: {href}")
                    continue
                seen.add(href)

                name_el = container.select_one(".product-card__title")
                name = name_el.get_text(strip=True) if name_el else ""
                if not name:
                    logging.warning(f"No name found for {href}")
                    continue

                price_new_el = container.select_one(".product-card__price--sale")
                price_old_el = container.select_one(".product-card__price--compare")
                price_new = price_new_el.get_text(strip=True).replace("$", "") if price_new_el else None
                price_old = price_old_el.get_text(strip=True).replace("$", "") if price_old_el else None

                if not (price_new and price_old):
                    logging.warning(f"No prices found for {href}")
                    continue

                # Calculate % off and filter for 30%+ discount
                percent_off = calculate_percent_off(price_new, price_old)
                logging.info(f"Deck {name}: {percent_off} off")
                try:
                    percent_off_value = float(percent_off.strip("%"))
                    if percent_off_value < 30:
                        logging.info(f"Skipping deck with less than 30% off: {name} ({percent_off})")
                        continue
                except (ValueError, TypeError):
                    logging.info(f"Skipping deck with invalid % off: {name} ({percent_off})")
                    continue

                products.append({
                    "name": name,
                    "url": href,
                    "price_new": price_new,
                    "price_old": price_old,
                    "availability": "Check store",
                    "part": self.part
                })
                logging.info(f"Parsed product: {name}")

            except Exception as e:
                logging.error(f"Error parsing product: {e}")
                continue

        logging.info(f"Parsed {len(products)} products")
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
    Generate an improved HTML chart with enhanced historical changes section.
    Enhancements: add part type and date to changes, show change summary in headers, enable sorting.
    """
    # Get the current date and time for historical changes and title
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sale Items and Changes</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Roboto', sans-serif;
                margin: 20px;
                background-color: #f5f7fa;
                color: #333;
            }}
            h1, h2, h3 {{
                text-align: center;
                color: #2c3e50;
            }}
            h1 {{
                font-size: 2.2em;
                margin-bottom: 20px;
            }}
            h2 {{
                font-size: 1.8em;
                margin-top: 40px;
            }}
            h3 {{
                font-size: 1.4em;
                margin: 20px 0;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            h3::before {{
                content: '▼';
                font-size: 0.8em;
                transition: transform 0.3s;
            }}
            h3.collapsed::before {{
                content: '▶';
                transform: rotate(0deg);
            }}
            .summary {{
                background-color: #ffffff;
                padding: 15px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                margin-bottom: 20px;
                text-align: center;
            }}
            .search-container {{
                margin: 20px 0;
                text-align: center;
            }}
            .search-container input {{
                padding: 10px;
                width: 300px;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 1em;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                background-color: #ffffff;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                border-radius: 8px;
                overflow: hidden;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #e0e0e0;
            }}
            th {{
                background: linear-gradient(135deg, #3498db, #2980b9);
                color: white;
                position: sticky;
                top: 0;
                z-index: 1;
                cursor: pointer;
                font-weight: 500;
            }}
            th:hover {{
                background: linear-gradient(135deg, #2980b9, #1c5f8a);
            }}
            th::after {{
                content: '';
                margin-left: 5px;
                font-size: 0.8em;
            }}
            th.asc::after {{
                content: '↑';
            }}
            th.desc::after {{
                content: '↓';
            }}
            tr:nth-child(even) {{
                background-color: #f9f9f9;
            }}
            tr:hover {{
                background-color: #f1f1f1;
            }}
            a {{
                color: #3498db;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            .new {{
                background-color: #e6f7e6;
            }}
            .price-change {{
                background-color: #fff4e1;
            }}
            .removed {{
                background-color: #ffe6e6;
            }}
            .section {{
                margin-bottom: 40px;
            }}
            .collapsible-content {{
                display: block;
                transition: max-height 0.3s ease-out;
                overflow: hidden;
            }}
            .collapsible-content.collapsed {{
                display: none;
            }}
            @media (max-width: 768px) {{
                table {{
                    display: block;
                    overflow-x: auto;
                }}
                th, td {{
                    min-width: 120px;
                }}
            }}
        </style>
        <script>
            function sortTable(tableId, colIndex, isNumeric = false) {{
                const table = document.getElementById(tableId);
                let rows = Array.from(table.rows).slice(1);
                const isAsc = table.rows[0].cells[colIndex].getAttribute('data-sort') !== 'asc';
                
                rows.sort((a, b) => {{
                    let aValue = a.cells[colIndex].innerText.trim();
                    let bValue = b.cells[colIndex].innerText.trim();
                    
                    if (isNumeric) {{
                        aValue = parseFloat(aValue.replace('$', '').replace('%', '')) || 0;
                        bValue = parseFloat(bValue.replace('$', '').replace('%', '')) || 0;
                        return isAsc ? aValue - bValue : bValue - aValue;
                    }} else {{
                        return isAsc ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
                    }}
                }});
                
                table.rows[0].cells[colIndex].setAttribute('data-sort', isAsc ? 'asc' : 'desc');
                for (let i = 0; i < table.rows[0].cells.length; i++) {{
                    table.rows[0].cells[i].classList.remove('asc', 'desc');
                }}
                table.rows[0].cells[colIndex].classList.add(isAsc ? 'asc' : 'desc');
                
                const tbody = table.getElementsByTagName('tbody')[0];
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
            }}

            function searchTable() {{
                const input = document.getElementById('searchInput').value.toLowerCase();
                const tables = document.getElementsByTagName('table');
                
                for (let table of tables) {{
                    const rows = table.getElementsByTagName('tr');
                    for (let i = 1; i < rows.length; i++) {{
                        const cells = rows[i].getElementsByTagName('td');
                        let match = false;
                        for (let cell of cells) {{
                            if (cell.innerText.toLowerCase().includes(input)) {{
                                match = true;
                                break;
                            }}
                        }}
                        rows[i].style.display = match ? '' : 'none';
                    }}
                }}
            }}

            function toggleSection(element) {{
                const content = element.nextElementSibling;
                element.classList.toggle('collapsed');
                content.classList.toggle('collapsed');
            }}
        </script>
    </head>
    <body>
        <h1>Skateboard Sale Items and Changes as of {current_datetime}</h1>
    """

    # Summary Statistics
    summary = {}
    for site_key, items in data.items():
        store, part = site_key.split("_")
        if store not in summary:
            summary[store] = {}
        summary[store][part] = len(items)

    html_content += "<div class='summary'><h2>Summary</h2>"
    for store, parts in summary.items():
        total = sum(parts.values())
        parts_str = ", ".join([f"{count} {part}" for part, count in parts.items()])
        html_content += f"<p><strong>{store}</strong>: {total} items ({parts_str})</p>"
    html_content += "</div>"

    # Search Bar
    html_content += """
        <div class="search-container">
            <input type="text" id="searchInput" onkeyup="searchTable()" placeholder="Search items...">
        </div>
    """

    # Current Sale Items - Grouped by Store
    html_content += "<div class='section'><h2>Current Sale Items</h2>"
    stores = sorted(set(site_key.split("_")[0] for site_key in data.keys()))
    for store in stores:
        store_items = []
        for site_key, items in data.items():
            if site_key.startswith(store):
                store_items.extend(items)
        if not store_items:
            continue

        html_content += f"<h3>{store}</h3>"
        html_content += f"<table id='table-{store.lower()}'>"
        html_content += """
            <thead>
                <tr>
                    <th onclick="sortTable('table-{}', 0)">Part</th>
                    <th onclick="sortTable('table-{}', 1)">Product Name</th>
                    <th onclick="sortTable('table-{}', 2, true)">New Price ($)</th>
                    <th onclick="sortTable('table-{}', 3, true)">Old Price ($)</th>
                    <th onclick="sortTable('table-{}', 4, true)">% Off</th>
                    <th onclick="sortTable('table-{}', 5)">Availability</th>
                </tr>
            </thead>
            <tbody>
        """.format(store.lower(), store.lower(), store.lower(), store.lower(), store.lower(), store.lower())

        for item in store_items:
            percent_off = calculate_percent_off(item["price_new"], item["price_old"])
            html_content += f"""
                <tr>
                    <td>{item['part']}</td>
                    <td><a href="{item['url']}" target="_blank">{item['name']}</a></td>
                    <td>{item['price_new']}</td>
                    <td>{item['price_old'] if item['price_old'] else 'N/A'}</td>
                    <td>{percent_off}</td>
                    <td>{item['availability']}</td>
                </tr>
            """
        html_content += "</tbody></table>"
    html_content += "</div>"

    # Historical Changes with Enhanced Details
    html_content += """
        <div class="section">
            <h2>Historical Changes</h2>
    """
    if not changes:
        html_content += "<p>No changes detected since the last run.</p>"
    else:
        for site, site_changes in changes.items():
            # Calculate summary of changes
            new_count = len([c for c in site_changes if c["type"] == "new"])
            price_change_count = len([c for c in site_changes if c["type"] == "price_change"])
            removed_count = len([c for c in site_changes if c["type"] == "removed"])
            summary_parts = []
            if new_count > 0:
                summary_parts.append(f"{new_count} New")
            if price_change_count > 0:
                summary_parts.append(f"{price_change_count} Price Changes")
            if removed_count > 0:
                summary_parts.append(f"{removed_count} Removed")
            summary_text = ", ".join(summary_parts) if summary_parts else "No changes"

            html_content += f"<h3 onclick='toggleSection(this)'>{site} ({summary_text})</h3>"
            html_content += "<div class='collapsible-content'>"

            # New Items
            new_items = [change for change in site_changes if change["type"] == "new"]
            if new_items:
                html_content += f"""
                <h4>New Items</h4>
                <table id="historical-new-{site.lower()}">
                    <thead>
                        <tr>
                            <th onclick="sortTable('historical-new-{site.lower()}', 0)">Part</th>
                            <th onclick="sortTable('historical-new-{site.lower()}', 1)">Product Name</th>
                            <th onclick="sortTable('historical-new-{site.lower()}', 2, true)">New Price ($)</th>
                            <th onclick="sortTable('historical-new-{site.lower()}', 3)">Date Added</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in new_items:
                    item = change["item"]
                    html_content += f"""
                        <tr class="new">
                            <td>{item['part']}</td>
                            <td><a href="{item['url']}" target="_blank">{item['name']}</a></td>
                            <td>{item['price_new']}</td>
                            <td>{current_date}</td>
                        </tr>
                    """
                html_content += "</tbody></table>"

            # Price Changes
            price_changes = [change for change in site_changes if change["type"] == "price_change"]
            if price_changes:
                html_content += f"""
                <h4>Price Changes</h4>
                <table id="historical-price-{site.lower()}">
                    <thead>
                        <tr>
                            <th onclick="sortTable('historical-price-{site.lower()}', 0)">Part</th>
                            <th onclick="sortTable('historical-price-{site.lower()}', 1)">Product Name</th>
                            <th onclick="sortTable('historical-price-{site.lower()}', 2, true)">Old Price ($)</th>
                            <th onclick="sortTable('historical-price-{site.lower()}', 3, true)">New Price ($)</th>
                            <th onclick="sortTable('historical-price-{site.lower()}', 4)">Date Changed</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in price_changes:
                    part = site.split("_")[1]
                    html_content += f"""
                        <tr class="price-change">
                            <td>{part}</td>
                            <td><a href="{change['url']}" target="_blank">{change['name']}</a></td>
                            <td>{change['old']}</td>
                            <td>{change['new']}</td>
                            <td>{current_date}</td>
                        </tr>
                    """
                html_content += "</tbody></table>"

            # Removed Items
            removed_items = [change for change in site_changes if change["type"] == "removed"]
            if removed_items:
                html_content += f"""
                <h4>Removed Items</h4>
                <table id="historical-removed-{site.lower()}">
                    <thead>
                        <tr>
                            <th onclick="sortTable('historical-removed-{site.lower()}', 0)">Part</th>
                            <th onclick="sortTable('historical-removed-{site.lower()}', 1)">Product Name</th>
                            <th onclick="sortTable('historical-removed-{site.lower()}', 2, true)">Last Known Price ($)</th>
                            <th onclick="sortTable('historical-removed-{site.lower()}', 3)">Date Removed</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                for change in removed_items:
                    item = change["item"]
                    html_content += f"""
                        <tr class="removed">
                            <td>{item['part']}</td>
                            <td>{item['name']}</td>
                            <td>{item['price_new']}</td>
                            <td>{current_date}</td>
                        </tr>
                    """
                html_content += "</tbody></table>"

            html_content += "</div>"

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
        SkateWarehouseScraper("SkateWarehouse", "https://www.skatewarehouse.com/Clearance_Skateboard_Parts/catpage-BOXLSHOES.html", "Bearings"),
        ZumiezDecksScraper(),
        SkateWarehouseScraper("SkateWarehouse", "https://www.skatewarehouse.com/Clearance_Skateboard_Decks/catpage-SALEDECK.html", "Decks"),
        CCSScraper("CCS", "https://shop.ccs.com/collections/clearance/skateboard-deck", "Decks"),
        TacticsDecksScraper(),
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