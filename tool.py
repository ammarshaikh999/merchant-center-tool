import requests
from bs4 import BeautifulSoup
import csv
from datetime import datetime
import re
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# GOOGLE SHEETS SETUP
# ============================================================
CREDENTIALS_FILE = "utopian-pride-492309-e8-ba676512abd5.json"
SHEET_ID = "1acOTN47TNWGBh6HEIJX9pYNMY31ZDRyQ--iFeIdxzgo"

def get_google_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet


def scrape_product_details(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')

        # 1. DESCRIPTION - h2 se lekar saara text ek line mein
        desc_panel = soup.find('div', id='tab-description') or soup.find('div', class_='description')
        description = ""
        if desc_panel:
            paragraphs = []
            for tag in desc_panel.find_all(['h2', 'h3', 'h4', 'p', 'li']):
                text = tag.get_text(strip=True)
                if not text:
                    continue
                if re.match(r'^(Material|Color|Gender|Size|Weight|Dimensions?|Product Spec)', text, re.IGNORECASE):
                    continue
                if "Product Specifications" in text:
                    continue
                paragraphs.append(text)
            description = " ".join(paragraphs).strip()

        # 2. IMAGES
        img_links = []
        images = soup.select('.woocommerce-product-gallery__image img, .wp-post-image')
        for img in images:
            src = img.get('data-src') or img.get('src')
            if src and src not in img_links:
                img_links.append(src)
        
        image_link = img_links[0] if img_links else ""
        additional_image_link = ",".join(img_links[1:]) + "," if len(img_links) > 1 else ""

        # 3. SPECIFICATIONS LOGIC (Material, Color, Gender)

        # Color - sirf woocommerce short description se uthao
        color = ""
        short_desc = soup.find('div', class_='woocommerce-product-details__short-description')
        if short_desc:
            short_text = short_desc.get_text(separator=" ", strip=True)
            color_match = re.search(r"Color:\s*(.+?)(?:\s{2,}|\||\n|$)", short_text)
            if color_match:
                color = color_match.group(1).strip()

        # Baaki specs ke liye full page text
        all_text = soup.get_text(separator=" ", strip=True)

        # Material Extraction
        material_match = re.search(r"Material:\s*(.*?)(?=\s*[A-Z][a-z]+:|$)", all_text)
        material = material_match.group(1).strip() if material_match else ""

        # Gender Logic
        gender = ""
        if "Size and Gender" in all_text:
            gender = "Unisex"
        elif "Men Size" in all_text:
            gender = "Male"
        elif "Women Size" in all_text:
            gender = "Female"
        else:
            gender = "Unisex"

        return {
            "id": "", "title": "", "description": description, "link": url,
            "image_link": image_link, "additional image link": additional_image_link,
            "condition": "", "price": "", "availability": "", "mpn": "", "brand": "",
            "google_product_category": "", "material": material, "product_type": "",
            "identifier_exists": "", "color": color, "gender": gender
        }

    except Exception as e:
        print(f"Error: {e}")
        return None


def start_automation():
    print("--- Merchant Center Tool (Google Sheets Version) ---")
    print("Paste URLs (Type 'DONE' then Enter):")
    
    urls = []
    while True:
        line = input()
        if line.strip().upper() == 'DONE': break
        if line.strip(): urls.append(line.strip())

    if not urls: return

    fieldnames = ["id", "title", "description", "link", "image_link", "additional image link",
                  "condition", "price", "availability", "mpn", "brand",
                  "google_product_category", "material", "product_type",
                  "identifier_exists", "color", "gender"]

    # ── CSV ──
    filename = f"merchant_feed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    csv_file = open(filename, 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    # ── Google Sheet ──
    print("\nGoogle Sheet se connect ho raha hai...")
    sheet = get_google_sheet()
    sheet.clear()
    sheet.append_row(fieldnames)
    print("Connected! Data likhna shuru...")

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] Scraping Product...")
        data = scrape_product_details(url)
        if data:
            writer.writerow(data)
            row = [data[f] for f in fieldnames]
            sheet.append_row(row)

    csv_file.close()
    print(f"\nDone! CSV '{filename}' aur Google Sheet dono update ho gayi! 🚀")


if __name__ == "__main__":
    start_automation()