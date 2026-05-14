import streamlit as st
import requests
import csv
import re
import time
import io
import json
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(page_title="Merchant Center Tool", page_icon="🛍️", layout="wide")
st.title("🛍️ Merchant Center Tool")

# ============================================================
# STORE CREDENTIALS
# ============================================================
STORES = {
    "Voggaci": {
        "STORE_URL": "https://voggaci.com",
        "CK": "ck_6a71cbd882f15cf58755dadec4657ad8c51481da",
        "CS": "cs_e188acce5cb4a8ff31b2d50929fd8a93ecee7aed",
    },
    "The Movie Attire": {
        "STORE_URL": "https://themovieattire.com",
        "CK": "ck_55bf303c4013201868885ae52f671a5cd804b6c6",
        "CS": "cs_6b9419eed0793f0e5bbafde5f4b252eda112f931",
    },
    "Nyoshopping": {
        "STORE_URL": "https://nyoshopping.com",
        "CK": "ck_2e8843d4709d3b7717f9ce512d535a8fa6aae467",
        "CS": "cs_559384bfd5fbbfdd17167590f1fa786e41f35cf8",
    },
    "Jacket Cult": {
        "STORE_URL": "https://jacketcult.shop",
        "CK": "ck_9226b1b1c260e12500d7249a2a9e2d3bc14e6d16",
        "CS": "cs_69410665a3da1caa4994a0ba24151c4d9c207e46",
    }
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
# WOOCOMMERCE API FUNCTIONS
# ============================================================
def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=20)
    return resp.json() if resp.status_code == 200 else None

def get_all_products(store):
    """Saare products ek page per 100 karke fetch karo"""
    all_products = []
    page = 1
    while True:
        products = wc_get(store, "products", {"per_page": 100, "page": page, "status": "publish"})
        if not products:
            break
        all_products.extend(products)
        if len(products) < 100:
            break
        page += 1
        time.sleep(0.5)
    return all_products

def get_product_by_sku(store, sku):
    products = wc_get(store, "products", {"sku": sku})
    if products and len(products) > 0:
        return products[0]
    return None

def get_variations(store, product_id):
    variations = wc_get(store, f"products/{product_id}/variations", {"per_page": 100})
    return variations or []

def clean_description(html_text):
    """HTML tags hata do aur clean text lo"""
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_attribute(product, attr_name):
    """Product attributes se value lo"""
    for attr in product.get('attributes', []):
        if attr_name.lower() in attr.get('name', '').lower():
            options = attr.get('options', [])
            return options[0] if options else ""
    return ""

def detect_gender(product):
    """Product name/categories se gender detect karo"""
    name = product.get('name', '').lower()
    categories = [c.get('name', '').lower() for c in product.get('categories', [])]
    tags = [t.get('name', '').lower() for t in product.get('tags', [])]
    all_text = name + ' '.join(categories) + ' '.join(tags)

    if 'women' in all_text or 'female' in all_text or 'girl' in all_text or "ladies" in all_text:
        return "Female"
    elif 'men' in all_text or 'male' in all_text or 'boy' in all_text:
        return "Male"
    return "Unisex"

def build_primary(product, store_name):
    """Primary feed row banao"""
    images = product.get('images', [])
    image_link = images[0]['src'] if images else ""
    additional_images = ",".join([img['src'] for img in images[1:]]) + "," if len(images) > 1 else ""

    price = product.get('price', '') or product.get('regular_price', '')
    price_str = f"{price} USD" if price else ""

    return {
        "id": str(product.get('id', '')),
        "title": product.get('name', ''),
        "description": clean_description(product.get('description', '') or product.get('short_description', '')),
        "link": product.get('permalink', ''),
        "image_link": image_link,
        "additional image link": additional_images,
        "condition": "New",
        "price": price_str,
        "availability": "in_stock" if product.get('stock_status') == 'instock' else "out_of_stock",
        "mpn": product.get('sku', ''),
        "brand": store_name,
        "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "material": get_attribute(product, 'material'),
        "product_type": " > ".join([c.get('name', '') for c in product.get('categories', [])]),
        "identifier_exists": "No",
        "color": get_attribute(product, 'color'),
        "gender": detect_gender(product)
    }

def build_supplemental_rows(product, store_name, variations):
    """Supplemental feed rows banao - har size ke liye alag row"""
    rows = []
    color = get_attribute(product, 'color')
    gender = detect_gender(product)
    product_id = str(product.get('id', ''))
    title = product.get('name', '')

    sizes = []
    # Variations se sizes lo
    for var in variations:
        for attr in var.get('attributes', []):
            if 'size' in attr.get('name', '').lower():
                val = attr.get('option', '').upper()
                if val and val not in sizes:
                    sizes.append(val)

    # Agar variations nahi hain toh product attributes se
    if not sizes:
        size_attr = get_attribute(product, 'size')
        if size_attr:
            sizes = [size_attr.upper()]

    for size in (sizes if sizes else [""]):
        rows.append({
            "id": product_id,
            "title": title,
            "color": color,
            "gender": gender,
            "age_group": "Adult",
            "brand": store_name,
            "size": size,
            "included_destination": "Free listings, Shopping ads, Dynamic remarketing",
            "excluded_destination": "",
            "shipping_label": "Free Shipping",
            "return_policy_label": "30 Days Returns"
        })
    return rows

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

