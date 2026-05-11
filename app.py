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
import xml.etree.ElementTree as ET

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Merchant Center Tool",
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ Merchant Center Tool")

# ============================================================
# WEBSITES & SITEMAPS
# ============================================================
WEBSITES = {
    "JacketCult": [
        "https://jacketcult.shop/product-sitemap.xml",
        "https://jacketcult.shop/product-sitemap2.xml"
    ],
    "TheMovieAttire": [
        "http://themovieattire.com/product-sitemap.xml"
    ],
    "Urbanixity": [
        "http://urbanixity.com/product-sitemap.xml"
    ]
}

# ============================================================
# GOOGLE SHEETS SETUP
# ============================================================
SHEET_ID = "1acOTN47TNWGBh6HEIJX9pYNMY31ZDRyQ--iFeIdxzgo"

def get_spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def get_or_create_tab(spreadsheet, title, rows="2000", cols="20"):
    try:
        return spreadsheet.worksheet(title)
    except:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

# ============================================================
# SITEMAP SCANNER
# ============================================================
def get_urls_from_sitemap(sitemap_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    urls = []
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=15)
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        for url in root.findall('ns:url', ns):
            loc = url.find('ns:loc', ns)
            if loc is not None and '/product/' in loc.text:
                urls.append(loc.text.strip())
    except Exception as e:
        st.warning(f"Sitemap error: {sitemap_url} — {e}")
    return urls

def scan_all_sitemaps(website_name):
    all_urls = []
    sitemaps = WEBSITES.get(website_name, [])
    for sitemap in sitemaps:
        urls = get_urls_from_sitemap(sitemap)
        all_urls.extend(urls)
    return list(set(all_urls))

