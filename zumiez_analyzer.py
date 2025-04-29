import os
import re
import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.firefox import GeckoDriverManager

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("zumiez_scraper")

def analyze_zumiez_html():
    """
    Analyzes the saved Zumiez HTML to identify the correct selectors for products
    """
    html_file = "page_source_zumiez.html"
    
    if not os.path.exists(html_file):
        logger.error(f"HTML file {html_file} not found. Run the full scraper first.")
        return
        
    logger.info(f"Analyzing saved HTML file: {html_file}")
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find all div elements with class containing 'product'
    logger.info("Looking for divs with class containing 'product'")
    product_divs = soup.find_all('div', class_=lambda c: c and 'product' in c.lower())
    logger.info(f"Found {len(product_divs)} divs with 'product' in class name")
    
    # Find all div elements with class containing 'item'
    logger.info("Looking for divs with class containing 'item'")
    item_divs = soup.find_all('div', class_=lambda c: c and 'item' in c.lower())
    logger.info(f"Found {len(item_divs)} divs with 'item' in class name")
    
    # Find all product links
    logger.info("Looking for product links")
    product_links = soup.find_all('a', href=lambda h: h and '/wheels/' in h)
    logger.info(f"Found {len(product_links)} links containing '/wheels/'")
    
    # Find price elements
    logger.info("Looking for price elements")
    price_elements = soup.find_all(text=re.compile(r'\$\d+\.\d{2}'))
    logger.info(f"Found {len(price_elements)} price elements")
    
    # Check if the page has products at all
    wheel_mention = soup.find_all(text=re.compile(r'wheel', re.IGNORECASE))
    logger.info(f"Found {len(wheel_mention)} mentions of 'wheel'")
    
    # Look for possible product grid containers
    logger.info("Looking for product grid containers")
    grid_containers = soup.find_all(['div', 'ul'], class_=lambda c: c and ('grid' in c.lower() or 'list' in c.lower()))
    logger.info(f"Found {len(grid_containers)} possible grid containers")
    
    # Check if there's any mention of "no products found" or similar
    no_results = soup.find_all(text=re.compile(r'no (items|products|results)', re.IGNORECASE))
    if no_results:
        logger.info("Found 'no results' messages:")
        for msg in no_results:
            logger.info(f"  - {msg.strip()}")
    
    # Check if we need to look for different URL structure
    logger.info("Looking for potential alternate URLs for wheels")
    wheel_links = soup.find_all('a', href=lambda h: h and 'wheel' in h.lower())
    logger.info(f"Found {len(wheel_links)} links containing 'wheel'")
    for link in wheel_links[:5]:  # Show first 5 only
        logger.info(f"  - {link.get('href')}")
    
    # Look for JSON data
    logger.info("Looking for embedded JSON data")
    scripts = soup.find_all('script', type='application/json')
    logger.info(f"Found {len(scripts)} JSON script tags")
    
    # Find structured data
    structured_data = soup.find_all('script', type='application/ld+json')
    logger.info(f"Found {len(structured_data)} structured data script tags")
    
    # Check for new API endpoints
    api_scripts = soup.find_all('script', text=re.compile(r'api'))
    logger.info(f"Found {len(api_scripts)} scripts mentioning 'api'")
    
    # Save a summary of findings
    with open("zumiez_html_analysis.txt", "w") as f:
        f.write("ZUMIEZ HTML ANALYSIS\n")
        f.write("===================\n\n")
        f.write(f"Product divs: {len(product_divs)}\n")
        f.write(f"Item divs: {len(item_divs)}\n")
        f.write(f"Product links: {len(product_links)}\n")
        f.write(f"Price elements: {len(price_elements)}\n")
        f.write(f"Wheel mentions: {len(wheel_mention)}\n")
        f.write(f"Grid containers: {len(grid_containers)}\n")
        f.write(f"JSON scripts: {len(scripts)}\n")
        f.write(f"Structured data: {len(structured_data)}\n")
        f.write("\nSAMPLE ELEMENTS:\n")
        
        # Sample of product divs
        if product_divs:
            f.write("\nSample product div classes:\n")
            for div in product_divs[:5]:
                f.write(f"  - {div.get('class')}\n")
        
        # Sample of links
        if product_links:
            f.write("\nSample product links:\n")
            for link in product_links[:5]:
                f.write(f"  - {link.get('href')}\n")
        
        # Sample of prices
        if price_elements:
            f.write("\nSample price elements:\n")
            for price in price_elements[:5]:
                f.write(f"  - {price.strip()}\n")
    
    logger.info("Analysis complete. Check zumiez_html_analysis.txt for details")

