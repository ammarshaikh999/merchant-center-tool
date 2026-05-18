import streamlit as st
import requests
import time
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Merchant Center Tool", page_icon="🛍️", layout="wide")
st.title("🛍️ Merchant Center Tool")

STORES = {
    "Jacket Cult": {
        "STORE_URL": "https://jacketcult.shop",
        "CK": "ck_9226b1b1c260e12500d7249a2a9e2d3bc14e6d16",
        "CS": "cs_69410665a3da1caa4994a0ba24151c4d9c207e46"
    }
}

def wc_get(store, endpoint, params={}):
    url = f"{store['STORE_URL']}/wp-json/wc/v3/{endpoint}"
    try:
        resp = requests.get(url, auth=(store['CK'], store['CS']), params=params, timeout=15)
        st.write(f"Status Code: {resp.status_code}")  # Debugging
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"API Error: {resp.status_code} - {resp.text[:300]}")
    except Exception as e:
        st.error(f"Request Failed: {e}")
    return None

def get_product_by_sku(store, sku):
    return wc_get(store, "products", {"sku": sku})

# ===================== MAIN APP =====================
st.subheader("SKU se Products Fetch Karo")
store_choice = st.selectbox("Store", ["Jacket Cult"])
sku_input = st.text_area("SKU daalo:", "18750756522003", height=100)

if st.button("🚀 Fetch Karo", use_container_width=True):
    with st.spinner("Product fetch ho raha hai..."):
        sku = sku_input.strip()
        st.write(f"Searching SKU: `{sku}`")
        
        product = get_product_by_sku(STORES[store_choice], sku)
        
        if product:
            st.success("✅ Product Mila!")
            st.json(product)   # Raw data dikhayega
            st.write("**Name:**", product.get('name'))
            st.write("**Gender Attribute:**", [a for a in product.get('attributes', []) if 'gender' in a.get('name','').lower() or 'size' in a.get('name','').lower()])
        else:
            st.error("❌ Product nahi mila ya API error hai")

st.sidebar.info("Simple Debug Mode ON")