db_fieldnames = ["sku", "product_id", "url", "store", "title"]

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3 = st.tabs(["🚀 SKU se Scrape Karo", "🗄️ Product Database", "📦 Sab Products Fetch Karo"])

# ============================================================
# TAB 1 - SKU se Scrape
# ============================================================
with tab1:
    st.subheader("SKU se Products Fetch Karo")
    st.info("SKU daalo → WooCommerce API se seedha data aayega — koi Cloudflare issue nahi! ✅")

    col_a, col_b = st.columns(2)
    with col_a:
        store_choice_t1 = st.selectbox("Store select karo:", list(STORES.keys()), key="t1_store")
    with col_b:
        st.write("")

    sku_input = st.text_area("SKUs daalo (har SKU alag line mein):", height=150,
                              placeholder="JC-1234\nJC-5678")

    if st.button("🚀 Fetch Karo", use_container_width=True, key="sku_fetch"):
        skus = [s.strip() for s in sku_input.strip().split("\n") if s.strip()]
        if not skus:
            st.warning("Pehle SKU daalo!")
        else:
            store = STORES[store_choice_t1]
            all_primary, all_supplemental = [], []
            progress = st.progress(0)

            for i, sku in enumerate(skus, 1):
                st.write(f"[{i}/{len(skus)}] SKU: {sku}")
                product = get_product_by_sku(store, sku)
                if product:
                    variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                    primary = build_primary(product, store_choice_t1)
                    supplemental = build_supplemental_rows(product, store_choice_t1, variations)
                    all_primary.append(primary)
                    all_supplemental.extend(supplemental)
                    st.write(f"✅ {product.get('name')} — {len(supplemental)} sizes")
                else:
                    st.write(f"❌ SKU nahi mila: {sku}")
                progress.progress(i / len(skus))
                time.sleep(0.5)

            if all_primary:
                with st.spinner("Google Sheet update ho rahi hai..."):
                    try:
                        spreadsheet = get_spreadsheet()
                        primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                        supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
                        append_to_sheet(primary_sheet, primary_fieldnames, all_primary)
                        time.sleep(2)
                        append_to_sheet(supplemental_sheet, supplemental_fieldnames, all_supplemental)
                        st.success("✅ Google Sheet update ho gayi!")
                    except Exception as e:
                        st.error(f"Sheet error: {e}")

                out1 = io.StringIO()
                csv.DictWriter(out1, fieldnames=primary_fieldnames).writeheader()
                [csv.DictWriter(out1, fieldnames=primary_fieldnames).writerow(d) for d in all_primary]

                out2 = io.StringIO()
                csv.DictWriter(out2, fieldnames=supplemental_fieldnames).writeheader()
                [csv.DictWriter(out2, fieldnames=supplemental_fieldnames).writerow(d) for d in all_supplemental]

                st.success(f"🎉 {len(all_primary)} products done!")
                c1, c2 = st.columns(2)
                with c1:
                    st.download_button("📥 Primary Feed CSV", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
                with c2:
                    st.download_button("📥 Supplemental Feed CSV", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

# ============================================================
# TAB 2 - Product Database
# ============================================================
with tab2:
    st.subheader("🗄️ Product Database — Sab Products Save Karo")
    st.info("Yeh tab store ke sab products scan karega aur SKU + URL + Title database mein save karega.")

    store_choice_t2 = st.selectbox("Store select karo:", ["Sab Stores"] + list(STORES.keys()), key="t2_store")

    col1, col2 = st.columns(2)
    with col1:
        scan_db_btn = st.button("🔍 Database Scan & Save Karo", use_container_width=True)
    with col2:
        check_new_btn = st.button("🆕 Naye Products Check Karo", use_container_width=True)

    if scan_db_btn:
        stores_to_scan = list(STORES.keys()) if store_choice_t2 == "Sab Stores" else [store_choice_t2]
        try:
            spreadsheet = get_spreadsheet()
            db_sheet = get_or_create_tab(spreadsheet, "URL Database")
            existing_data = db_sheet.get_all_values()
            existing_skus = set()
            if len(existing_data) > 1:
                sku_idx = existing_data[0].index('sku') if 'sku' in existing_data[0] else 0
                existing_skus = {row[sku_idx] for row in existing_data[1:] if len(row) > sku_idx}

            new_rows = []
            for store_name in stores_to_scan:
                store = STORES[store_name]
                st.write(f"🔍 {store_name} scan ho raha hai...")
                with st.spinner(f"{store_name} products fetch ho rahe hain..."):
                    products = get_all_products(store)
                added = 0
                for p in products:
                    sku = p.get('sku', '')
                    if sku and sku not in existing_skus:
                        new_rows.append([
                            sku,
                            str(p.get('id', '')),
                            p.get('permalink', ''),
                            store_name,
                            p.get('name', '')
                        ])
                        existing_skus.add(sku)
                        added += 1
                st.write(f"   → {len(products)} total, {added} naye")

            if new_rows:
                if not existing_data:
                    db_sheet.update([db_fieldnames] + new_rows, value_input_option='RAW')
                else:
                    db_sheet.append_rows(new_rows, value_input_option='RAW')
                st.success(f"✅ {len(new_rows)} naye products database mein save ho gaye!")
            else:
                st.success("✅ Koi naya product nahi — database updated hai!")
            st.markdown(f"📊 **[Database dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
        except Exception as e:
            st.error(f"Error: {e}")

    if check_new_btn:
        stores_to_scan = list(STORES.keys()) if store_choice_t2 == "Sab Stores" else [store_choice_t2]
        try:
            spreadsheet = get_spreadsheet()
            db_sheet = get_or_create_tab(spreadsheet, "URL Database")
            existing_data = db_sheet.get_all_values()
            existing_skus = set()
            if len(existing_data) > 1:
                sku_idx = existing_data[0].index('sku') if 'sku' in existing_data[0] else 0
                existing_skus = {row[sku_idx] for row in existing_data[1:] if len(row) > sku_idx}

            new_products = []
            for store_name in stores_to_scan:
                store = STORES[store_name]
                with st.spinner(f"{store_name} check ho raha hai..."):
                    products = get_all_products(store)
                for p in products:
                    sku = p.get('sku', '')
                    if sku and sku not in existing_skus:
                        new_products.append({
                            "store": store_name,
                            "sku": sku,
                            "title": p.get('name', ''),
                            "url": p.get('permalink', ''),
                            "id": str(p.get('id', ''))
                        })

            if new_products:
                st.warning(f"🆕 {len(new_products)} naye products mile!")
                for p in new_products:
                    st.write(f"• **{p['store']}** | SKU: `{p['sku']}` | {p['title']}")
                if st.button("✅ Inhe Database mein Add Karo"):
                    rows = [[p['sku'], p['id'], p['url'], p['store'], p['title']] for p in new_products]
                    db_sheet = get_or_create_tab(get_spreadsheet(), "URL Database")
                    db_sheet.append_rows(rows, value_input_option='RAW')
                    st.success("✅ Sab naye products add ho gaye!")
            else:
                st.success("✅ Koi naya product nahi — sab up to date hai!")
        except Exception as e:
            st.error(f"Error: {e}")

# ============================================================
# TAB 3 - Sab Products Feed mein Daalo
# ============================================================
with tab3:
    st.subheader("📦 Sab Products Fetch Karo aur Feed Banao")
    st.info("Ek store ke sab products ek baar mein Primary + Supplemental feed mein aa jayenge.")

    store_choice_t3 = st.selectbox("Store select karo:", list(STORES.keys()), key="t3_store")

    col1, col2 = st.columns(2)
    with col1:
        fetch_all_btn = st.button("📦 Sab Products Fetch Karo", use_container_width=True)
    with col2:
        st.write("")
        replace_or_append = st.radio("Mode:", ["Neeche Append Karo", "Sheet Clear Karke New Banao"], horizontal=True)

    if fetch_all_btn:
        store = STORES[store_choice_t3]
        with st.spinner(f"{store_choice_t3} ke sab products aa rahe hain..."):
            products = get_all_products(store)

        if not products:
            st.error("Koi product nahi mila ya API error!")
        else:
            st.info(f"{len(products)} products mile — feed ban rahi hai...")
            all_primary, all_supplemental = [], []
            progress = st.progress(0)

            for i, product in enumerate(products, 1):
                variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                primary = build_primary(product, store_choice_t3)
                supplemental = build_supplemental_rows(product, store_choice_t3, variations)
                all_primary.append(primary)
                all_supplemental.extend(supplemental)
                progress.progress(i / len(products))
                if i % 10 == 0:
                    time.sleep(0.5)

            with st.spinner("Google Sheet update ho rahi hai..."):
                try:
                    spreadsheet = get_spreadsheet()
                    primary_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    supplemental_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")

                    if replace_or_append == "Sheet Clear Karke New Banao":
                        primary_sheet.clear()
                        supplemental_sheet.clear()
                        time.sleep(1)

                    append_to_sheet(primary_sheet, primary_fieldnames, all_primary)
                    time.sleep(2)
                    append_to_sheet(supplemental_sheet, supplemental_fieldnames, all_supplemental)
                    st.success("✅ Google Sheet update ho gayi!")
                except Exception as e:
                    st.error(f"Sheet error: {e}")

            out1 = io.StringIO()
            w1 = csv.DictWriter(out1, fieldnames=primary_fieldnames)
            w1.writeheader()
            w1.writerows(all_primary)

            out2 = io.StringIO()
            w2 = csv.DictWriter(out2, fieldnames=supplemental_fieldnames)
            w2.writeheader()
            w2.writerows(all_supplemental)

            st.success(f"🎉 {len(all_primary)} products, {len(all_supplemental)} supplemental rows!")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Primary Feed CSV", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
            with c2:
                st.download_button("📥 Supplemental Feed CSV", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
            st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
