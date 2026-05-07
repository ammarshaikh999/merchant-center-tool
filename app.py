import streamlit as st
import requests
from bs4 import BeautifulSoup
import csv
import re
import time
import io
import json
import gspread
from urllib.parse import urlparse
from google.oauth2.service_account import Credentials

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Merchant Center Tool",
    page_icon="🛍️",
    layout="centered"
)

st.title("🛍️ Merchant Center Tool")
st.markdown("Product URLs paste karo aur Google Sheet + CSV dono automatically ban jayegi!")

# ============================================================
# GOOGLE SHEETS SETUP
# ============================================================
SHEET_ID = "1acOTN47TNWGBh6HEIJX9pYNMY31ZDRyQ--iFeIdxzgo"

def get_google_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet


# ============================================================
# SCRAPING FUNCTION
# ============================================================
def scrape_product_details(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')

        # 1. TITLE - h1 se
        title = ""
        title_tag = soup.find('h1', class_='product_title') or soup.find('h1')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # 2. PRODUCT ID - URL se ya page se
        product_id = ""
        id_tag = soup.find('link', {'rel': 'shortlink'})
        if id_tag and 'p=' in id_tag.get('href', ''):
            product_id = id_tag['href'].split('p=')[-1]
        else:
            # post ID from body class
            body = soup.find('body')
            if body:
                classes = body.get('class', [])
                for cls in classes:
                    if cls.startswith('postid-'):
                        product_id = cls.replace('postid-', '')
                        break

        # 3. PRICE
        price = ""
        price_tag = soup.find('p', class_='price') or soup.find('span', class_='woocommerce-Price-amount')
        if price_tag:
            amount = price_tag.find('span', class_='woocommerce-Price-amount')
            if amount:
                price_text = amount.get_text(strip=True)
                price_text = re.sub(r'[^\d.]', '', price_text)
                price = f"{price_text} USD"
            else:
                price_text = price_tag.get_text(strip=True)
                price_text = re.sub(r'[^\d.]', '', price_text)
                price = f"{price_text} USD"

        # 4. SKU
        sku = ""
        sku_tag = soup.find('span', class_='sku')
        if sku_tag:
            sku = sku_tag.get_text(strip=True)

        # 5. BRAND - URL se website naam
        brand = ""
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        brand = domain.split('.')[0].capitalize()

        # 6. DESCRIPTION
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

        # 7. IMAGES
        img_links = []
        images = soup.select('.woocommerce-product-gallery__image img, .wp-post-image')
        for img in images:
            src = img.get('data-src') or img.get('src')
            if src and src not in img_links:
                img_links.append(src)
        
        image_link = img_links[0] if img_links else ""
        additional_image_link = ",".join(img_links[1:]) + "," if len(img_links) > 1 else ""

        # 8. COLOR
        color = ""
        short_desc = soup.find('div', class_='woocommerce-product-details__short-description')
        if short_desc:
            short_text = short_desc.get_text(separator=" ", strip=True)
            color_match = re.search(r"Color:\s*(.+?)(?:\s{2,}|\||\n|$)", short_text)
            if color_match:
                color = color_match.group(1).strip()

        # 9. MATERIAL & GENDER
        all_text = soup.get_text(separator=" ", strip=True)

        material_match = re.search(r"Material:\s*(.*?)(?=\s*[A-Z][a-z]+:|$)", all_text)
        material = material_match.group(1).strip() if material_match else ""

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
            "id": product_id,
            "title": title,
            "description": description,
            "link": url,
            "image_link": image_link,
            "additional image link": additional_image_link,
            "condition": "New",
            "price": price,
            "availability": "in_stock",
            "mpn": sku,
            "brand": brand,
            "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
            "material": material,
            "product_type": "",
            "identifier_exists": "No",
            "color": color,
            "gender": gender
        }

    except Exception as e:
        return None


# ============================================================
# UI
# ============================================================
urls_input = st.text_area(
    "Product URLs yahan paste karo (har URL alag line mein):",
    height=200,
    placeholder="https://example.com/product-1\nhttps://example.com/product-2"
)

fieldnames = ["id", "title", "description", "link", "image_link", "additional image link",
              "condition", "price", "availability", "mpn", "brand",
              "google_product_category", "material", "product_type",
              "identifier_exists", "color", "gender"]

if st.button("🚀 Scraping Shuru Karo", use_container_width=True):
    urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
    
    if not urls:
        st.warning("Pehle kuch URLs daalo!")
    else:
        st.info(f"Total {len(urls)} products scrape honge...")

        # Google Sheet connect
        with st.spinner("Google Sheet se connect ho raha hai..."):
            try:
                sheet = get_google_sheet()
                sheet.clear()
                sheet.append_row(fieldnames)
                sheet_connected = True
                st.success("✅ Google Sheet connected!")
            except Exception as e:
                st.error(f"Google Sheet error: {e}")
                sheet_connected = False

        # Scraping
        all_data = []
        progress = st.progress(0)
        status = st.empty()

        for i, url in enumerate(urls, 1):
            status.text(f"[{i}/{len(urls)}] Scraping: {url}")
            data = scrape_product_details(url)
            
            if data:
                all_data.append(data)
                if sheet_connected:
                    row = [data[f] for f in fieldnames]
                    sheet.append_row(row)
                st.write(f"✅ {i}. {url}")
            else:
                st.write(f"❌ {i}. Error: {url}")
            
            progress.progress(i / len(urls))
            time.sleep(2)

        status.text("Done!")

        # CSV download
        if all_data:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_data)
            csv_data = output.getvalue()

            st.success(f"🎉 {len(all_data)}/{len(urls)} products successfully scrape ho gaye!")
            
            st.download_button(
                label="📥 CSV Download Karo",
                data=csv_data,
                file_name="merchant_feed.csv",
                mime="text/csv",
                use_container_width=True
            )

            if sheet_connected:
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
