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
# WOOCOMMERCE API
# ============================================================
def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    try:
        resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        pass
    return None

def get_all_products(store):
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

# ============================================================
# DATA EXTRACTION
# ============================================================
def clean_html(html_text):
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_attribute(product, *keywords):
    attributes = product.get('attributes', [])
    for attr in attributes:
        attr_name = attr.get('name', '').lower().replace('pa_', '')
        for kw in keywords:
            if kw.lower() == attr_name or kw.lower() in attr_name:
                options = attr.get('options', [])
                if options:
                    return options[0].strip()
    return ""

def extract_color_from_text(text):
    if not text:
        return ""
    
    text_lower = text.lower()
    
    # "Color: Black and White" pattern
    color_match = re.search(r'(?:color|colour)[:\s-]*(.+?)(?=\s{2,}|\n|\||$|material|inner|front|collar|pockets|sleeves|size|weight)', 
                           text_lower, re.IGNORECASE)
    if color_match:
        color_value = color_match.group(1).strip()
        color_value = re.split(r'\s{2,}|material|inner|front|collar', color_value)[0].strip()
        return color_value.title()
    
    # Common colors fallback
    common_colors = r'\b(black|white|red|blue|green|yellow|pink|purple|orange|grey|gray|navy|brown|beige|cream|maroon|burgundy|teal|gold|silver|multicolor)\b'
    matches = re.findall(common_colors, text_lower)
    if matches:
        unique_colors = list(dict.fromkeys(matches))
        if len(unique_colors) > 1:
            return " and ".join([c.title() for c in unique_colors])
        return unique_colors[0].title()
    
    return ""

def get_color_improved(product):
    color = get_attribute(product, 'color', 'colour', 'rang')
    if color:
        return color
    
    short_desc = clean_html(product.get('short_description', ''))
    if short_desc:
        color = extract_color_from_text(short_desc)
        if color:
            return color
    
    full_desc = clean_html(product.get('description', ''))
    if full_desc:
        color = extract_color_from_text(full_desc)
        if color:
            return color
    
    title = product.get('name', '')
    if title:
        color = extract_color_from_text(title)
        if color:
            return color
    
    return ""

def get_sizes_from_variations(variations):
    sizes = []
    size_keywords = ['size', 'pa_size', 'taille']
    for var in variations:
        attrs = var.get('attributes', [])
        if not attrs:
            continue
        for attr in attrs:
            attr_name = attr.get('name', '').lower().replace('pa_', '')
            if any(kw in attr_name for kw in size_keywords):
                val = attr.get('option', '').strip()
                if val and val.upper() not in [s.upper() for s in sizes]:
                    sizes.append(val)
    return sizes

def get_sizes_from_attributes(product):
    size_keywords = ['size', 'pa_size']
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower().replace('pa_', '')
        if any(kw == attr_name or kw in attr_name for kw in size_keywords):
            return [o.strip() for o in attr.get('options', []) if o.strip()]
    return []

def detect_gender(product):
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower().replace('pa_', '')
        if 'gender' in attr_name:
            options = attr.get('options', [])
            if options:
                val = options[0].strip().lower()
                if any(x in val for x in ['female', 'women', 'girl']):
                    return "Female"
                elif any(x in val for x in ['male', 'men', 'boy']):
                    return "Male"
                elif 'unisex' in val:
                    return "Unisex"
            if len(options) > 1:
                return "Unisex"
    
    name = product.get('name', '').lower()
    cats = ' '.join([c.get('name', '').lower() for c in product.get('categories', [])])
    tags = ' '.join([t.get('name', '').lower() for t in product.get('tags', [])])
    all_text = f"{name} {cats} {tags}"
    if any(w in all_text for w in ['women', 'female', 'girl', 'ladies']):
        return "Female"
    elif any(w in all_text for w in ['men', 'male', 'boy']):
        return "Male"
    return "Unisex"

def get_product_category(product):
    cats = [c.get('name', '') for c in product.get('categories', [])]
    return " > ".join(cats) if cats else ""

def debug_product(product):
    st.write("**Product ID:**", product.get('id'))
    st.write("**Name:**", product.get('name'))
    st.write("**SKU:**", product.get('sku'))
    st.write("**Price:**", product.get('price'))
    st.write("**Type:**", product.get('type'))
    st.write("**Stock:**", product.get('stock_status'))
    st.write("**Attributes:**")
    for a in product.get('attributes', []):
        st.write(f" - `{a.get('name')}` : {a.get('options')}")
    st.write("**Description Length:**", len(product.get('description', '')))
    st.write("**Short Description:**", clean_html(product.get('short_description', ''))[:300])

# ============================================================
# BUILD FUNCTIONS
# ============================================================
def build_primary(product, store_name):
    images = product.get('images', [])
    image_link = images[0]['src'] if images else ""
    additional_images = ",".join([img['src'] for img in images[1:]]) + "," if len(images) > 1 else ""
    price = product.get('price', '') or product.get('regular_price', '') or product.get('sale_price', '')
    price_str = f"{price} USD" if price else ""
    stock = product.get('stock_status', '')
    availability = "in_stock" if stock == 'instock' else "out_of_stock"
    
    color = get_color_improved(product)
    material = get_attribute(product, 'material', 'fabric', 'kapra')

    return {
        "id": str(product.get('id', '')),
        "title": product.get('name', ''),
        "description": clean_html(product.get('description', '') or product.get('short_description', '')),
        "link": product.get('permalink', ''),
        "image_link": image_link,
        "additional image link": additional_images,
        "condition": "New",
        "price": price_str,
        "availability": availability,
        "mpn": product.get('sku', ''),
        "brand": store_name,
        "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "material": material,
        "product_type": get_product_category(product),
        "identifier_exists": "No",
        "color": color,
        "gender": detect_gender(product)
    }

