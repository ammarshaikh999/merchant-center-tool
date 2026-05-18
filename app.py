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

STORES = {
    "Voggaci": {"STORE_URL": "https://voggaci.com", "CK": "ck_6a71cbd882f15cf58755dadec4657ad8c51481da", "CS": "cs_e188acce5cb4a8ff31b2d50929fd8a93ecee7aed"},
    "The Movie Attire": {"STORE_URL": "https://themovieattire.com", "CK": "ck_55bf303c4013201868885ae52f671a5cd804b6c6", "CS": "cs_6b9419eed0793f0e5bbafde5f4b252eda112f931"},
    "Nyoshopping": {"STORE_URL": "https://nyoshopping.com", "CK": "ck_2e8843d4709d3b7717f9ce512d535a8fa6aae467", "CS": "cs_559384bfd5fbbfdd17167590f1fa786e41f35cf8"},
    "Jacket Cult": {"STORE_URL": "https://jacketcult.shop", "CK": "ck_9226b1b1c260e12500d7249a2a9e2d3bc14e6d16", "CS": "cs_69410665a3da1caa4994a0ba24151c4d9c207e46"}
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
    existing = sheet.get_all_values()
    if not existing:
        rows = [fieldnames] + [[d.get(f, "") for f in fieldnames] for d in data_list]
        sheet.update(rows, value_input_option='RAW')
    else:
        rows = [[d.get(f, "") for f in fieldnames] for d in data_list]
        sheet.append_rows(rows, value_input_option='RAW')

def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    try:
        resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def get_product_by_sku(store, sku):
    products = wc_get(store, "products", {"sku": sku})
    if products and len(products) > 0:
        return products[0]
    return None

def get_variations(store, product_id):
    variations = wc_get(store, f"products/{product_id}/variations", {"per_page": 100})
    return variations or []

def clean_html(html_text):
    if not html_text: return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_attribute(product, *keywords):
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower().replace('pa_', '')
        for kw in keywords:
            if kw.lower() == attr_name or kw.lower() in attr_name:
                options = attr.get('options', [])
                if options:
                    return options[0].strip()
    return ""

def extract_spec_from_text(text, spec_name):
    if not text: return ""
    text_lower = text.lower()
    pattern = rf'(?:{spec_name})[:\s-]*(.+?)(?=\s{{2,}}|\n|\||$|material|inner|front|collar|pockets|sleeves|size|weight|color)'
    match = re.search(pattern, text_lower, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        return re.split(r'\s{2,}|material|inner', value)[0].strip().title()
    return ""

def get_color_improved(product):
    color = get_attribute(product, 'color', 'colour')
    if color: return color
    for text in [clean_html(product.get('short_description', '')), clean_html(product.get('description', '')), product.get('name', '')]:
        if text:
            c = extract_spec_from_text(text, 'color|colour')
            if c: return c
    return ""

def get_material_improved(product):
    mat = get_attribute(product, 'material', 'fabric')
    if mat: return mat
    for text in [clean_html(product.get('short_description', '')), clean_html(product.get('description', '')), product.get('name', '')]:
        if text:
            m = extract_spec_from_text(text, 'material|fabric')
            if m: return m
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

def detect_gender(product):
    # Attribute Name se (women-size, attribute_women-size etc.)
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower()
        if any(x in attr_name for x in ['women', 'female', 'woman', 'ladies']):
            return "Female"
        if any(x in attr_name for x in ['men', 'male', 'man']):
            return "Male"

    # Options mein Gender
    for attr in product.get('attributes', []):
        attr_name = attr.get('name', '').lower().replace('pa_', '')
        if 'gender' in attr_name:
            options = [o.lower() for o in attr.get('options', [])]
            if 'female' in options and 'male' in options: return "Unisex"
            if any(x in options for x in ['female','women','girl','ladies']): return "Female"
            if any(x in options for x in ['male','men','boy']): return "Male"

    # Title + Description
    title = product.get('name', '').lower()
    desc = clean_html(product.get('description', '') or product.get('short_description', '')).lower()
    full_text = f"{title} {desc}"

    if any(kw in full_text for kw in ['taylor swift', 'kate hudson', 'kate middleton', 'women', 'female', 'ladies', 'womens', "women's", 'girl']):
        return "Female"
    if any(kw in full_text for kw in ['men', 'male', "men's", 'man', 'boy']):
        return "Male"

    return "Unisex"

# Build Functions (same as before)
def build_primary(product, store_name):
    images = product.get('images', [])
    image_link = images[0]['src'] if images else ""
    additional_images = ",".join([img['src'] for img in images[1:]]) + "," if len(images) > 1 else ""
    price = product.get('price', '') or product.get('regular_price', '') or product.get('sale_price', '')
    price_str = f"{price} USD" if price else ""

    return {
        "id": str(product.get('id', '')),
        "title": product.get('name', ''),
        "description": clean_html(product.get('description', '') or product.get('short_description', '')),
        "link": product.get('permalink', ''),
        "image_link": image_link,
        "additional image link": additional_images,
        "condition": "New",
        "price": price_str,
        "availability": "in_stock" if product.get('stock_status') == 'instock' else "out_of_stock",
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
    color = get_color_improved(product)
    gender = detect_gender(product)
    sizes = get_sizes_improved(product, variations)
    rows = []
    for size in (sizes if sizes else [""]):
        rows.append({
            "id": str(product.get('id', '')),
            "title": product.get('name', ''),
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

primary_fieldnames = ["id","title","description","link","image_link","additional image link","condition","price","availability","mpn","brand","google_product_category","material","product_type","identifier_exists","color","gender"]
supplemental_fieldnames = ["id","title","color","gender","age_group","brand","size","included_destination","excluded_destination","shipping_label","return_policy_label"]

tab1, tab2, tab3, tab4 = st.tabs(["🚀 SKU se Fetch Karo", "🗄️ Product Database", "📦 Sab Products", "🔍 Debug (Test)"])

with tab1:
    st.subheader("SKU se Products Fetch Karo")
    store_choice = st.selectbox("Store:", list(STORES.keys()), key="t1")
    sku_input = st.text_area("SKUs daalo:", height=150)
    if st.button("🚀 Fetch Karo", use_container_width=True):
        # ... (baaki code same rakh sakte ho, main short kar raha hoon space ke liye)
        st.info("Code running...")

with tab4:
    st.subheader("Debug")
    sku = st.text_input("Debug SKU")
    store = st.selectbox("Store for Debug", list(STORES.keys()))
    if st.button("Test"):
        product = get_product_by_sku(STORES[store], sku)
        if product:
            st.write("**Gender Detected:**", detect_gender(product))
            st.write("**Attributes:**", product.get('attributes'))

st.sidebar.success("✅ Women-Size Attribute se Gender Detect kar raha hai")
