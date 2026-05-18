import streamlit as st
from curl_cffi import requests  # Cloudflare bypass
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
st.set_page_config(page_title="Merchant Center Tool", page_icon="🛍️", layout="wide")
st.title("🛍️ Merchant Center Tool")

# ============================================================
# WEBSITES & SITEMAPS
# ============================================================
WEBSITES = {
    "JacketCult":     ["https://jacketcult.shop/product-sitemap.xml", "https://jacketcult.shop/product-sitemap2.xml"],
    "TheMovieAttire": ["http://themovieattire.com/product-sitemap.xml"],
    "Urbanixity":     ["http://urbanixity.com/product-sitemap.xml"]
}

# ============================================================
# GOOGLE SHEETS
# ============================================================
SHEET_ID = "1acOTN47TNWGBh6HEIJX9pYNMY31ZDRyQ--iFeIdxzgo"

def get_spreadsheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def get_or_create_tab(spreadsheet, title):
    try:
        return spreadsheet.worksheet(title)
    except:
        return spreadsheet.add_worksheet(title=title, rows="2000", cols="25")

def append_to_sheet(sheet, fieldnames, data_list):
    existing = sheet.get_all_values()
    if not existing:
        rows = [fieldnames] + [[d.get(f, "") for f in fieldnames] for d in data_list]
        sheet.update(rows, value_input_option='RAW')
    else:
        rows = [[d.get(f, "") for f in fieldnames] for d in data_list]
        sheet.append_rows(rows, value_input_option='RAW')

# ============================================================
# curl_cffi REQUEST - Chrome impersonate karta hai
# ============================================================
def cf_get(url, timeout=20):
    """curl_cffi se request karo - Chrome fingerprint use karta hai"""
    try:
        resp = requests.get(
            url,
            impersonate="chrome120",  # Chrome 120 ki exact TLS fingerprint
            timeout=timeout
        )
        return resp
    except Exception as e:
        return None

