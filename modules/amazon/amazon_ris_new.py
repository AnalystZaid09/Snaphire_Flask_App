import streamlit as st
import pandas as pd
import numpy as np
import re
import gc
from io import BytesIO
from common.ui_utils import (
    apply_professional_style, 
    render_header,
    download_module_report,
    auto_save_generated_reports
)

# Module name for MongoDB collection
MODULE_NAME = "amazon"
TOOL_NAME = "amazon_ris"

# Page configuration
st.set_page_config(
    page_title="RIS Analysis Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)
apply_professional_style()

# Custom CSS
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f0f2f6;
        border-radius: 5px 5px 0 0;
        padding: 10px 20px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0068c9;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

render_header("RIS Analysis Dashboard")

# Helper functions
def clean_text(x):
    if pd.isna(x):
        return ""
    return re.sub(r"\s+", "", str(x).lower())

def normalize_sku(x):
    if pd.isna(x):
        return ""
    return str(x).strip().upper().replace(" ", "")

def normalize_shipping_state(shipping_state, fc_state, state_rules):
    ship = clean_text(shipping_state)
    fc = str(fc_state).strip()
    
    if fc in state_rules:
        for variant in state_rules[fc]:
            if ship == clean_text(variant):
                return fc
    
    return shipping_state

def to_excel(df):
    output = BytesIO()
    # Convert object columns to string to avoid PyArrow type conversion errors
    df_copy = df.copy()
    for col in df_copy.columns:
        if df_copy[col].dtype == 'object':
            df_copy[col] = df_copy[col].astype(str)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_copy.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

# State rules for normalization
STATE_RULES = {
    "Delhi": ["delhi", "dl", "newdelhi", "nctdelhi", "haryana", "harayana", "hr"],
    "Haryana": ["haryana", "harayana", "hr", "delhi", "dl", "newdelhi", "nctdelhi", "chandigarh", "chd"],
    "Karnataka": ["karnataka", "ka", "bangalore", "bengaluru"],
    "Madhya Pradesh": ["madhyapradesh", "mp", "indore", "bhopal"],
    "Maharashtra": ["maharashtra", "mh", "dadra", "nagarhaveli", "dadra&nagarhaveli", "dnh"],
    "Uttar Pradesh": ["uttarpradesh", "up"],
    "Telangana": ["telangana", "tg", "hyderabad"],
    "West Bengal": ["westbengal", "wb", "kolkata"],
    "Punjab": ["punjab", "pb", "chandigarh", "chd"],
    "Kerala": ["kerala", "kl", "trivandrum", "thiruvananthapuram"],
    "Orissa": ["orissa", "odisha", "or", "bhubaneswar"],
    "Tamil Nadu": ["tamilnadu", "tn", "chennai"],
    "Gujarat": ["gujarat", "gj", "ahmedabad", "surat"],
    "Rajasthan": ["rajasthan", "rj", "jaipur"],
    "Anadhra Pradesh": ["andhrapradesh", "ap", "visakhapatnam", "vizag"],
    "Bihar": ["bihar", "br", "patna"],
}

# Title - REMOVED since we use render_header
# st.title("📊 RIS Analysis Dashboard")
# st.markdown("---")

# Initialize session state
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'all_results' not in st.session_state:
    st.session_state.all_results = {}
if 'manager_data' not in st.session_state:
    st.session_state.manager_data = None
if 'manager_results' not in st.session_state:
    st.session_state.manager_results = {}

# Sidebar for file upload
with st.sidebar:
    st.header(" Select Manager Type")
    manager_type = st.selectbox(
        "Choose Manager Type",
        ["Portal", "Manager"],
        index=0
    )
    
    st.markdown("---")
    
    if manager_type == "Portal":
        st.header("📁 Upload Files")
        st.markdown("Upload all three required files:")
        
        ris_file = st.file_uploader("Upload RIS.csv", type=['csv'], key='ris')
        state_fc_file = st.file_uploader("Upload State FC Cluster.xlsx", type=['xlsx', 'xls'], key='statefc')
        purchase_file = st.file_uploader("Upload PM.xlsx", type=['xlsx', 'xls'], key='purchase')
        
        st.markdown("---")
        
        # Clear cache button
        if st.button("🗑️ Clear Cache", use_container_width=True):
            st.session_state.processed_data = None
            st.session_state.all_results = {}
            st.session_state.manager_data = None
            st.session_state.manager_results = {}
            st.rerun()
        
        if st.button("🔄 Process Data", use_container_width=True):
            if ris_file and state_fc_file and purchase_file:
                with st.spinner("Processing data (Extreme Memory Optimization)..."):
                    try:
                        # 1. READ MINIMAL COLUMNS
                        # RIS Data (usually the largest)
                        ris_cols = ["Amazon Order Id", "Merchant SKU", "Shipped Quantity", "Shipping State", "FC", "Purchase Date", "Payments Date"]
                        ris_df = pd.read_csv(ris_file, usecols=lambda x: x in ris_cols)
                        
                        # State FC Mapping
                        state_fc_cols = ["FC", "State", "Cluster", "State Cluster"] # Assuming these based on line 158
                        # Need to check actual column indices since it was using state_fc_df.columns[0-3]
                        # Let's read first few rows to get column names safely
                        temp_fc = pd.read_excel(state_fc_file, sheet_name="Sheet2", nrows=0)
                        fc_actual_cols = temp_fc.columns.tolist()[:4]
                        state_fc_df = pd.read_excel(state_fc_file, sheet_name="Sheet2", usecols=fc_actual_cols)
                        del temp_fc
                        
                        # Purchase/Product Master
                        pur_cols = ["Amazon Sku Name", "ASIN", "Vendor SKU Codes", "Brand Manager", "Brand", "Product Name"]
                        purchase_df = pd.read_excel(purchase_file, usecols=pur_cols)
                        
                        # Aggressive GC
                        gc.collect()

                        # 2. RENAME & CATEGORIZE FC DATA
                        state_fc_df.columns = ["FC", "FC State", "FC Cluster", "FC State Cluster"]
                        for col in ["FC State", "FC Cluster", "FC State Cluster"]:
                            state_fc_df[col] = state_fc_df[col].astype("category")
                        
                        # Create mappings
                        fc_state_map = dict(zip(state_fc_df["FC"], state_fc_df["FC State"]))
                        fc_cluster_map = dict(zip(state_fc_df["FC"], state_fc_df["FC Cluster"]))
                        fc_state_cluster_map = dict(zip(state_fc_df["FC"], state_fc_df["FC State Cluster"]))
                        del state_fc_df
                        
                        # 3. MAP FC DATA TO RIS
                        ris_df["FC State"] = ris_df["FC"].map(fc_state_map).astype("category")
                        ris_df["FC Cluster"] = ris_df["FC"].map(fc_cluster_map).astype("category")
                        ris_df["FC State Cluster"] = ris_df["FC"].map(fc_state_cluster_map).astype("category")
                        
                        del fc_state_map, fc_cluster_map, fc_state_cluster_map
                        gc.collect()

                        # 4. NORMALIZE & MAP PRODUCT DATA
                        purchase_df["Amazon Sku Name"] = purchase_df["Amazon Sku Name"].apply(normalize_sku)
                        ris_df["Merchant SKU"] = ris_df["Merchant SKU"].apply(normalize_sku)
                        
                        # Map Brand first (most important for pivots)
                        brand_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Brand"]))
                        ris_df["Brand"] = ris_df["Merchant SKU"].map(brand_map).astype("category")
                        del brand_map
                        
                        # Map other product data
                        ris_df["ASIN"] = ris_df["Merchant SKU"].map(dict(zip(purchase_df["Amazon Sku Name"], purchase_df["ASIN"])))
                        ris_df["Vendor SKU"] = ris_df["Merchant SKU"].map(dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Vendor SKU Codes"])))
                        ris_df["Brand Manager"] = ris_df["Merchant SKU"].map(dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Brand Manager"]))).astype("category")
                        ris_df["Product Name"] = ris_df["Merchant SKU"].map(dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Product Name"])))
                        
                        del purchase_df
                        gc.collect()

                        # 5. CALCULATE RIS STATUS
                        # Optimize shipping state normalization by using a vectorized approach if possible
                        # or at least clean up immediately
                        ris_df["Shipping State Corrected"] = ris_df.apply(
                            lambda x: normalize_shipping_state(str(x["Shipping State"]), str(x["FC State"]), STATE_RULES),
                            axis=1
                        ).astype("category")
                        
                        ris_df["RIS Status"] = np.where(
                            ris_df["Shipping State Corrected"].str.upper().str.strip() == 
                            ris_df["FC State"].str.upper().str.strip(),
                            "RIS",
                            "Non RIS"
                        )
                        ris_df["RIS Status"] = ris_df["RIS Status"].astype("category")
                        
                        # Downcast Shipped Quantity
                        if "Shipped Quantity" in ris_df.columns:
                            ris_df["Shipped Quantity"] = pd.to_numeric(ris_df["Shipped Quantity"], errors='coerce').fillna(0).astype("int32")

                        # Convert objects to string for Streamlit/Arrow compatibility
                        for col in ris_df.columns:
                            if ris_df[col].dtype == 'object':
                                ris_df[col] = ris_df[col].astype(str)
                        
                        # Store processed data (this is the big one in session state)
                        st.session_state.processed_data = ris_df
                        
                        # Generate all pivots
                        results = {}
                        
                        # 1. Brand-wise RIS
                        brand_wise = pd.pivot_table(
                            ris_df, index="Brand", columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        # Ensure columns exist
                        if "RIS" not in brand_wise.columns:
                            brand_wise["RIS"] = 0
                        if "Non RIS" not in brand_wise.columns:
                            brand_wise["Non RIS"] = 0
                        brand_wise["Grand Total"] = brand_wise["RIS"] + brand_wise["Non RIS"]
                        brand_wise["RIS %"] = ((brand_wise["RIS"] / brand_wise["Grand Total"].replace(0, 1)) * 100).round(2).fillna(0)
                        brand_wise["Non RIS %"] = ((brand_wise["Non RIS"] / brand_wise["Grand Total"].replace(0, 1)) * 100).round(2).fillna(0)
                        # Add Grand Total row
                        total_sum = brand_wise["Grand Total"].sum()
                        grand_total_row = pd.DataFrame({
                            "Brand": ["Grand Total"],
                            "RIS": [brand_wise["RIS"].sum()],
                            "Non RIS": [brand_wise["Non RIS"].sum()],
                            "Grand Total": [total_sum],
                            "RIS %": [round((brand_wise["RIS"].sum() / max(total_sum, 1)) * 100, 2)],
                            "Non RIS %": [round((brand_wise["Non RIS"].sum() / max(total_sum, 1)) * 100, 2)]
                        })
                        brand_wise = pd.concat([brand_wise, grand_total_row], ignore_index=True)
                        results['brand_wise'] = brand_wise
                        
                        # 2. ASIN-wise RIS
                        asin_wise = pd.pivot_table(
                            ris_df, index=["ASIN", "Brand"], columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        if "RIS" not in asin_wise.columns:
                            asin_wise["RIS"] = 0
                        if "Non RIS" not in asin_wise.columns:
                            asin_wise["Non RIS"] = 0
                        asin_wise["Grand Total"] = asin_wise["RIS"] + asin_wise["Non RIS"]
                        asin_wise["RIS %"] = ((asin_wise["RIS"] / asin_wise["Grand Total"]) * 100).round(2)
                        asin_wise["Non RIS %"] = ((asin_wise["Non RIS"] / asin_wise["Grand Total"]) * 100).round(2)
                        # Add Grand Total row
                        grand_total_row = pd.DataFrame({
                            "ASIN": ["Grand Total"],
                            "Brand": [""],
                            "RIS": [asin_wise["RIS"].sum()],
                            "Non RIS": [asin_wise["Non RIS"].sum()],
                            "Grand Total": [asin_wise["Grand Total"].sum()],
                            "RIS %": [round((asin_wise["RIS"].sum() / asin_wise["Grand Total"].sum()) * 100, 2)],
                            "Non RIS %": [round((asin_wise["Non RIS"].sum() / asin_wise["Grand Total"].sum()) * 100, 2)]
                        })
                        asin_wise = pd.concat([asin_wise, grand_total_row], ignore_index=True)
                        results['asin_wise'] = asin_wise
                        
                        # 3. Cluster-wise RIS
                        cluster_wise = pd.pivot_table(
                            ris_df, index="FC Cluster", columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        if "RIS" not in cluster_wise.columns:
                            cluster_wise["RIS"] = 0
                        if "Non RIS" not in cluster_wise.columns:
                            cluster_wise["Non RIS"] = 0
                        cluster_wise["Grand Total"] = cluster_wise["RIS"] + cluster_wise["Non RIS"]
                        cluster_wise["RIS %"] = ((cluster_wise["RIS"] / cluster_wise["Grand Total"]) * 100).round(2)
                        cluster_wise["Non RIS %"] = ((cluster_wise["Non RIS"] / cluster_wise["Grand Total"]) * 100).round(2)
                        # Add Grand Total row
                        grand_total_row = pd.DataFrame({
                            "FC Cluster": ["Grand Total"],
                            "RIS": [cluster_wise["RIS"].sum()],
                            "Non RIS": [cluster_wise["Non RIS"].sum()],
                            "Grand Total": [cluster_wise["Grand Total"].sum()],
                            "RIS %": [round((cluster_wise["RIS"].sum() / cluster_wise["Grand Total"].sum()) * 100, 2)],
                            "Non RIS %": [round((cluster_wise["Non RIS"].sum() / cluster_wise["Grand Total"].sum()) * 100, 2)]
                        })
                        cluster_wise = pd.concat([cluster_wise, grand_total_row], ignore_index=True)
                        results['cluster_wise'] = cluster_wise
                        
                        # 4. Cluster-Brand pivot WITH GRAND TOTAL
                        cluster_brand = pd.pivot_table(
                            ris_df, index=["FC Cluster", "Brand"], columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        if "RIS" not in cluster_brand.columns:
                            cluster_brand["RIS"] = 0
                        if "Non RIS" not in cluster_brand.columns:
                            cluster_brand["Non RIS"] = 0
                        # Ensure numeric types
                        cluster_brand["RIS"] = pd.to_numeric(cluster_brand["RIS"], errors='coerce').fillna(0)
                        cluster_brand["Non RIS"] = pd.to_numeric(cluster_brand["Non RIS"], errors='coerce').fillna(0)
                        cluster_brand["Grand Total"] = cluster_brand["RIS"] + cluster_brand["Non RIS"]
                        cluster_brand["RIS %"] = ((cluster_brand["RIS"] / cluster_brand["Grand Total"]) * 100).round(2).fillna(0)
                        cluster_brand["Non RIS %"] = ((cluster_brand["Non RIS"] / cluster_brand["Grand Total"]) * 100).round(2).fillna(0)
                        
                        # Calculate Grand Total from original data
                        total_ris = float(cluster_brand["RIS"].sum())
                        total_non_ris = float(cluster_brand["Non RIS"].sum())
                        total_grand = total_ris + total_non_ris
                        
                        # Add Grand Total row
                        grand_total_row = pd.DataFrame({
                            "FC Cluster": ["Grand Total"],
                            "Brand": [""],
                            "RIS": [total_ris],
                            "Non RIS": [total_non_ris],
                            "Grand Total": [total_grand],
                            "RIS %": [round((total_ris / total_grand) * 100, 2) if total_grand > 0 else 0],
                            "Non RIS %": [round((total_non_ris / total_grand) * 100, 2) if total_grand > 0 else 0]
                        })
                        cluster_brand = pd.concat([cluster_brand, grand_total_row], ignore_index=True)
                        results['cluster_brand'] = cluster_brand
                        
                        # 5. State Cluster-wise RIS
                        state_cluster = pd.pivot_table(
                            ris_df, index="FC State Cluster", columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        if "RIS" not in state_cluster.columns:
                            state_cluster["RIS"] = 0
                        if "Non RIS" not in state_cluster.columns:
                            state_cluster["Non RIS"] = 0
                        state_cluster["Grand Total"] = state_cluster["RIS"] + state_cluster["Non RIS"]
                        state_cluster["RIS %"] = ((state_cluster["RIS"] / state_cluster["Grand Total"]) * 100).round(2)
                        state_cluster["Non RIS %"] = ((state_cluster["Non RIS"] / state_cluster["Grand Total"]) * 100).round(2)
                        # Add Grand Total row
                        grand_total_row = pd.DataFrame({
                            "FC State Cluster": ["Grand Total"],
                            "RIS": [state_cluster["RIS"].sum()],
                            "Non RIS": [state_cluster["Non RIS"].sum()],
                            "Grand Total": [state_cluster["Grand Total"].sum()],
                            "RIS %": [round((state_cluster["RIS"].sum() / state_cluster["Grand Total"].sum()) * 100, 2)],
                            "Non RIS %": [round((state_cluster["Non RIS"].sum() / state_cluster["Grand Total"].sum()) * 100, 2)]
                        })
                        state_cluster = pd.concat([state_cluster, grand_total_row], ignore_index=True)
                        results['state_cluster'] = state_cluster
                        
                        # 6. State-FC pivot WITH GRAND TOTAL
                        state_fc = pd.pivot_table(
                            ris_df, index=["FC State Cluster", "FC Cluster"], columns="RIS Status",
                            values="Shipped Quantity", aggfunc="sum", fill_value=0
                        ).reset_index()
                        if "RIS" not in state_fc.columns:
                            state_fc["RIS"] = 0
                        if "Non RIS" not in state_fc.columns:
                            state_fc["Non RIS"] = 0
                        # Ensure numeric types
                        state_fc["RIS"] = pd.to_numeric(state_fc["RIS"], errors='coerce').fillna(0)
                        state_fc["Non RIS"] = pd.to_numeric(state_fc["Non RIS"], errors='coerce').fillna(0)
                        state_fc["Grand Total"] = state_fc["RIS"] + state_fc["Non RIS"]
                        state_fc["RIS %"] = ((state_fc["RIS"] / state_fc["Grand Total"]) * 100).round(2).fillna(0)
                        state_fc["Non RIS %"] = ((state_fc["Non RIS"] / state_fc["Grand Total"]) * 100).round(2).fillna(0)
                        
                        # Calculate Grand Total from original data
                        total_ris = float(state_fc["RIS"].sum())
                        total_non_ris = float(state_fc["Non RIS"].sum())
                        total_grand = total_ris + total_non_ris
                        
                        # Add Grand Total row
                        grand_total_row = pd.DataFrame({
                            "FC State Cluster": ["Grand Total"],
                            "FC Cluster": [""],
                            "RIS": [total_ris],
                            "Non RIS": [total_non_ris],
                            "Grand Total": [total_grand],
                            "RIS %": [round((total_ris / total_grand) * 100, 2) if total_grand > 0 else 0],
                            "Non RIS %": [round((total_non_ris / total_grand) * 100, 2) if total_grand > 0 else 0]
                        })
                        state_fc = pd.concat([state_fc, grand_total_row], ignore_index=True)
                        results['state_fc'] = state_fc
                        
                        st.session_state.all_results = results
                        
                        # Auto-save all generated reports to MongoDB
                        auto_save_generated_reports(results, MODULE_NAME, tool_name=TOOL_NAME)
                        
                        st.success("✅ Data processed successfully! Switch tabs to view reports.")
                        
                        # Aggressive cleanup
                        gc.collect()
                        
                    except Exception as e:
                        st.error(f"❌ Error processing files: {str(e)}")
                        gc.collect()
            else:
                st.warning("⚠️ Please upload all three files first!")
    
    else:
        # Manager option - Upload RIS Week file and PM file
        st.header("📁 Upload Manager Files")
        st.markdown("Upload the required files:")
        
        ris_week_file = st.file_uploader("Upload RIS Week File", type=['csv', 'xlsx', 'xls'], key='ris_week')
        pm_file = st.file_uploader("Upload PM File", type=['xlsx', 'xls'], key='pm_file')
        
        st.markdown("---")
        
        # Clear cache button
        if st.button("🗑️ Clear Cache", use_container_width=True, key='manager_clear'):
            st.session_state.manager_data = None
            st.session_state.manager_results = {}
            st.session_state.processed_data = None
            st.session_state.all_results = {}
            st.rerun()
        
        if st.button("🔄 Process Manager Data", use_container_width=True, key='manager_process'):
            if ris_week_file and pm_file:
                with st.spinner("Processing Manager data (Extreme Memory Optimization)..."):
                    try:
                        # 1. READ MINIMAL COLUMNS
                        # Read RIS Week file columns first
                        temp_ris = pd.read_csv(ris_week_file, nrows=0) if ris_week_file.name.endswith('.csv') else pd.read_excel(ris_week_file, nrows=0)
                        ris_all_cols = temp_ris.columns.tolist()
                        del temp_ris
                        
                        # Identify columns for usecols
                        target_cols = []
                        for col in ris_all_cols:
                            clow = col.lower().replace(" ", "").replace("_", "")
                            if clow in ['total', 'totalunits', 'totalqty', 'totalquantity', 'totalunit',
                                       'risunits', 'ris', 'risqty', 'risquantity', 'risunit', 'ris_units',
                                       'custcluster', 'cluster', 'customercluster', 'asin', 'brand', 
                                       'merchantbrandname', 'brandname']:
                                target_cols.append(col)
                        
                        # Read RIS Week file with usecols
                        if ris_week_file.name.endswith('.csv'):
                            ris_week_df = pd.read_csv(ris_week_file, usecols=target_cols)
                        else:
                            ris_week_df = pd.read_excel(ris_week_file, usecols=target_cols)
                        
                        # Read PM file minimal
                        pm_cols = ["ASIN", "Brand", "Brand Manager", "Vendor SKU Codes"]
                        pm_df = pd.read_excel(pm_file, usecols=lambda x: x in pm_cols)
                        
                        gc.collect()

                        # 2. CALCULATE NON RIS & OPTIMIZE TYPES
                        total_col = None
                        ris_col = None
                        
                        for col in ris_week_df.columns:
                            col_lower = col.lower().replace(" ", "").replace("_", "")
                            if col_lower in ['total', 'totalunits', 'totalqty', 'totalquantity']:
                                total_col = col
                            if col_lower in ['risunits', 'ris', 'risqty', 'risquantity', 'ris_units']:
                                ris_col = col
                        
                        if total_col and ris_col:
                            ris_week_df[total_col] = pd.to_numeric(ris_week_df[total_col], errors='coerce').fillna(0).astype("int32")
                            ris_week_df[ris_col] = pd.to_numeric(ris_week_df[ris_col], errors='coerce').fillna(0).astype("int32")
                            ris_week_df["Non RIS"] = (ris_week_df[total_col] - ris_week_df[ris_col]).astype("int32")
                        
                        # 3. MAP PRODUCT DATA
                        # Find ASIN column
                        pm_asin_col = next((c for c in pm_df.columns if c.lower() == 'asin'), None)
                        ris_asin_col = next((c for c in ris_week_df.columns if c.lower() == 'asin'), None)
                        
                        if pm_asin_col and ris_asin_col:
                            pm_df[pm_asin_col] = pm_df[pm_asin_col].astype(str).str.strip().str.upper()
                            ris_week_df[ris_asin_col] = ris_week_df[ris_asin_col].astype(str).str.strip().str.upper()
                        
                            # Apply mappings and categorize
                            for target, source in [("Brand", "Brand"), ("Brand Manager", "Brand Manager"), ("Vendor SKU Codes", "Vendor SKU Codes")]:
                                if source in pm_df.columns:
                                    mapping = dict(zip(pm_df[pm_asin_col], pm_df[source]))
                                    ris_week_df[target] = ris_week_df[ris_asin_col].map(mapping).astype("category")
                                    del mapping
                            
                        del pm_df
                        gc.collect()
                        
                        # Convert other objects to string for Arrow
                        for col in ris_week_df.columns:
                            if ris_week_df[col].dtype == 'object':
                                ris_week_df[col] = ris_week_df[col].astype(str)
                        
                        # Store in session state
                        st.session_state.manager_data = ris_week_df
                        
                        # Generate pivot tables for Manager
                        manager_results = {}
                        
                        # Find column names (case-insensitive)
                        ris_units_col = None
                        total_units_col = None
                        cluster_col = None
                        brand_col = None
                        asin_col_for_pivot = ris_asin_col  # Use the already found ASIN column
                        
                        for col in ris_week_df.columns:
                            col_lower = col.lower().replace(" ", "").replace("_", "")
                            if col_lower in ['risunits', 'ris', 'risqty', 'risquantity', 'risunit']:
                                ris_units_col = col
                            if col_lower in ['total', 'totalunits', 'totalqty', 'totalquantity', 'totalunit']:
                                total_units_col = col
                            if col_lower in ['custcluster', 'cluster', 'customercluster']:
                                cluster_col = col
                            if col_lower in ['brand', 'merchantbrandname', 'brandname']:
                                brand_col = col
                            if col_lower == 'asin' and not asin_col_for_pivot:
                                asin_col_for_pivot = col
                        
                        # 1. Brand-wise Pivot
                        if brand_col and ris_units_col and total_units_col and "Non RIS" in ris_week_df.columns:
                            # Convert columns to numeric for aggregation
                            ris_week_df[ris_units_col] = pd.to_numeric(ris_week_df[ris_units_col], errors='coerce').fillna(0)
                            ris_week_df["Non RIS"] = pd.to_numeric(ris_week_df["Non RIS"], errors='coerce').fillna(0)
                            ris_week_df[total_units_col] = pd.to_numeric(ris_week_df[total_units_col], errors='coerce').fillna(0)
                            
                            brand_pivot = ris_week_df.groupby(brand_col).agg({
                                ris_units_col: 'sum',
                                'Non RIS': 'sum',
                                total_units_col: 'sum'
                            }).reset_index()
                            brand_pivot.columns = ["Brand", "RIS Units", "Non RIS", "Total Units"]
                            # Calculate percentages
                            brand_pivot["RIS %"] = ((brand_pivot["RIS Units"] / brand_pivot["Total Units"]) * 100).round(2).fillna(0)
                            brand_pivot["Non RIS %"] = ((brand_pivot["Non RIS"] / brand_pivot["Total Units"]) * 100).round(2).fillna(0)
                            # Add Grand Total
                            total_ris = brand_pivot["RIS Units"].sum()
                            total_non_ris = brand_pivot["Non RIS"].sum()
                            total_units = brand_pivot["Total Units"].sum()
                            grand_total = pd.DataFrame({
                                "Brand": ["Grand Total"],
                                "RIS Units": [total_ris],
                                "Non RIS": [total_non_ris],
                                "Total Units": [total_units],
                                "RIS %": [round((total_ris / total_units) * 100, 2) if total_units > 0 else 0],
                                "Non RIS %": [round((total_non_ris / total_units) * 100, 2) if total_units > 0 else 0]
                            })
                            brand_pivot = pd.concat([brand_pivot, grand_total], ignore_index=True)
                            manager_results['brand_wise'] = brand_pivot
                        
                        # 2. ASIN-wise Pivot
                        if asin_col_for_pivot and ris_units_col and total_units_col and "Non RIS" in ris_week_df.columns:
                            asin_pivot = ris_week_df.groupby(asin_col_for_pivot).agg({
                                ris_units_col: 'sum',
                                'Non RIS': 'sum',
                                total_units_col: 'sum'
                            }).reset_index()
                            asin_pivot.columns = ["ASIN", "RIS Units", "Non RIS", "Total Units"]
                            # Calculate percentages
                            asin_pivot["RIS %"] = ((asin_pivot["RIS Units"] / asin_pivot["Total Units"]) * 100).round(2).fillna(0)
                            asin_pivot["Non RIS %"] = ((asin_pivot["Non RIS"] / asin_pivot["Total Units"]) * 100).round(2).fillna(0)
                            # Add Grand Total
                            total_ris = asin_pivot["RIS Units"].sum()
                            total_non_ris = asin_pivot["Non RIS"].sum()
                            total_units = asin_pivot["Total Units"].sum()
                            grand_total = pd.DataFrame({
                                "ASIN": ["Grand Total"],
                                "RIS Units": [total_ris],
                                "Non RIS": [total_non_ris],
                                "Total Units": [total_units],
                                "RIS %": [round((total_ris / total_units) * 100, 2) if total_units > 0 else 0],
                                "Non RIS %": [round((total_non_ris / total_units) * 100, 2) if total_units > 0 else 0]
                            })
                            asin_pivot = pd.concat([asin_pivot, grand_total], ignore_index=True)
                            manager_results['asin_wise'] = asin_pivot
                        
                        # 3. Cluster-wise Pivot
                        if cluster_col and ris_units_col and total_units_col and "Non RIS" in ris_week_df.columns:
                            cluster_pivot = ris_week_df.groupby(cluster_col).agg({
                                ris_units_col: 'sum',
                                'Non RIS': 'sum',
                                total_units_col: 'sum'
                            }).reset_index()
                            cluster_pivot.columns = ["Cluster", "RIS Units", "Non RIS", "Total Units"]
                            # Calculate percentages
                            cluster_pivot["RIS %"] = ((cluster_pivot["RIS Units"] / cluster_pivot["Total Units"]) * 100).round(2).fillna(0)
                            cluster_pivot["Non RIS %"] = ((cluster_pivot["Non RIS"] / cluster_pivot["Total Units"]) * 100).round(2).fillna(0)
                            # Add Grand Total
                            total_ris = cluster_pivot["RIS Units"].sum()
                            total_non_ris = cluster_pivot["Non RIS"].sum()
                            total_units = cluster_pivot["Total Units"].sum()
                            grand_total = pd.DataFrame({
                                "Cluster": ["Grand Total"],
                                "RIS Units": [total_ris],
                                "Non RIS": [total_non_ris],
                                "Total Units": [total_units],
                                "RIS %": [round((total_ris / total_units) * 100, 2) if total_units > 0 else 0],
                                "Non RIS %": [round((total_non_ris / total_units) * 100, 2) if total_units > 0 else 0]
                            })
                            cluster_pivot = pd.concat([cluster_pivot, grand_total], ignore_index=True)
                            manager_results['cluster_wise'] = cluster_pivot
                        
                        # 4. Cluster-ASIN Pivot
                        if cluster_col and asin_col_for_pivot and ris_units_col and total_units_col and "Non RIS" in ris_week_df.columns:
                            cluster_asin_pivot = ris_week_df.groupby([cluster_col, asin_col_for_pivot]).agg({
                                ris_units_col: 'sum',
                                'Non RIS': 'sum',
                                total_units_col: 'sum'
                            }).reset_index()
                            cluster_asin_pivot.columns = ["Cluster", "ASIN", "RIS Units", "Non RIS", "Total Units"]
                            # Calculate percentages
                            cluster_asin_pivot["RIS %"] = ((cluster_asin_pivot["RIS Units"] / cluster_asin_pivot["Total Units"]) * 100).round(2).fillna(0)
                            cluster_asin_pivot["Non RIS %"] = ((cluster_asin_pivot["Non RIS"] / cluster_asin_pivot["Total Units"]) * 100).round(2).fillna(0)
                            # Add Grand Total
                            total_ris = cluster_asin_pivot["RIS Units"].sum()
                            total_non_ris = cluster_asin_pivot["Non RIS"].sum()
                            total_units = cluster_asin_pivot["Total Units"].sum()
                            grand_total = pd.DataFrame({
                                "Cluster": ["Grand Total"],
                                "ASIN": [""],
                                "RIS Units": [total_ris],
                                "Non RIS": [total_non_ris],
                                "Total Units": [total_units],
                                "RIS %": [round((total_ris / total_units) * 100, 2) if total_units > 0 else 0],
                                "Non RIS %": [round((total_non_ris / total_units) * 100, 2) if total_units > 0 else 0]
                            })
                            cluster_asin_pivot = pd.concat([cluster_asin_pivot, grand_total], ignore_index=True)
                            manager_results['cluster_asin'] = cluster_asin_pivot
                        
                        st.session_state.manager_results = manager_results
                        
                        # Auto-save all generated reports to MongoDB
                        auto_save_generated_reports(manager_results, MODULE_NAME, tool_name=TOOL_NAME)
                        
                        st.success("✅ Manager data processed successfully! Switch tabs to view reports.")
                        
                        # Aggressive cleanup
                        gc.collect()
                        
                    except Exception as e:
                        st.error(f"❌ Error processing files: {str(e)}")
                        gc.collect()
            else:
                st.warning("⚠️ Please upload both RIS Week file and PM file!")

# Main content area
if st.session_state.processed_data is not None:
    tabs = st.tabs([
        "📋 Processed Data",
        "🏷️ Brand-wise RIS",
        "🔖 ASIN-wise RIS",
        "🏢 Cluster-wise RIS",
        "📊 Cluster-Brand Analysis",
        "🗺️ State Cluster Analysis",
        "📍 State-FC Analysis"
    ])
    
    # Tab 1: Processed Data
    with tabs[0]:
        st.header("Processed RIS Data")
        df = st.session_state.processed_data
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Records", f"{len(df):,}")
        with col2:
            ris_count = len(df[df["RIS Status"] == "RIS"])
            st.metric("RIS Orders", f"{ris_count:,}")
        with col3:
            non_ris_count = len(df[df["RIS Status"] == "Non RIS"])
            st.metric("Non-RIS Orders", f"{non_ris_count:,}")
        with col4:
            ris_percent = (ris_count / len(df) * 100) if len(df) > 0 else 0
            st.metric("RIS %", f"{ris_percent:.2f}%")
        
        st.markdown("---")
        st.dataframe(df, width="stretch", height=400)
        
        download_module_report(
            df=df,
            module_name=MODULE_NAME,
            report_name="Processed RIS Data",
            button_label="📥 Download Processed Data (Excel)",
            key="dl_processed_ris",
            tool_name=TOOL_NAME
        )
    
    # Tab 2: Brand-wise RIS
    with tabs[1]:
        st.header("Brand-wise RIS Analysis")
        if 'brand_wise' in st.session_state.all_results:
            df = st.session_state.all_results['brand_wise']
            st.dataframe(df, width="stretch", height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="Brand-wise RIS Analysis",
                button_label="📥 Download Brand-wise Analysis (Excel)",
                key="dl_brand_wise_ris",
                tool_name=TOOL_NAME
            )
    
    # Tab 3: ASIN-wise RIS
    with tabs[2]:
        st.header("ASIN-wise RIS Analysis")
        if 'asin_wise' in st.session_state.all_results:
            df = st.session_state.all_results['asin_wise']
            st.dataframe(df, width="stretch", height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="ASIN-wise RIS Analysis",
                button_label="📥 Download ASIN-wise Analysis (Excel)",
                key="dl_asin_wise_ris",
                tool_name=TOOL_NAME
            )
    
    # Tab 4: Cluster-wise RIS
    with tabs[3]:
        st.header("Cluster-wise RIS Analysis")
        if 'cluster_wise' in st.session_state.all_results:
            df = st.session_state.all_results['cluster_wise']
            st.dataframe(df, width="stretch", height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="Cluster-wise RIS Analysis",
                button_label="📥 Download Cluster-wise Analysis (Excel)",
                key="dl_cluster_wise_ris",
                tool_name=TOOL_NAME
            )
    
    # Tab 5: Cluster-Brand Analysis
    with tabs[4]:
        st.header("Cluster-Brand RIS Analysis")
        if 'cluster_brand' in st.session_state.all_results:
            df = st.session_state.all_results['cluster_brand']
            st.dataframe(df, width="stretch", height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="Cluster-Brand RIS Analysis",
                button_label="📥 Download Cluster-Brand Analysis (Excel)",
                key="dl_cluster_brand_ris",
                tool_name=TOOL_NAME
            )
    
    # Tab 6: State Cluster Analysis
    with tabs[5]:
        st.header("State Cluster RIS Analysis")
        if 'state_cluster' in st.session_state.all_results:
            df = st.session_state.all_results['state_cluster']
            st.dataframe(df, width="stretch", height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="State Cluster RIS Analysis",
                button_label="📥 Download State Cluster Analysis (Excel)",
                key="dl_state_cluster_ris",
                tool_name=TOOL_NAME
            )
    
    # Tab 7: State-FC Analysis
    with tabs[6]:
        st.header("State-FC RIS Analysis")
        if 'state_fc' in st.session_state.all_results:
            df = st.session_state.all_results['state_fc']
            st.dataframe(df, use_container_width=True, height=400)
            download_module_report(
                df=df,
                module_name=MODULE_NAME,
                report_name="State-FC RIS Analysis",
                button_label="📥 Download State-FC Analysis (Excel)",
                key="dl_state_fc_ris",
                tool_name=TOOL_NAME
            )


elif st.session_state.manager_data is not None:
    # Manager Data Display with Tabs
    manager_tabs = st.tabs([
        "📋 Processed Data",
        "🏷️ Brand-wise",
        "🔖 ASIN-wise",
        "🏢 Cluster-wise",
        "📊 Cluster-ASIN"
    ])
    
    # Tab 1: Processed Data
    with manager_tabs[0]:
        st.header("📊 Manager RIS Week Data")
        df = st.session_state.manager_data
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Records", f"{len(df):,}")
        with col2:
            if "Non RIS" in df.columns:
                non_ris_total = pd.to_numeric(df["Non RIS"], errors='coerce').sum()
                st.metric("Total Non RIS", f"{non_ris_total:,.0f}")
        with col3:
            # Find the RIS column
            ris_col = None
            for col in df.columns:
                col_lower = col.lower().replace(" ", "").replace("_", "")
                if col_lower in ['risunits', 'ris', 'risqty', 'risquantity', 'ris_units']:
                    ris_col = col
                    break
            if ris_col:
                ris_total = pd.to_numeric(df[ris_col], errors='coerce').sum()
                st.metric("Total RIS", f"{ris_total:,.0f}")
        
        st.markdown("---")
        st.dataframe(df, width="stretch", height=500)
        
        st.download_button(
            label="📥 Download Manager RIS Data (Excel)",
            data=to_excel(df),
            file_name="manager_ris_week_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # Tab 2: Brand-wise Pivot
    with manager_tabs[1]:
        st.header("🏷️ Brand-wise Analysis")
        if 'brand_wise' in st.session_state.manager_results:
            df = st.session_state.manager_results['brand_wise']
            st.dataframe(df, width="stretch", height=400)
            st.download_button(
                label="📥 Download Brand-wise Analysis (Excel)",
                data=to_excel(df),
                file_name="manager_brand_wise.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("⚠️ Brand-wise pivot not available. Ensure Brand column is mapped from PM file.")
    
    # Tab 3: ASIN-wise Pivot
    with manager_tabs[2]:
        st.header("🔖 ASIN-wise Analysis")
        if 'asin_wise' in st.session_state.manager_results:
            df = st.session_state.manager_results['asin_wise']
            st.dataframe(df, width="stretch", height=400)
            st.download_button(
                label="📥 Download ASIN-wise Analysis (Excel)",
                data=to_excel(df),
                file_name="manager_asin_wise.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("⚠️ ASIN-wise pivot not available. Ensure ASIN column exists in RIS Week file.")
    
    # Tab 4: Cluster-wise Pivot
    with manager_tabs[3]:
        st.header("🏢 Cluster-wise Analysis")
        if 'cluster_wise' in st.session_state.manager_results:
            df = st.session_state.manager_results['cluster_wise']
            st.dataframe(df, width="stretch", height=400)
            st.download_button(
                label="📥 Download Cluster-wise Analysis (Excel)",
                data=to_excel(df),
                file_name="manager_cluster_wise.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("⚠️ Cluster-wise pivot not available. Ensure cust_cluster column exists in RIS Week file.")
    
    # Tab 5: Cluster-ASIN Pivot
    with manager_tabs[4]:
        st.header("📊 Cluster-ASIN Analysis")
        if 'cluster_asin' in st.session_state.manager_results:
            df = st.session_state.manager_results['cluster_asin']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download Cluster-ASIN Analysis (Excel)",
                data=to_excel(df),
                file_name="manager_cluster_asin.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("⚠️ Cluster-ASIN pivot not available. Ensure both cust_cluster and ASIN columns exist.")

else:
    # Welcome screen
    st.info("👋 Welcome! Please upload the required files using the sidebar to begin analysis.")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        ### 📄 RIS.csv
        - Main shipment data
        - Contains order details
        - Shipping information
        """)
    
    with col2:
        st.markdown("""
        ### 🗂️ State FC Cluster.xlsx
        - FC and cluster mapping
        - State assignments
        - Cluster definitions
        """)
    
    with col3:
        st.markdown("""
        ### 📦 PM.xlsx
        - Product master data
        - Brand information
        - ASIN mappings
        """)
    
    st.markdown("---")
    st.markdown("""
    ### 📊 Analysis Features:
    
    **Amazon Manager:**
    - Processed Data: Complete dataset with RIS status calculations
    - Brand-wise RIS: Performance metrics by brand
    - ASIN-wise RIS: Product-level analysis
    - Cluster-wise RIS: FC cluster performance
    - Cluster-Brand Analysis: Combined cluster and brand insights
    - State Cluster Analysis: State-level cluster metrics
    - State-FC Analysis: Detailed state and FC mapping
    
    **Manager:**
    - RIS Week Data with Non RIS calculations
    - Brand, Brand Manager, Vendor SKU mappings from PM file
    
    All reports can be downloaded as Excel files! 📥

    """)
