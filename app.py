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

# ============================================================
# GOOGLE SHEETS
# ============================================================
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
# API FUNCTIONS
# ============================================================
def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    try:
        resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except:
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
    return products[0] if products else None

def get_variations(store, product_id):
    return wc_get(store, f"products/{product_id}/variations", {"per_page": 100}) or []

# ============================================================
# EXTRACTION FUNCTIONS
# ============================================================
def clean_html(html_text):
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    return re.sub(r'\s+', ' ', text).strip()

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
    if not text:
        return ""
    pattern = rf'(?:{spec_name})[:\s-]*(.+?)(?=\s{{2,}}|\n|\||$|material|inner|front|collar|pockets|sleeves|size|weight|color)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        return re.split(r'\s{2,}|material|inner', value)[0].strip().title()
    return ""

def get_color_improved(product):
    color = get_attribute(product, 'color', 'colour')
    if color:
        return color
    for text in [
        clean_html(product.get('short_description', '')),
        clean_html(product.get('description', '')),
        product.get('name', '')
    ]:
        if text:
            c = extract_spec_from_text(text, 'color|colour')
            if c:
                return c
    return ""

def get_material_improved(product):
    mat = get_attribute(product, 'material', 'fabric')
    if mat:
        return mat
    for text in [
        clean_html(product.get('short_description', '')),
        clean_html(product.get('description', ''))
    ]:
        if text:
            m = extract_spec_from_text(text, 'material|fabric')
            if m:
                return m
    return ""

def get_sizes_improved(product, variations):
    sizes = []
    size_order = ['XXS', 'XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']

    # Variations se try karo
    seen = set()
    for var in variations:
        for attr in var.get('attributes', []):
            name = attr.get('name', '').lower().replace('pa_', '')
            if 'size' in name:
                val = attr.get('option', '').strip()
                if val and val not in seen:
                    sizes.append(val)
                    seen.add(val)

    # Agar variations se nahi mila toh product attributes se lo
    if not sizes:
        for attr in product.get('attributes', []):
            name = attr.get('name', '').lower().replace('pa_', '')
            if 'size' in name:
                for opt in attr.get('options', []):
                    val = opt.strip()
                    if val and val not in seen:
                        sizes.append(val)
                        seen.add(val)

    # Logical order mein sort karo
    sizes.sort(key=lambda x: size_order.index(x) if x in size_order else 99)
    return sizes

def detect_gender(product):
    """
    FIX: 'women' mein 'men' bhi hota hai — isliye pehle female check karo
    aur phir female words hata ke male check karo
    """
    text_parts = []
    text_parts.append(product.get('name', ''))
    for cat in product.get('categories', []):
        text_parts.append(cat.get('name', ''))
    for attr in product.get('attributes', []):
        text_parts.append(attr.get('name', ''))
        for opt in attr.get('options', []):
            text_parts.append(str(opt))

    full_text = " ".join(text_parts).lower()

    female_keywords = ['women', 'woman', 'female', 'ladies', 'girl', 'girls']
    male_keywords = ['men', 'man', 'male', 'boys', 'boy']

    # Female word boundary se check karo
    has_female = any(re.search(rf'\b{word}\b', full_text) for word in female_keywords)

    # Female words hata do phir male check karo — warna "women" mein "men" match hoga
    cleaned = re.sub(r'\b(?:women|woman|female|ladies|girl|girls)\b', '', full_text)
    has_male = any(re.search(rf'\b{word}\b', cleaned) for word in male_keywords)

    if has_female and has_male:
        return "Unisex"
    elif has_female:
        return "Female"
    elif has_male:
        return "Male"
    return "Unisex"

# ============================================================
# BUILD FUNCTIONS
# ============================================================
def build_primary(product, store_name):
    images = product.get('images', [])
    image_link = images[0]['src'] if images else ""
    additional_images = ",".join([img['src'] for img in images[1:]]) + "," if len(images) > 1 else ""
    price = product.get('price', '') or product.get('regular_price', '')
    price_str = f"{float(price):.2f} USD" if price else ""

    return {
        "id":                    str(product.get('id', '')),
        "title":                 product.get('name', ''),
        "description":           clean_html(product.get('description', '') or product.get('short_description', '')),
        "link":                  product.get('permalink', ''),
        "image_link":            image_link,
        "additional image link": additional_images,
        "condition":             "New",
        "price":                 price_str,
        "availability":          "in_stock" if product.get('stock_status') == 'instock' else "out_of_stock",
        "mpn":                   product.get('sku', ''),
        "brand":                 store_name,
        "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "material":              get_material_improved(product),
        "product_type":          "",
        "identifier_exists":     "No",
        "color":                 get_color_improved(product),
        "gender":                detect_gender(product)
    }

