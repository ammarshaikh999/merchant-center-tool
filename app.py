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

def get_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)

    # Primary Feed tab
    try:
        primary_sheet = spreadsheet.worksheet("Primary Feed")
    except:
        primary_sheet = spreadsheet.add_worksheet(title="Primary Feed", rows="1000", cols="30")

    # Supplemental Feed tab
    try:
        supplemental_sheet = spreadsheet.worksheet("Supplemental Feed")
    except:
        supplemental_sheet = spreadsheet.add_worksheet(title="Supplemental Feed", rows="1000", cols="20")

    return primary_sheet, supplemental_sheet


# ============================================================
# SCRAPING FUNCTION
# ============================================================
def scrape_product_details(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')

        # 1. TITLE
        title = ""
        title_tag = soup.find('h1', class_='product_title') or soup.find('h1')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # 2. PRODUCT ID
        product_id = ""
        id_tag = soup.find('link', {'rel': 'shortlink'})
        if id_tag and 'p=' in id_tag.get('href', ''):
            product_id = id_tag['href'].split('p=')[-1]
        else:
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
                price_text = re.sub(r'[^\d.]', '', amount.get_text(strip=True))
                price = f"{price_text} USD"
            else:
                price_text = re.sub(r'[^\d.]', '', price_tag.get_text(strip=True))
                price = f"{price_text} USD"

        # 4. SKU
        sku = ""
        sku_tag = soup.find('span', class_='sku')
        if sku_tag:
            sku = sku_tag.get_text(strip=True)

        # 5. BRAND
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

        # 10. SIZES
        sizes = []
        size_select = soup.find('select', {'name': 'attribute_pa_size'}) or \
                      soup.find('select', {'name': 'attribute_size'}) or \
                      soup.find('select', attrs={'name': re.compile(r'attribute.*size', re.I)})
        if size_select:
            for option in size_select.find_all('option'):
                val = option.get('value', '').strip()
                if val:
                    sizes.append(val.upper())

        if not sizes:
            size_buttons = soup.select('.variable-items-wrapper .wvs-style-button, .swatch-option, li[data-value]')
            for btn in size_buttons:
                val = btn.get('data-value') or btn.get_text(strip=True)
                if val and val.upper() not in sizes:
                    sizes.append(val.upper())

        primary_data = {
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

        supplemental_rows = []
        size_list = sizes if sizes else [""]
        for size in size_list:
            supplemental_rows.append({
                "id": product_id,
                "title": title,
                "color": color,
                "gender": gender,
                "age_group": "Adult",
                "brand": brand,
                "size": size,
                "included_destination": "Free listings, Shopping ads, Dynamic remarketing",
                "excluded_destination": "",
                "shipping_label": "Free Shipping",
                "return_policy_label": "30 Days Returns"
            })

        return primary_data, supplemental_rows

    except Exception as e:
        return None, []


# ============================================================
# UI
# ============================================================
urls_input = st.text_area(
    "Product URLs yahan paste karo (har URL alag line mein):",
    height=200,
    placeholder="https://example.com/product-1\nhttps://example.com/product-2"
)

primary_fieldnames = ["id", "title", "description", "link", "image_link", "additional image link",
                      "condition", "price", "availability", "mpn", "brand",
                      "google_product_category", "material", "product_type",
                      "identifier_exists", "color", "gender"]

supplemental_fieldnames = ["id", "title", "color", "gender", "age_group", "brand", "size",
                           "included_destination", "excluded_destination",
                           "shipping_label", "return_policy_label"]

if st.button("🚀 Scraping Shuru Karo", use_container_width=True):
    urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
    
    if not urls:
        st.warning("Pehle kuch URLs daalo!")
    else:
        st.info(f"Total {len(urls)} products scrape honge...")

        # Google Sheet connect
        with st.spinner("Google Sheet se connect ho raha hai..."):
            try:
                primary_sheet, supplemental_sheet = get_google_sheets()
                primary_sheet.clear()
                supplemental_sheet.clear()
                sheet_connected = True
                st.success("✅ Google Sheet connected!")
            except Exception as e:
                st.error(f"Google Sheet error: {e}")
                sheet_connected = False

        # Scraping - pehle sab data collect karo
        all_primary = []
        all_supplemental = []
        progress = st.progress(0)
        status = st.empty()

        for i, url in enumerate(urls, 1):
            status.text(f"[{i}/{len(urls)}] Scraping: {url}")
            primary_data, supplemental_rows = scrape_product_details(url)
            
            if primary_data:
                all_primary.append(primary_data)
                all_supplemental.extend(supplemental_rows)
                st.write(f"✅ {i}. {url} — {len(supplemental_rows)} sizes")
            else:
                st.write(f"❌ {i}. Error: {url}")
            
            progress.progress(i / len(urls))
            time.sleep(2)

        status.text("Scraping done! Google Sheet mein upload ho raha hai...")

        # ── BATCH UPDATE - ek baar mein sab bhejo ──
        if all_primary and sheet_connected:
            try:
                # Primary Feed - ek baar mein sab
                primary_rows = [primary_fieldnames]
                for d in all_primary:
                    primary_rows.append([d[f] for f in primary_fieldnames])
                primary_sheet.update(primary_rows, value_input_option='RAW')

                time.sleep(2)  # quota ke liye thodi der

                # Supplemental Feed - ek baar mein sab
                supplemental_rows = [supplemental_fieldnames]
                for d in all_supplemental:
                    supplemental_rows.append([d[f] for f in supplemental_fieldnames])
                supplemental_sheet.update(supplemental_rows, value_input_option='RAW')

                st.success("✅ Google Sheet update ho gayi!")
            except Exception as e:
                st.error(f"Sheet update error: {e}")

        if all_primary:
            # Primary CSV
            output1 = io.StringIO()
            writer1 = csv.DictWriter(output1, fieldnames=primary_fieldnames)
            writer1.writeheader()
            writer1.writerows(all_primary)

            # Supplemental CSV
            output2 = io.StringIO()
            writer2 = csv.DictWriter(output2, fieldnames=supplemental_fieldnames)
            writer2.writeheader()
            writer2.writerows(all_supplemental)

            st.success(f"🎉 {len(all_primary)} products scrape ho gaye!")

            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="📥 Primary Feed CSV",
                    data=output1.getvalue(),
                    file_name="primary_feed.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label="📥 Supplemental Feed CSV",
                    data=output2.getvalue(),
                    file_name="supplemental_feed.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            if sheet_connected:
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