# ============================================================
# SITEMAP SCANNER
# ============================================================
def get_urls_from_sitemap(sitemap_url):
    urls = []
    seen = set()
    try:
        resp = cf_get(sitemap_url)
        if not resp:
            return urls
        root = ET.fromstring(resp.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        for url in root.findall('ns:url', ns):
            loc = url.find('ns:loc', ns)
            if loc is not None and '/product/' in loc.text:
                u = loc.text.strip()
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
    except Exception as e:
        st.warning(f"Sitemap error: {sitemap_url} — {e}")
    return urls

def scan_all_sitemaps(website_name):
    all_urls = []
    seen = set()
    for sitemap in WEBSITES.get(website_name, []):
        for url in get_urls_from_sitemap(sitemap):
            if url not in seen:
                seen.add(url)
                all_urls.append(url)
    return all_urls

# ============================================================
# SCRAPING FUNCTION
# ============================================================
def scrape_product_details(url):
    try:
        resp = cf_get(url)
        if not resp:
            return None, []

        soup = BeautifulSoup(resp.content, 'html.parser')

        # Cloudflare check
        page_text = soup.get_text().lower()
        if "checking your browser" in page_text or "just a moment" in page_text:
            return None, []

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
            target = amount if amount else price_tag
            price_text = re.sub(r'[^\d.]', '', target.get_text(strip=True))
            price = f"{price_text} USD" if price_text else ""

        # SKU
        sku = ""
        sku_tag = soup.find('span', class_='sku')
        if sku_tag:
            sku = sku_tag.get_text(strip=True)

        # BRAND from URL
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

        # COLOR - short description se
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
        size_select = (
            soup.find('select', {'name': 'attribute_pa_size'}) or
            soup.find('select', {'name': 'attribute_size'}) or
            soup.find('select', attrs={'name': re.compile(r'attribute.*size', re.I)})
        )
        if size_select:
            for option in size_select.find_all('option'):
                val = option.get('value', '').strip()
                if val:
                    sizes.append(val.upper())
        if not sizes:
            for btn in soup.select('.variable-items-wrapper .wvs-style-button, .swatch-option, li[data-value]'):
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
primary_fieldnames = [
    "id", "title", "description", "link", "image_link", "additional image link",
    "condition", "price", "availability", "mpn", "brand",
    "google_product_category", "material", "product_type",
    "identifier_exists", "color", "gender"
]
supplemental_fieldnames = [
    "id", "title", "color", "gender", "age_group", "brand", "size",
    "included_destination", "excluded_destination",
    "shipping_label", "return_policy_label"
]
db_fieldnames = ["sku", "url", "website", "title"]

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3 = st.tabs(["🔗 URL se Scrape Karo", "🗄️ URL Database", "🔍 SKU se Search"])

# ============================================================
# TAB 1 - URL Scraping
# ============================================================
with tab1:
    st.subheader("Product URLs paste karo")
    st.info("Naye products neeche append honge — purana data safe rahega ✅")

    urls_input = st.text_area("Har URL alag line mein:", height=200,
                               placeholder="https://jacketcult.shop/product/example-jacket/")

    if st.button("🚀 Scraping Shuru Karo", use_container_width=True, key="scrape_btn"):
        urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
        if not urls:
            st.warning("Pehle kuch URLs daalo!")
        else:
            st.info(f"Total **{len(urls)}** products scrape honge...")
            with st.spinner("Google Sheet se connect ho raha hai..."):
                try:
                    spreadsheet = get_spreadsheet()
                    primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
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

            if all_primary and sheet_connected:
                status.text("Sheet update ho rahi hai...")
                try:
                    append_to_sheet(primary_sheet, primary_fieldnames, all_primary)
                    time.sleep(2)
                    append_to_sheet(supplemental_sheet, supplemental_fieldnames, all_supplemental)
                    st.success("✅ Google Sheet update ho gayi!")
                except Exception as e:
                    st.error(f"Sheet error: {e}")

            if all_primary:
                out1 = io.StringIO()
                w1 = csv.DictWriter(out1, fieldnames=primary_fieldnames)
                w1.writeheader(); w1.writerows(all_primary)

                out2 = io.StringIO()
                w2 = csv.DictWriter(out2, fieldnames=supplemental_fieldnames)
                w2.writeheader(); w2.writerows(all_supplemental)

                st.success(f"🎉 {len(all_primary)} products done!")
                c1, c2 = st.columns(2)
                with c1:
                    st.download_button("📥 Primary Feed CSV", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
                with c2:
                    st.download_button("📥 Supplemental Feed CSV", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

# ============================================================
# TAB 2 - URL DATABASE
# ============================================================
with tab2:
    st.subheader("🗄️ URL Database — Sitemap se URLs Save Karo")
    st.info("Naye URLs neeche append honge — purane safe rahenge ✅")

    website_choice = st.selectbox("Website:", ["Sab Websites"] + list(WEBSITES.keys()))

    c1, c2 = st.columns(2)
    with c1:
        scan_btn = st.button("🔍 Sitemap Scan Karo & Save", use_container_width=True)
    with c2:
        check_btn = st.button("🆕 Naye Products Check Karo", use_container_width=True)

    if scan_btn:
        with st.spinner("Sitemaps scan ho rahi hain..."):
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")
                existing_data = db_sheet.get_all_values()
                existing_urls = set()
                if len(existing_data) > 1 and 'url' in existing_data[0]:
                    idx = existing_data[0].index('url')
                    existing_urls = {row[idx] for row in existing_data[1:] if len(row) > idx}

                sites = list(WEBSITES.keys()) if website_choice == "Sab Websites" else [website_choice]
                new_rows = []
                for site in sites:
                    st.write(f"🔍 **{site}** scan ho raha hai...")
                    urls = scan_all_sitemaps(site)
                    added = 0
                    for url in urls:
                        if url not in existing_urls:
                            new_rows.append([" ", url, site, ""])
                            existing_urls.add(url)
                            added += 1
                    st.write(f"   → {len(urls)} total, **{added} naye**")

                if new_rows:
                    if not existing_data:
                        db_sheet.update([db_fieldnames] + new_rows, value_input_option='RAW')
                    else:
                        db_sheet.append_rows(new_rows, value_input_option='RAW')
                    st.success(f"✅ {len(new_rows)} naye URLs save ho gaye!")
                else:
                    st.success("✅ Database already updated hai!")
                st.markdown(f"📊 **[Database dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
            except Exception as e:
                st.error(f"Error: {e}")

    if check_btn:
        with st.spinner("Check ho raha hai..."):
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")
                existing_data = db_sheet.get_all_values()
                existing_urls = set()
                if len(existing_data) > 1 and 'url' in existing_data[0]:
                    idx = existing_data[0].index('url')
                    existing_urls = {row[idx] for row in existing_data[1:] if len(row) > idx}

                sites = list(WEBSITES.keys()) if website_choice == "Sab Websites" else [website_choice]
                new_urls = []
                for site in sites:
                    for url in scan_all_sitemaps(site):
                        if url not in existing_urls:
                            new_urls.append({"url": url, "website": site})

                if new_urls:
                    st.warning(f"🆕 **{len(new_urls)} naye products** mile!")
                    for item in new_urls:
                        st.write(f"• **{item['website']}**: {item['url']}")
                    if st.button("✅ Inhe Add Karo"):
                        rows = [[" ", item['url'], item['website'], ""] for item in new_urls]
                        db_sheet.append_rows(rows, value_input_option='RAW')
                        st.success("✅ Add ho gaye!")
                else:
                    st.success("✅ Koi naya product nahi!")
            except Exception as e:
                st.error(f"Error: {e}")

# ============================================================
# TAB 3 - SKU se Search
# ============================================================
with tab3:
    st.subheader("🔍 SKU se Product Dhundo aur Scrape Karo")
    st.info("SKU daalo → database se URL milega → feed mein add hoga ✅")

    sku_input = st.text_area("SKUs daalo (har SKU alag line mein):", height=150,
                              placeholder="JC-1234\nJC-5678")

    if st.button("🔍 SKU se Scrape Karo", use_container_width=True):
        skus = [s.strip() for s in sku_input.strip().split("\n") if s.strip()]
        if not skus:
            st.warning("Pehle SKU daalo!")
        else:
            try:
                spreadsheet = get_spreadsheet()
                db_sheet = get_or_create_tab(spreadsheet, "URL Database")
                all_db = db_sheet.get_all_records()

                sku_url_map = {}
                for sku in skus:
                    for row in all_db:
                        if str(row.get('sku', '')).strip() == sku:
                            sku_url_map[sku] = row['url']
                            break

                not_found = [s for s in skus if s not in sku_url_map]
                if not_found:
                    st.warning(f"Yeh SKUs nahi mile: `{', '.join(not_found)}`")
                    st.info("Pehle Tab 2 se sitemap scan karo aur SKU column fill karo.")

                if sku_url_map:
                    primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
                    all_primary, all_supplemental = [], []
                    progress = st.progress(0)
                    total = len(sku_url_map)

                    for i, (sku, url) in enumerate(sku_url_map.items(), 1):
                        st.write(f"**[{i}/{total}]** SKU: `{sku}` → {url}")
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
                        append_to_sheet(primary_sheet, primary_fieldnames, all_primary)
                        time.sleep(2)
                        append_to_sheet(supplemental_sheet, supplemental_fieldnames, all_supplemental)

                        out1 = io.StringIO()
                        w1 = csv.DictWriter(out1, fieldnames=primary_fieldnames)
                        w1.writeheader(); w1.writerows(all_primary)

                        out2 = io.StringIO()
                        w2 = csv.DictWriter(out2, fieldnames=supplemental_fieldnames)
                        w2.writeheader(); w2.writerows(all_supplemental)

                        st.success(f"🎉 {len(all_primary)} products done!")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.download_button("📥 Primary Feed", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
                        with c2:
                            st.download_button("📥 Supplemental Feed", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
                        st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

            except Exception as e:
                st.error(f"Error: {e}")