def try_direct_api():
    """
    Attempts to directly query Zumiez API endpoints to get product data
    """
    logger.info("Trying direct API approach")
    
    # Try multiple API endpoints that might exist
    api_urls = [
        "https://www.zumiez.com/graphql",
        "https://www.zumiez.com/rest/V1/products?searchCriteria[filter_groups][0][filters][0][field]=category_id&searchCriteria[filter_groups][0][filters][0][value]=wheels&searchCriteria[filter_groups][1][filters][0][field]=special_price&searchCriteria[filter_groups][1][filters][0][condition_type]=notnull",
        "https://www.zumiez.com/skate/components/wheels.json?sale=1"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json"
    }
    
    for url in api_urls:
        try:
            logger.info(f"Trying API URL: {url}")
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                # Try to parse as JSON
                try:
                    data = response.json()
                    logger.info(f"Successfully got JSON response from {url}")
                    
                    # Save the response for analysis
                    with open(f"zumiez_api_{api_urls.index(url)}.json", "w") as f:
                        json.dump(data, f, indent=2)
                    
                    # Basic content check
                    if "items" in data or "products" in data:
                        logger.info("Found product data in API response")
                    else:
                        logger.info("No obvious product data in API response")
                    
                except json.JSONDecodeError:
                    logger.info(f"Response from {url} is not valid JSON")
            else:
                logger.info(f"Request to {url} failed with status code {response.status_code}")
        
        except Exception as e:
            logger.error(f"Error trying API URL {url}: {e}")

def try_new_selector_approach():
    """
    Try more aggressive scraping with the saved HTML
    """
    html_file = "page_source_zumiez.html"
    
    if not os.path.exists(html_file):
        logger.error(f"HTML file {html_file} not found. Run the full scraper first.")
        return []
    
    logger.info(f"Trying new selector approach on saved HTML: {html_file}")
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'html.parser')
    products = []
    
    # Look for any links that might be products
    all_links = soup.find_all('a', href=True)
    logger.info(f"Found {len(all_links)} total links")
    
    wheel_links = [a for a in all_links if '/wheels/' in a['href'] or 'wheel' in a['href'].lower()]
    logger.info(f"Found {len(wheel_links)} links containing 'wheel'")
    
    for link in wheel_links:
        try:
            # Extract as much information as possible
            href = link['href']
            if href.startswith('/'):
                href = f"https://www.zumiez.com{href}"
            
            # Look for name in various attributes
            name = None
            if link.get('title'):
                name = link['title']
            elif link.get('alt'):
                name = link['alt']
            elif link.get_text(strip=True):
                name = link.get_text(strip=True)
            
            # Look for price near this link
            price = None
            parent = link.parent
            for _ in range(3):  # Look a few levels up
                if parent:
                    price_text = parent.find(text=re.compile(r'\$\d+\.\d{2}'))
                    if price_text:
                        price = price_text.strip()
                        break
                    parent = parent.parent
            
            if name and href:
                # If we have a name and URL, it's likely a product
                logger.info(f"Found possible product: {name}, {price}, {href}")
                products.append({
                    'name': name,
                    'url': href,
                    'price_new': price,
                    'price_old': None
                })
        except Exception as e:
            logger.warning(f"Error processing link: {e}")
    
    logger.info(f"Found {len(products)} potential products")
    
    # Save the results
    with open("zumiez_new_selector_results.json", "w") as f:
        json.dump(products, f, indent=2)
    
    return products

def try_direct_zumiez_search():
    """
    Try a direct search on Zumiez site
    """
    logger.info("Trying direct search on Zumiez")
    
    options = Options()
    options.headless = True
    service = Service(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    
    try:
        # Go to Zumiez homepage
        driver.get("https://www.zumiez.com")
        time.sleep(3)
        
        # Use the search bar
        search_input = driver.find_element(By.ID, "search")
        search_input.send_keys("skateboard wheels sale")
        search_input.submit()
        
        time.sleep(5)
        
        # Save the results page
        with open("zumiez_search_results.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        
        logger.info("Saved search results page")
        
        # Take a screenshot
        driver.save_screenshot("zumiez_search_results.png")
        
        # Analyze the results
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Look for product cards or items
        product_elements = soup.select(".product-item, .product-card, .product, [data-product-id]")
        logger.info(f"Found {len(product_elements)} product elements in search results")
        
        # Extract information about these products
        products = []
        for prod in product_elements:
            try:
                # Try to find product information
                name_el = prod.select_one("h3, .product-name, .name")
                price_el = prod.select_one(".price, .current-price")
                link_el = prod.select_one("a[href]")
                
                if name_el and link_el:
                    name = name_el.get_text(strip=True)
                    href = link_el.get("href")
                    price = price_el.get_text(strip=True) if price_el else None
                    
                    if href.startswith("/"):
                        href = f"https://www.zumiez.com{href}"
                    
                    products.append({
                        "name": name,
                        "url": href,
                        "price_new": price,
                        "price_old": None
                    })
            except Exception as e:
                logger.warning(f"Error extracting product info: {e}")
                
        logger.info(f"Extracted {len(products)} products from search results")
        
        # Save the results
        with open("zumiez_search_products.json", "w") as f:
            json.dump(products, f, indent=2)
        
    except Exception as e:
        logger.error(f"Error during direct search: {e}")
    finally:
        driver.quit()

def try_all_approaches():
    """
    Try all approaches to get Zumiez data
    """
    logger.info("Starting comprehensive Zumiez analysis")
    
    # First analyze the saved HTML
    analyze_zumiez_html()
    
    # Try the API approach
    try_direct_api()
    
    # Try new selector approach
    products_from_selectors = try_new_selector_approach()
    
    # Try direct search
    try_direct_zumiez_search()
    
    logger.info("All approaches completed")
    
    return products_from_selectors

if __name__ == "__main__":
    products = try_all_approaches()
    print(f"Found {len(products)} potential products")