# ============================================================
# SKU FETCHER
# ============================================================
def get_sku_from_url(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        sku_tag = soup.find('span', class_='sku')
        if sku_tag:
            return sku_tag.get_text(strip=True)
    except:
        pass
    return ""

# ============================================================
# SCRAPING FUNCTION
# ============================================================
def scrape_product_details(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')

        # TITLE
        title = ""
        title_tag = soup.find('h1', class_='product_title') or soup.find('h1')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # PRODUCT ID
        product_id = ""
        id_tag = soup.find('link', {'rel': 'shortlink'})
        if id_tag and 'p=' in id_tag.get('href', ''):
            product_id = id_tag['href'].split('p=')[-1]
        else:
            body = soup.find('body')
            if body:
                for cls in body.get('class', []):
                    if cls.startswith('postid-'):
                        product_id = cls.replace('postid-', '')
                        break

        # PRICE
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

        # SKU
        sku = ""
        sku_tag = soup.find('span', class_='sku')
        if sku_tag:
            sku = sku_tag.get_text(strip=True)

        # BRAND
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        brand = domain.split('.')[0].capitalize()

        # DESCRIPTION
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

        # IMAGES
        img_links = []
        images = soup.select('.woocommerce-product-gallery__image img, .wp-post-image')
        for img in images:
            src = img.get('data-src') or img.get('src')
            if src and src not in img_links:
                img_links.append(src)
        image_link = img_links[0] if img_links else ""
        additional_image_link = ",".join(img_links[1:]) + "," if len(img_links) > 1 else ""

        # COLOR
        color = ""
        short_desc = soup.find('div', class_='woocommerce-product-details__short-description')
        if short_desc:
            short_text = short_desc.get_text(separator=" ", strip=True)
            color_match = re.search(r"Color:\s*(.+?)(?:\s{2,}|\||\n|$)", short_text)
            if color_match:
                color = color_match.group(1).strip()

        # MATERIAL & GENDER
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

        # SIZES
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
            "id": product_id, "title": title, "description": description, "link": url,
            "image_link": image_link, "additional image link": additional_image_link,
            "condition": "New", "price": price, "availability": "in_stock",
            "mpn": sku, "brand": brand,
            "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
            "material": material, "product_type": "", "identifier_exists": "No",
            "color": color, "gender": gender
        }

        supplemental_rows = []
        for size in (sizes if sizes else [""]):
            supplemental_rows.append({
                "id": product_id, "title": title, "color": color, "gender": gender,
                "age_group": "Adult", "brand": brand, "size": size,
                "included_destination": "Free listings, Shopping ads, Dynamic remarketing",
                "excluded_destination": "", "shipping_label": "Free Shipping",
                "return_policy_label": "30 Days Returns"
            })

        return primary_data, supplemental_rows

    except Exception as e:
        return None, []


# ============================================================
# FIELDNAMES
# ============================================================
primary_fieldnames = ["id", "title", "description", "link", "image_link", "additional image link",
                      "condition", "price", "availability", "mpn", "brand",
                      "google_product_category", "material", "product_type",
                      "identifier_exists", "color", "gender"]

supplemental_fieldnames = ["id", "title", "color", "gender", "age_group", "brand", "size",
                           "included_destination", "excluded_destination",
                           "shipping_label", "return_policy_label"]

db_fieldnames = ["sku", "url", "website", "title"]


# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3 = st.tabs(["🔗 URL se Scrape Karo", "🗄️ URL Database", "🔍 SKU se Search"])


# ============================================================
# TAB 1 - Manual URL Scraping
# ============================================================
with tab1:
    st.subheader("Product URLs paste karo")
    urls_input = st.text_area(
        "Har URL alag line mein:",
        height=200,
        placeholder="https://jacketcult.shop/product/example-jacket/"
    )

    if st.button("🚀 Scraping Shuru Karo", use_container_width=True, key="scrape_btn"):
        urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
        if not urls:
            st.warning("Pehle kuch URLs daalo!")
        else:
            st.info(f"Total {len(urls)} products scrape honge...")
            with st.spinner("Google Sheet se connect ho raha hai..."):
                try:
                    spreadsheet = get_spreadsheet()
                    primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
                    primary_sheet.clear()
                    supplemental_sheet.clear()
                    sheet_connected = True
                    st.success("✅ Google Sheet connected!")
                except Exception as e:
                    st.error(f"Sheet error: {e}")
                    sheet_connected = False

            all_primary, all_supplemental = [], []
            progress = st.progress(0)
            status = st.empty()

            for i, url in enumerate(urls, 1):
                status.text(f"[{i}/{len(urls)}] Scraping...")
                primary_data, supplemental_rows = scrape_product_details(url)
                if primary_data:
                    all_primary.append(primary_data)
                    all_supplemental.extend(supplemental_rows)
                    st.write(f"✅ {i}. {url}")
                else:
                    st.write(f"❌ {i}. Error: {url}")
                progress.progress(i / len(urls))
                time.sleep(2)

            status.text("Sheet update ho rahi hai...")

            if all_primary and sheet_connected:
                try:
                    p_rows = [primary_fieldnames] + [[d[f] for f in primary_fieldnames] for d in all_primary]
                    primary_sheet.update(p_rows, value_input_option='RAW')
                    time.sleep(2)
                    s_rows = [supplemental_fieldnames] + [[d[f] for f in supplemental_fieldnames] for d in all_supplemental]
                    supplemental_sheet.update(s_rows, value_input_option='RAW')
                    st.success("✅ Google Sheet update ho gayi!")
                except Exception as e:
                    st.error(f"Sheet update error: {e}")

            if all_primary:
                out1 = io.StringIO()
                csv.DictWriter(out1, fieldnames=primary_fieldnames).writeheader()
                csv.DictWriter(out1, fieldnames=primary_fieldnames).writerows(all_primary)

                out2 = io.StringIO()
                csv.DictWriter(out2, fieldnames=supplemental_fieldnames).writeheader()
                csv.DictWriter(out2, fieldnames=supplemental_fieldnames).writerows(all_supplemental)

                st.success(f"🎉 {len(all_primary)} products done!")
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button("📥 Primary Feed CSV", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
                with col2:
                    st.download_button("📥 Supplemental Feed CSV", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")


# ============================================================
# TAB 2 - URL DATABASE (Sitemap Scanner)
# ============================================================
with tab2:
    st.subheader("🗄️ URL Database — Sitemap se URLs Save Karo")
    st.info("Yeh tool teeno websites ke sitemaps scan karega aur sab product URLs + SKU database mein save karega.")

    website_choice = st.selectbox("Website select karo:", ["Sab Websites"] + list(WEBSITES.keys()))

    col1, col2 = st.columns(2)
    with col1:
        scan_btn = st.button("🔍 Sitemap Scan Karo & Save", use_container_width=True)
    with col2:
        check_new_btn = st.button("🆕 Naye Products Check Karo", use_container_width=True)

    if scan_btn:
        with st.spinner("Sitemaps scan ho rahi hain..."):
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")

                # Existing URLs load karo
                existing_data = db_sheet.get_all_records()
                existing_urls = {row['url'] for row in existing_data}

                # Scan karo
                websites_to_scan = list(WEBSITES.keys()) if website_choice == "Sab Websites" else [website_choice]
                new_rows = []

                for website in websites_to_scan:
                    st.write(f"🔍 Scanning {website}...")
                    urls = scan_all_sitemaps(website)
                    st.write(f"   → {len(urls)} URLs mili")

                    for url in urls:
                        if url not in existing_urls:
                            new_rows.append({
                                "sku": "",
                                "url": url,
                                "website": website,
                                "title": ""
                            })
                            existing_urls.add(url)

                if new_rows:
                    # Agar sheet empty hai toh header bhi add karo
                    if not existing_data:
                        all_rows = [db_fieldnames] + [[r[f] for f in db_fieldnames] for r in new_rows]
                        db_sheet.update(all_rows, value_input_option='RAW')
                    else:
                        for row in new_rows:
                            db_sheet.append_row([row[f] for f in db_fieldnames])
                            time.sleep(0.5)

                    st.success(f"✅ {len(new_rows)} naye URLs database mein save ho gaye!")
                else:
                    st.success("✅ Koi naya URL nahi mila — database already updated hai!")

                st.markdown(f"📊 **[URL Database dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

            except Exception as e:
                st.error(f"Error: {e}")

    if check_new_btn:
        with st.spinner("Naye products check ho rahe hain..."):
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")
                existing_data = db_sheet.get_all_records()
                existing_urls = {row['url'] for row in existing_data}

                websites_to_scan = list(WEBSITES.keys()) if website_choice == "Sab Websites" else [website_choice]
                new_urls = []

                for website in websites_to_scan:
                    urls = scan_all_sitemaps(website)
                    for url in urls:
                        if url not in existing_urls:
                            new_urls.append({"url": url, "website": website})

                if new_urls:
                    st.warning(f"🆕 {len(new_urls)} naye products mile!")
                    for item in new_urls:
                        st.write(f"• {item['website']}: {item['url']}")

                    if st.button("Inhe Database mein Add Karo"):
                        for item in new_urls:
                            db_sheet.append_row(["", item['url'], item['website'], ""])
                            time.sleep(0.5)
                        st.success("✅ Sab naye URLs add ho gaye!")
                else:
                    st.success("✅ Koi naya product nahi hai!")

            except Exception as e:
                st.error(f"Error: {e}")


# ============================================================
# TAB 3 - SKU SE SEARCH
# ============================================================
with tab3:
    st.subheader("🔍 SKU se Product Dhundo aur Scrape Karo")
    st.info("SKU daalo — tool database mein se URL dhundega aur feed mein add karega.")

    sku_input = st.text_area(
        "SKUs daalo (har SKU alag line mein):",
        height=150,
        placeholder="JC-1234\nJC-5678"
    )

    if st.button("🔍 SKU se Scrape Karo", use_container_width=True):
        skus = [s.strip() for s in sku_input.strip().split("\n") if s.strip()]
        if not skus:
            st.warning("Pehle SKU daalo!")
        else:
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")
                all_db = db_sheet.get_all_records()

                # SKU se URL match karo
                sku_url_map = {}
                for row in all_db:
                    if row.get('sku') in skus:
                        sku_url_map[row['sku']] = row['url']

                # Agar SKU database mein nahi mila toh bata do
                not_found = [s for s in skus if s not in sku_url_map]
                if not_found:
                    st.warning(f"Yeh SKUs database mein nahi mile: {', '.join(not_found)}")
                    st.info("Pehle Tab 2 se sitemap scan karo aur SKU column fill karo Google Sheet mein.")

                if sku_url_map:
                    st.info(f"{len(sku_url_map)} products mile, scraping shuru...")
                    primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")

                    all_primary, all_supplemental = [], []
                    progress = st.progress(0)
                    total = len(sku_url_map)

                    for i, (sku, url) in enumerate(sku_url_map.items(), 1):
                        st.write(f"[{i}/{total}] SKU: {sku} → {url}")
                        primary_data, supplemental_rows = scrape_product_details(url)
                        if primary_data:
                            all_primary.append(primary_data)
                            all_supplemental.extend(supplemental_rows)
                            st.write(f"✅ Done")
                        else:
                            st.write(f"❌ Error")
                        progress.progress(i / total)
                        time.sleep(2)

                    if all_primary:
                        p_rows = [primary_fieldnames] + [[d[f] for f in primary_fieldnames] for d in all_primary]
                        primary_sheet.update(p_rows, value_input_option='RAW')
                        time.sleep(2)
                        s_rows = [supplemental_fieldnames] + [[d[f] for f in supplemental_fieldnames] for d in all_supplemental]
                        supplemental_sheet.update(s_rows, value_input_option='RAW')

                        out1 = io.StringIO()
                        w1 = csv.DictWriter(out1, fieldnames=primary_fieldnames)
                        w1.writeheader()
                        w1.writerows(all_primary)

                        out2 = io.StringIO()
                        w2 = csv.DictWriter(out2, fieldnames=supplemental_fieldnames)
                        w2.writeheader()
                        w2.writerows(all_supplemental)

                        st.success(f"🎉 {len(all_primary)} products scrape ho gaye!")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button("📥 Primary Feed", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
                        with col2:
                            st.download_button("📥 Supplemental Feed", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)

            except Exception as e:
                st.error(f"Error: {e}")
