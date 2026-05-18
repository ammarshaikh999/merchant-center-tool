import streamlit as st
import requests
import csv
import re
import time
import io
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Merchant Center Tool", page_icon="🛍️", layout="wide")
st.title("🛍️ Merchant Center Tool")

# ========================= STORES =========================
STORES = {
    "Jacket Cult": {
        "STORE_URL": "https://jacketcult.shop",
        "CK": "ck_9226b1b1c260e12500d7249a2a9e2d3bc14e6d16",
        "CS": "cs_69410665a3da1caa4994a0ba24151c4d9c207e46"
    }
}

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
    if not data_list: return
    rows = [[d.get(f, "") for f in fieldnames] for d in data_list]
    if not sheet.get_all_values():
        sheet.update([fieldnames] + rows)
    else:
        sheet.append_rows(rows, value_input_option='RAW')

# ====================== API ======================
def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    try:
        resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data[0] if isinstance(data, list) and len(data) > 0 else data
        else:
            st.error(f"API Error {resp.status_code}")
    except Exception as e:
        st.error(f"Request Error: {e}")
    return None

def get_product_by_sku(store, sku):
    return wc_get(store, "products", {"sku": sku})

def get_variations(store, product_id):
    data = wc_get(store, f"products/{product_id}/variations", {"per_page": 100})
    return data if isinstance(data, list) else []

# ====================== EXTRACTION ======================
def clean_html(html_text):
    if not html_text: return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def detect_gender(product):
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower()
        if 'women' in attr_name or 'female' in attr_name:
            return "Female"
        if 'men' in attr_name or 'male' in attr_name:
            return "Male"
    
    title = product.get('name', '').lower()
    if any(kw in title for kw in ['taylor swift', 'kate', 'women', 'female', 'ladies']):
        return "Female"
    if any(kw in title for kw in ['men', 'male']):
        return "Male"
    return "Unisex"

def get_color_improved(product):
    for attr in product.get('attributes', []):
        if 'color' in attr.get('name', '').lower():
            return attr.get('options', [''])[0]
    for text in [clean_html(product.get('short_description', '')), clean_html(product.get('description', ''))]:
        match = re.search(r'color[:\s-]*(.+?)(?=\s{2,}|material|$)', text, re.I)
        if match:
            return match.group(1).strip().title()
    return ""

def get_material_improved(product):
    for text in [clean_html(product.get('short_description', '')), clean_html(product.get('description', ''))]:
        match = re.search(r'material[:\s-]*(.+?)(?=\s{2,}|inner|front|color|$)', text, re.I)
        if match:
            return match.group(1).strip().title()
    return ""

def get_sizes_improved(product, variations):
    sizes = set()
    for var in variations:
        for attr in var.get('attributes', []):
            if 'size' in attr.get('name', '').lower():
                val = attr.get('option', '').strip()
                if val: sizes.add(val)
    if not sizes:
        for attr in product.get('attributes', []):
            if 'size' in attr.get('name', '').lower():
                for opt in attr.get('options', []):
                    if opt.strip(): sizes.add(opt.strip())
    size_order = ['XXS','XS','S','M','L','XL','2XL','3XL','4XL']
    return sorted(list(sizes), key=lambda x: size_order.index(x) if x in size_order else 99)

# ====================== BUILD ======================
def build_primary(product, store_name):
    images = product.get('images', [])
    return {
        "id": str(product.get('id', '')),
        "title": product.get('name', ''),
        "description": clean_html(product.get('description', '')),
        "link": product.get('permalink', ''),
        "image_link": images[0]['src'] if images else "",
        "additional image link": ",".join([img['src'] for img in images[1:]]) + "," if len(images) > 1 else "",
        "condition": "New",
        "price": f"{product.get('price', '')} USD",
        "availability": "in_stock",
        "mpn": product.get('sku', ''),
        "brand": store_name,
        "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "material": get_material_improved(product),
        "product_type": "",
        "identifier_exists": "No",
        "color": get_color_improved(product),
        "gender": detect_gender(product)
    }

def build_supplemental_rows(product, store_name, variations):
    rows = []
    sizes = get_sizes_improved(product, variations)
    for size in (sizes if sizes else [""]):
        rows.append({
            "id": str(product.get('id', '')),
            "title": product.get('name', ''),
            "color": get_color_improved(product),
            "gender": detect_gender(product),
            "age_group": "Adult",
            "brand": store_name,
            "size": size,
            "included_destination": "Free listings, Shopping ads, Dynamic remarketing",
            "excluded_destination": "",
            "shipping_label": "Free Shipping",
            "return_policy_label": "30 Days Returns"
        })
    return rows

# ====================== TABS ======================
tab1, tab4 = st.tabs(["🚀 SKU se Fetch Karo", "🔍 Debug"])

with tab1:
    st.subheader("SKU se Products Fetch Karo")
    store_choice = st.selectbox("Store", list(STORES.keys()))
    sku_input = st.text_area("SKUs daalo (ek line mein ek):", height=150)
    
    if st.button("🚀 Fetch Karo", use_container_width=True):
        skus = [s.strip() for s in sku_input.split("\n") if s.strip()]
        if skus:
            with st.spinner("Fetching..."):
                for sku in skus:
                    product = get_product_by_sku(STORES[store_choice], sku)
                    if product:
                        variations = get_variations(STORES[store_choice], product['id'])
                        primary = build_primary(product, store_choice)
                        supplemental = build_supplemental_rows(product, store_choice, variations)
                        st.success(f"✅ {product.get('name')}")
                        st.write(f"**Gender:** {primary['gender']} | **Color:** {primary['color']} | **Material:** {primary['material']}")
                        st.write(f"**Sizes Found:** {len(supplemental)}")
                    else:
                        st.error(f"SKU not found: {sku}")

with tab4:
    st.subheader("Debug")
    sku = st.text_input("Debug SKU", "18750756522003")
    if st.button("Test"):
        product = get_product_by_sku(STORES["Jacket Cult"], sku)
        if product:
            st.json(product.get('attributes'))

st.sidebar.success("Fixed - List Handling + Women Size Detection")