def build_supplemental_rows(product, store_name, variations):
    sizes = get_sizes_improved(product, variations)
    rows = []
    for size in (sizes if sizes else [""]):
        rows.append({
            "id":                   str(product.get('id', '')),
            "title":                product.get('name', ''),
            "color":                get_color_improved(product),
            "gender":               detect_gender(product),
            "age_group":            "Adult",
            "brand":                store_name,
            "size":                 size,
            "included_destination": "Free listings, Shopping ads, Dynamic remarketing",
            "excluded_destination": "",
            "shipping_label":       "Free Shipping",
            "return_policy_label":  "30 Days Returns"
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
    st.info("SKU daalo → WooCommerce API se seedha data ✅")
    store_choice_t1 = st.selectbox("Store:", list(STORES.keys()), key="t1_store")
    sku_input = st.text_area("SKUs (har SKU alag line mein):", height=150, placeholder="JC-1234\nJC-5678")

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
                    st.write(f"✅ **{product.get('name')}** | Color: `{primary['color']}` | Gender: `{primary['gender']}` | Sizes: `{[r['size'] for r in supplemental]}`")
                else:
                    st.write(f"❌ SKU nahi mila: `{sku}`")
                progress.progress(i / len(skus))
                time.sleep(0.3)

            if all_primary:
                with st.spinner("Google Sheet update ho rahi hai..."):
                    try:
                        spreadsheet = get_spreadsheet()
                        append_to_sheet(get_or_create_tab(spreadsheet, "Primary Feed"), primary_fieldnames, all_primary)
                        time.sleep(2)
                        append_to_sheet(get_or_create_tab(spreadsheet, "Supplemental Feed"), supplemental_fieldnames, all_supplemental)
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
                st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

# ============================================================
# TAB 2 - Product Database
# ============================================================
with tab2:
    st.subheader("🗄️ Product Database")
    st.info("Store ke sab SKUs + URLs database mein save karo.")
    store_choice_t2 = st.selectbox("Store:", ["Sab Stores"] + list(STORES.keys()), key="t2_store")
    c1, c2 = st.columns(2)
    with c1:
        scan_btn = st.button("🔍 Scan & Save Karo", use_container_width=True)
    with c2:
        check_btn = st.button("🆕 Naye Products Check Karo", use_container_width=True)

    if scan_btn:
        stores_to_scan = list(STORES.keys()) if store_choice_t2 == "Sab Stores" else [store_choice_t2]
        try:
            spreadsheet = get_spreadsheet()
            db_sheet = get_or_create_tab(spreadsheet, "URL Database")
            existing_data = db_sheet.get_all_values()
            existing_skus = set()
            if len(existing_data) > 1 and 'sku' in existing_data[0]:
                idx = existing_data[0].index('sku')
                existing_skus = {row[idx] for row in existing_data[1:] if len(row) > idx}
            new_rows = []
            for store_name in stores_to_scan:
                st.write(f"🔍 **{store_name}** scan ho raha hai...")
                with st.spinner("..."):
                    products = get_all_products(STORES[store_name])
                added = 0
                for p in products:
                    sku = p.get('sku', '').strip()
                    if sku and sku not in existing_skus:
                        new_rows.append([sku, str(p.get('id', '')), p.get('permalink', ''), store_name, p.get('name', '')])
                        existing_skus.add(sku)
                        added += 1
                st.write(f"   → {len(products)} total, **{added} naye**")
            if new_rows:
                if not existing_data:
                    db_sheet.update([db_fieldnames] + new_rows, value_input_option='RAW')
                else:
                    db_sheet.append_rows(new_rows, value_input_option='RAW')
                st.success(f"✅ {len(new_rows)} naye products save ho gaye!")
            else:
                st.success("✅ Database already updated!")
            st.markdown(f"📊 **[Database dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")
        except Exception as e:
            st.error(f"Error: {e}")

    if check_btn:
        stores_to_scan = list(STORES.keys()) if store_choice_t2 == "Sab Stores" else [store_choice_t2]
        try:
            spreadsheet = get_spreadsheet()
            db_sheet = get_or_create_tab(spreadsheet, "URL Database")
            existing_data = db_sheet.get_all_values()
            existing_skus = set()
            if len(existing_data) > 1 and 'sku' in existing_data[0]:
                idx = existing_data[0].index('sku')
                existing_skus = {row[idx] for row in existing_data[1:] if len(row) > idx}
            new_products = []
            for store_name in stores_to_scan:
                with st.spinner(f"{store_name}..."):
                    products = get_all_products(STORES[store_name])
                for p in products:
                    sku = p.get('sku', '').strip()
                    if sku and sku not in existing_skus:
                        new_products.append({"store": store_name, "sku": sku, "title": p.get('name', ''), "url": p.get('permalink', ''), "id": str(p.get('id', ''))})
            if new_products:
                st.warning(f"🆕 **{len(new_products)} naye products** mile!")
                for p in new_products:
                    st.write(f"• **{p['store']}** | `{p['sku']}` | {p['title']}")
                if st.button("✅ Add Karo"):
                    rows = [[p['sku'], p['id'], p['url'], p['store'], p['title']] for p in new_products]
                    get_or_create_tab(get_spreadsheet(), "URL Database").append_rows(rows, value_input_option='RAW')
                    st.success("✅ Add ho gaye!")
            else:
                st.success("✅ Koi naya product nahi!")
        except Exception as e:
            st.error(f"Error: {e}")

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
            st.info(f"**{len(products)}** products mile...")
            all_primary, all_supplemental = [], []
            progress = st.progress(0)
            for i, product in enumerate(products, 1):
                variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                all_primary.append(build_primary(product, store_choice_t3))
                all_supplemental.extend(build_supplemental_rows(product, store_choice_t3, variations))
                progress.progress(i / len(products))
                if i % 10 == 0:
                    time.sleep(0.3)
            with st.spinner("Sheet update ho rahi hai..."):
                try:
                    spreadsheet = get_spreadsheet()
                    p_sheet = get_or_create_tab(spreadsheet, "Primary Feed")
                    s_sheet = get_or_create_tab(spreadsheet, "Supplemental Feed")
                    if mode == "Sheet Clear Karke Naya Banao":
                        p_sheet.clear(); s_sheet.clear(); time.sleep(1)
                    append_to_sheet(p_sheet, primary_fieldnames, all_primary)
                    time.sleep(2)
                    append_to_sheet(s_sheet, supplemental_fieldnames, all_supplemental)
                    st.success("✅ Sheet update ho gayi!")
                except Exception as e:
                    st.error(f"Error: {e}")
            out1 = io.StringIO()
            w1 = csv.DictWriter(out1, fieldnames=primary_fieldnames)
            w1.writeheader(); w1.writerows(all_primary)
            out2 = io.StringIO()
            w2 = csv.DictWriter(out2, fieldnames=supplemental_fieldnames)
            w2.writeheader(); w2.writerows(all_supplemental)
            st.success(f"🎉 {len(all_primary)} products, {len(all_supplemental)} supplemental rows!")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📥 Primary Feed", out1.getvalue(), "primary_feed.csv", "text/csv", use_container_width=True)
            with c2:
                st.download_button("📥 Supplemental Feed", out2.getvalue(), "supplemental_feed.csv", "text/csv", use_container_width=True)
            st.markdown(f"📊 **[Google Sheet dekho](https://docs.google.com/spreadsheets/d/{SHEET_ID})**")

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
                st.success(f"✅ **{product.get('name')}**")
                st.write("**ID:**", product.get('id'))
                st.write("**SKU:**", product.get('sku'))
                st.write("**Price:**", product.get('price'))
                st.write("**Type:**", product.get('type'))
                st.write("**Stock:**", product.get('stock_status'))
                st.write("**Attributes:**")
                for a in product.get('attributes', []):
                    st.write(f"  - `{a.get('name')}` : {a.get('options')}")
                st.write("---")
                variations = get_variations(store, product['id']) if product.get('type') == 'variable' else []
                st.write("**Color:**", get_color_improved(product))
                st.write("**Material:**", get_material_improved(product))
                st.write("**Gender:**", detect_gender(product))
                st.write("**Sizes:**", get_sizes_improved(product, variations))
            else:
                st.error(f"SKU `{debug_sku}` nahi mila!")