def build_supplemental_rows(product, store_name, variations):
    color = get_color_improved(product)
    gender = detect_gender(product)
    product_id = str(product.get('id', ''))
    title = product.get('name', '')

    if variations:
        sizes = get_sizes_from_variations(variations)
    else:
        sizes = get_sizes_from_attributes(product)

    rows = []
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

db_fieldnames = ["sku", "product_id", "url", "store", "title"]

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 SKU se Fetch Karo",
    "🗄️ Product Database",
    "📦 Sab Products",
    "🔍 Debug (Test)"
])

# ============================================================
# TAB 1 - SKU se Fetch
# ============================================================
with tab1:
    st.subheader("SKU se Products Fetch Karo")
    st.info("SKU daalo → Color ab Product Specifications se bhi lega ✅")
    store_choice_t1 = st.selectbox("Store select karo:", list(STORES.keys()), key="t1_store")
    sku_input = st.text_area("SKUs daalo (har SKU alag line mein):", height=150, placeholder="JC-1234\nJC-5678")
    
    if st.button("🚀 Fetch Karo", use_container_width=True, key="sku_fetch"):
        skus = [s.strip() for s in sku_input.strip().split("\n") if s.strip()]
        if not skus:
            st.warning("Pehle SKU daalo!")
        else:
            store = STORES[store_choice_t1]
            all_primary, all_supplemental = [], []
            progress = st.progress(0)
            for i, sku in enumerate(skus, 1):
                st.write(f"**[{i}/{len(skus)}]** SKU: `{sku}`")
                product = get_product_by_sku(store, sku)
                if product:
                    variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                    primary = build_primary(product, store_choice_t1)
                    supplemental = build_supplemental_rows(product, store_choice_t1, variations)
                    all_primary.append(primary)
                    all_supplemental.extend(supplemental)
                    st.write(f"✅ **{product.get('name')}** | **Color:** `{primary['color']}`")
                else:
                    st.write(f"❌ SKU nahi mila: `{sku}`")
                progress.progress(i / len(skus))
                time.sleep(0.3)
            
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

# ============================================================
# TAB 2 - Product Database
# ============================================================
with tab2:
    st.subheader("🗄️ Product Database")
    st.info("Store ke sab SKUs + URLs database mein save karo")
    store_choice_t2 = st.selectbox("Store:", ["Sab Stores"] + list(STORES.keys()), key="t2_store")
    c1, c2 = st.columns(2)
    with c1:
        scan_btn = st.button("🔍 Scan & Save Karo", use_container_width=True)
    with c2:
        check_btn = st.button("🆕 Naye Products Check Karo", use_container_width=True)
    
    if scan_btn or check_btn:
        st.info("Yeh feature abhi same hai...")

# ============================================================
# TAB 3 - Sab Products
# ============================================================
with tab3:
    st.subheader("📦 Sab Products Feed Mein Daalo")
    store_choice_t3 = st.selectbox("Store:", list(STORES.keys()), key="t3_store")
    mode = st.radio("Mode:", ["Neeche Append Karo", "Sheet Clear Karke Naya Banao"], horizontal=True)
    
    if st.button("📦 Sab Products Fetch Karo", use_container_width=True):
        store = STORES[store_choice_t3]
        with st.spinner("Sab products aa rahe hain..."):
            products = get_all_products(store)
        if not products:
            st.error("Koi product nahi mila!")
        else:
            st.info(f"**{len(products)}** products mile")
            all_primary, all_supplemental = [], []
            progress = st.progress(0)
            for i, product in enumerate(products, 1):
                variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                all_primary.append(build_primary(product, store_choice_t3))
                all_supplemental.extend(build_supplemental_rows(product, store_choice_t3, variations))
                progress.progress(i / len(products))
                if i % 20 == 0:
                    time.sleep(0.3)
            
            with st.spinner("Google Sheet update ho rahi hai..."):
                try:
                    spreadsheet = get_spreadsheet()
                    p_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    s_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
                    if mode == "Sheet Clear Karke Naya Banao":
                        p_sheet.clear()
                        s_sheet.clear()
                    append_to_sheet(p_sheet, primary_fieldnames, all_primary)
                    append_to_sheet(s_sheet, supplemental_fieldnames, all_supplemental)
                    st.success("✅ Sheet update ho gayi!")
                except Exception as e:
                    st.error(f"Sheet error: {e}")

# ============================================================
# TAB 4 - DEBUG
# ============================================================
with tab4:
    st.subheader("🔍 Debug — Product Raw Data Dekho")
    store_choice_t4 = st.selectbox("Store:", list(STORES.keys()), key="t4_store")
    debug_sku = st.text_input("SKU daalo:", placeholder="JC-1234")
    
    if st.button("🔍 Raw Data Dekho", use_container_width=True):
        if not debug_sku.strip():
            st.warning("SKU daalo!")
        else:
            store = STORES[store_choice_t4]
            product = get_product_by_sku(store, debug_sku.strip())
            if product:
                st.success(f"✅ Product mila: **{product.get('name')}**")
                debug_product(product)
                st.write("**Extracted Color:**", get_color_improved(product))
                if product.get('type') == 'variable':
                    variations = get_variations(store, product['id'])
                    st.write("**Variations (first 3):**")
                    for v in variations[:3]:
                        st.write(f"Variation ID: {v.get('id')} | Attrs: {v.get('attributes')}")
            else:
                st.error(f"SKU `{debug_sku}` nahi mila!")

st.sidebar.success("✅ Color Logic Updated - Specifications se lega")
