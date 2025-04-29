import os
import re
import json
import time
import requests
import logging
from urllib.parse import urlparse, urlencode
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper_debug.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("skate_scraper")

def fetch_page(url):
    """
    Uses headless Firefox (via Selenium) to render JavaScript and return page HTML,
    dismissing common overlays (cookie banners, popups), and clicking 'load more' on Zumiez.
    """
    logger.info(f"Fetching page: {url}")
    options = Options()
    options.set_preference("permissions.default.geo", 2)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("permissions.default.desktop-notification", 2)
    options.headless = True
    
    try:
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
        driver.get(url)
        
        logger.info("Waiting for page to load completely...")
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        
        # Take screenshot for debugging
        driver.save_screenshot(f"page_screenshot_{urlparse(url).netloc.split('.')[1]}.png")
        
        # dismiss cookie banner
        try:
            logger.info("Attempting to dismiss cookie banners...")
            for selector in [
                "//button[contains(text(),'Accept')]", 
                "//button[contains(text(),'OK')]",
                "//button[contains(@class,'cookie')]",
                "//div[contains(@class,'cookie')]//button"
            ]:
                try:
                    btns = driver.find_elements(By.XPATH, selector)
                    if btns:
                        btns[0].click()
                        logger.info(f"Clicked cookie button with selector: {selector}")
                        time.sleep(1)
                        break
                except Exception as e:
                    logger.debug(f"Cookie button not found with selector {selector}: {e}")
        except Exception as e:
            logger.warning(f"Error dismissing cookie banner: {e}")
        
        # Zumiez: click all 'load more'
        if 'zumiez.com' in url:
            logger.info("On Zumiez site, looking for 'load more' buttons...")
            load_more_attempts = 0
            max_attempts = 5
            
            while load_more_attempts < max_attempts:
                try:
                    selectors = [
                        'button.load-more-button', 
                        'button.load-more', 
                        '.load-more-btn',
                        '.button--load-more',
                        '.button--see-more'
                    ]
                    
                    found_button = False
                    for selector in selectors:
                        try:
                            load_btns = driver.find_elements(By.CSS_SELECTOR, selector)
                            if load_btns:
                                logger.info(f"Found load more button with selector: {selector}")
                                driver.execute_script("arguments[0].scrollIntoView();", load_btns[0])
                                time.sleep(0.5)
                                load_btns[0].click()
                                logger.info("Clicked load more button")
                                time.sleep(3)  # Give more time for content to load
                                found_button = True
                                break
                        except Exception as e:
                            logger.debug(f"No load more button with selector {selector}: {e}")
                    
                    if not found_button:
                        logger.info("No more 'load more' buttons found")
                        break
                        
                    load_more_attempts += 1
                    
                except Exception as e:
                    logger.warning(f"Error clicking load more: {e}")
                    break
                    
            if load_more_attempts >= max_attempts:
                logger.info(f"Reached maximum load more attempts ({max_attempts})")
        
        # Save page source for debugging
        with open(f"page_source_{urlparse(url).netloc.split('.')[1]}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
            
        logger.info("Page fully loaded, returning HTML")
        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        logger.error(f"Error fetching page {url}: {e}", exc_info=True)
        try:
            if 'driver' in locals() and driver:
                driver.quit()
        except:
            pass
        raise

class Scraper:
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.logger = logging.getLogger(f"skate_scraper.{name}")

    def scrape(self):
        self.logger.info(f"Starting scrape for {self.name}")
        try:
            html = fetch_page(self.url)
            results = self.parse(html)
            self.logger.info(f"Scraped {len(results)} products from {self.name}")
            return results
        except Exception as e:
            self.logger.error(f"Error scraping {self.name}: {e}", exc_info=True)
            return []

    def parse(self, html):
        raise NotImplementedError

class ZumiezScraper(Scraper):
    def __init__(self):
        super().__init__(
            'Zumiez',
            'https://www.zumiez.com/skate/components/wheels.html?sale=1'
        )

    def parse(self, html):
        self.logger.info(f"Parsing Zumiez HTML. Length: {len(html)}")
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        
        # Try to find product items with updated selectors
        all_selectors = [
            '.product-item', 
            '.product-grid-item', 
            '.item.product',
            '[data-role="priceBox"]',
            '.product-tile'
        ]
        
        for selector in all_selectors:
            product_items = soup.select(selector)
            self.logger.info(f"Selector '{selector}' found {len(product_items)} items")
            
            if product_items:
                for prod in product_items:
                    try:
                        # Look for multiple possible selectors for each element
                        name_el = (
                            prod.select_one('.product-item-link') or
                            prod.select_one('.product-name') or
                            prod.select_one('.name') or
                            prod.select_one('h2.product-name') or
                            prod.select_one('a[title]')  # Sometimes title is in the link
                        )
                        
                        price_el = (
                            prod.select_one('.special-price .price') or
                            prod.select_one('.price-box .price') or
                            prod.select_one('.price-wrapper .price') or
                            prod.select_one('.price .current') or
                            prod.select_one('.price')
                        )
                        
                        old_price_el = (
                            prod.select_one('.old-price .price') or
                            prod.select_one('.price-box .old-price') or
                            prod.select_one('.price .original')
                        )
                        
                        link_el = (
                            prod.select_one('a.product-item-link') or
                            prod.select_one('a.product-image') or
                            prod.select_one('a.thumb') or
                            prod.select_one('a[href]')  # Any link if nothing else matches
                        )
                        
                        # Get info from elements
                        name = None
                        if name_el:
                            name = name_el.get_text(strip=True)
                        elif link_el and link_el.get('title'):
                            name = link_el.get('title')
                            
                        href = None
                        if link_el:
                            href = link_el.get('href')
                            if href and href.startswith('/'):
                                href = 'https://www.zumiez.com' + href
                        
                        price_new = None
                        if price_el:
                            price_new = price_el.get_text(strip=True)
                            
                        price_old = None
                        if old_price_el:
                            price_old = old_price_el.get_text(strip=True)
                        
                        if name and href and price_new:
                            self.logger.debug(f"Found product: {name}, {price_new}")
                            products.append({
                                'name': name,
                                'url': href,
                                'price_new': price_new,
                                'price_old': price_old
                            })
                    except Exception as e:
                        self.logger.warning(f"Error parsing product: {e}")
                
                # If we found products with this selector, stop trying others
                if products:
                    break
        
        # If no products found, try different approaches
        if not products:
            self.logger.info("HTML parsing found no products, trying JSON extraction")
            try:
                # Find JSON data that might be embedded in scripts
                json_patterns = [
                    r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                    r'window\.adobeDataLayer\s*=\s*(\[.*?\]);',
                    r'"items"\s*:\s*(\[.*?\])'
                ]
                
                for pattern in json_patterns:
                    json_matches = re.findall(pattern, html, re.DOTALL)
                    if json_matches:
                        try:
                            data = json.loads(json_matches[0])
                            self.logger.info(f"Found JSON data with pattern {pattern}")
                            
                            # Save JSON for debugging
                            with open(f"json_data_zumiez_{json_patterns.index(pattern)}.json", "w") as f:
                                json.dump(data, f, indent=2)
                                
                            # Try to extract product info from JSON
                            # This depends on the actual structure of the JSON
                            # We'd need to inspect the saved JSON file to update this
                        except json.JSONDecodeError:
                            self.logger.warning(f"Failed to parse JSON with pattern {pattern}")
                
            except Exception as e:
                self.logger.error(f"Error parsing JSON data: {e}", exc_info=True)
        
        return products

class SkateWarehouseScraper(Scraper):
    def __init__(self):
        super().__init__(
            'SkateWarehouse',
            'https://www.skatewarehouse.com/Clearance_Skateboard_Wheels/catpage-SALEWHEELS.html'
        )

    def parse(self, html):
        self.logger.info(f"Parsing SkateWarehouse HTML. Length: {len(html)}")
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        
        try:
            # Try to find product links with updated selectors
            product_links = soup.find_all('a', href=re.compile(r'/descpage-'))
            self.logger.info(f"Found {len(product_links)} product links")
            
            for a in product_links:
                try:
                    text = a.get_text(separator=' ', strip=True)
                    if 'Wheels' not in text:
                        continue
                        
                    href = a['href']
                    if not href.startswith('http'):
                        href = 'https://www.skatewarehouse.com' + href
                        
                    # Find prices in text
                    prices = re.findall(r'\$(\d+\.\d{2})', text)
                    if prices:
                        # Extract name - try to remove clearance text and price
                        name = re.sub(r'^(Clearance|Sale)\s*-?\d+%\s*', '', text.split(f'${prices[0]}')[0].strip())
                        
                        self.logger.debug(f"Found product: {name}, ${prices[0]}")
                        products.append({
                            'name': name, 
                            'url': href, 
                            'price_new': f"${prices[0]}", 
                            'price_old': f"${prices[1]}" if len(prices) > 1 else None
                        })
                except Exception as e:
                    self.logger.warning(f"Error parsing SkateWarehouse product: {e}")
        
        except Exception as e:
            self.logger.error(f"Error parsing SkateWarehouse HTML: {e}", exc_info=True)
            
        return products

class CCSScraper(Scraper):
    def __init__(self):
        super().__init__(
            'CCS',
            'https://shop.ccs.com/collections/clearance/skateboard-wheels'
        )

    def parse(self, html):
        self.logger.info(f"Parsing CCS HTML. Length: {len(html)}")
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        
        try:
            # Try multiple possible selectors
            product_selectors = [
                '.product-item',
                '.product-card',
                '.product'
            ]
            
            for selector in product_selectors:
                product_items = soup.select(selector)
                self.logger.info(f"Selector '{selector}' found {len(product_items)} items")
                
                if product_items:
                    for prod in product_items:
                        try:
                            # Look for product elements with multiple possible selectors
                            title_el = (
                                prod.select_one('.product-title') or
                                prod.select_one('.product-name') or
                                prod.select_one('h3') or
                                prod.select_one('.title')
                            )
                            
                            sale_el = (
                                prod.select_one('.product-price--sale') or
                                prod.select_one('.product-price') or
                                prod.select_one('.sale-price') or
                                prod.select_one('.price')
                            )
                            
                            comp_el = (
                                prod.select_one('.product-price--compare') or
                                prod.select_one('.compare-price') or
                                prod.select_one('.original-price')
                            )
                            
                            link_el = prod.select_one('a')
                            
                            if title_el and sale_el and link_el:
                                name = title_el.get_text(strip=True)
                                price_new = sale_el.get_text(strip=True) 
                                price_old = comp_el.get_text(strip=True) if comp_el else None
                                href = link_el['href']
                                
                                # Make sure URL is absolute
                                if href.startswith('/'):
                                    href = 'https://shop.ccs.com' + href
                                    
                                self.logger.debug(f"Found product: {name}, {price_new}")
                                products.append({
                                    'name': name,
                                    'url': href,
                                    'price_new': price_new,
                                    'price_old': price_old
                                })
                        except Exception as e:
                            self.logger.warning(f"Error parsing CCS product: {e}")
                    
                    # If we found products with this selector, stop trying others
                    if products:
                        break
                        
        except Exception as e:
            self.logger.error(f"Error parsing CCS HTML: {e}", exc_info=True)
            
        return products

# Utility functions
def load_previous(path='previous_data.json'):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading previous data: {e}")
        return {}

def save_current(data, path='previous_data.json'):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved current data to {path}")
    except Exception as e:
        logger.error(f"Error saving current data: {e}")

def compare(prev, curr):
    changes = {}
    for site, items in curr.items():
        pm = {i['url']: i for i in prev.get(site, [])}
        diffs = []
        for it in items:
            pi = pm.get(it['url'])
            if not pi:
                diffs.append({'type': 'new', 'item': it})
            elif it['price_new'] != pi.get('price_new'):
                diffs.append({'type': 'price_change', 'url': it['url'], 'old': pi.get('price_new'), 'new': it['price_new']})
        cu = {i['url'] for i in items}
        for u, pi in pm.items():
            if u not in cu:
                diffs.append({'type': 'removed', 'item': pi})
        if diffs:
            changes[site] = diffs
    return changes

def main():
    logger.info("Starting skateboard wheel sales scraper")
    
    # Define scrapers
    scrapers = [ZumiezScraper(), SkateWarehouseScraper(), CCSScraper()]
    
    # Run each scraper individually for better debugging
    current = {}
    for scraper in scrapers:
        logger.info(f"Running {scraper.name} scraper")
        try:
            items = scraper.scrape()
            current[scraper.name] = items
            logger.info(f"{scraper.name}: {len(items)} items scraped")
            
            # Save individual results for debugging
            with open(f"{scraper.name.lower()}_results.json", "w") as f:
                json.dump(items, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error running {scraper.name} scraper: {e}", exc_info=True)
            current[scraper.name] = []
    
    prev = load_previous()
    diffs = compare(prev, current)
    if diffs:
        logger.info("Changes detected:")
        for site, changes in diffs.items():
            logger.info(f"\n{site}:")
            for c in changes:
                if c['type'] == 'new':
                    logger.info(f"  New: {c['item']['name']} at {c['item']['price_new']}")
                elif c['type'] == 'price_change':
                    logger.info(f"  Price change: {c['old']} -> {c['new']} | {c['url']}")
                elif c['type'] == 'removed':
                    logger.info(f"  Removed: {c['item']['name']}")
    else:
        logger.info("No changes detected.")
    
    save_current(current)
    logger.info("Scraper completed successfully")

if __name__ == '__main__':
    main()