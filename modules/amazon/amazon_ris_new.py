import streamlit as st
import pandas as pd
import numpy as np
import re
from io import BytesIO

from mongo_utils import save_reconciliation_report
from ui_utils import apply_professional_style, get_download_filename, render_header

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

# Title
# Title
render_header("RIS Analysis Dashboard")
st.markdown("---")

# Initialize session state
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'all_results' not in st.session_state:
    st.session_state.all_results = {}

# Sidebar for file upload
with st.sidebar:
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
        st.rerun()
    
    if st.button("🔄 Process Data", use_container_width=True):
        if ris_file and state_fc_file and purchase_file:
            with st.spinner("Processing data..."):
                try:
                    # Read files
                    ris_df = pd.read_csv(ris_file)
                    state_fc_df = pd.read_excel(state_fc_file, sheet_name="Sheet2")
                    purchase_df = pd.read_excel(purchase_file)
                    
                    # Rename columns in state_fc_df
                    state_fc_df = state_fc_df.rename(columns={
                        state_fc_df.columns[0]: "FC",
                        state_fc_df.columns[1]: "FC State",
                        state_fc_df.columns[2]: "FC Cluster",
                        state_fc_df.columns[3]: "FC State Cluster"
                    })
                    
                    # Create mappings
                    fc_state_map = dict(zip(state_fc_df["FC"], state_fc_df["FC State"]))
                    fc_cluster_map = dict(zip(state_fc_df["FC"], state_fc_df["FC Cluster"]))
                    fc_state_cluster_map = dict(zip(state_fc_df["FC"], state_fc_df["FC State Cluster"]))
                    
                    # Map FC data to RIS
                    ris_df["FC State"] = ris_df["FC"].map(fc_state_map)
                    ris_df["FC Cluster"] = ris_df["FC"].map(fc_cluster_map)
                    ris_df["FC State Cluster"] = ris_df["FC"].map(fc_state_cluster_map)
                    
                    # Normalize SKUs
                    purchase_df["Amazon Sku Name"] = purchase_df["Amazon Sku Name"].apply(normalize_sku)
                    ris_df["Merchant SKU"] = ris_df["Merchant SKU"].apply(normalize_sku)
                    
                    # Create product mappings
                    asin_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["ASIN"]))
                    vendor_sku_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Vendor SKU Codes"]))
                    brand_manager_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Brand Manager"]))
                    brand_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Brand"]))
                    product_name_map = dict(zip(purchase_df["Amazon Sku Name"], purchase_df["Product Name"]))
                    
                    # Map product data to RIS
                    ris_df["ASIN"] = ris_df["Merchant SKU"].map(asin_map)
                    ris_df["Vendor SKU"] = ris_df["Merchant SKU"].map(vendor_sku_map)
                    ris_df["Brand"] = ris_df["Merchant SKU"].map(brand_map)
                    ris_df["Brand Manager"] = ris_df["Merchant SKU"].map(brand_manager_map)
                    ris_df["Product Name"] = ris_df["Merchant SKU"].map(product_name_map)
                    
                    # Normalize shipping state
                    ris_df["Shipping State Corrected"] = ris_df.apply(
                        lambda x: normalize_shipping_state(x["Shipping State"], x["FC State"], STATE_RULES),
                        axis=1
                    )
                    
                    # Calculate RIS Status
                    ris_df["RIS Status"] = np.where(
                        ris_df["Shipping State Corrected"].str.upper().str.strip() == 
                        ris_df["FC State"].str.upper().str.strip(),
                        "RIS",
                        "Non RIS"
                    )
                    
                    # Convert all object columns to string to avoid PyArrow serialization errors
                    for col in ris_df.columns:
                        if ris_df[col].dtype == 'object':
                            ris_df[col] = ris_df[col].astype(str)
                    
                    # Store processed data
                    st.session_state.processed_data = ris_df
                    
                    # Save to MongoDB
                    try:
                         save_reconciliation_report(
                            collection_name="amazon_ris",
                            invoice_no=f"RIS_{pd.Timestamp.now().strftime('%Y%m%d%H%M')}",
                            summary_data=pd.DataFrame([{"Total Records": len(ris_df)}]),
                            line_items_data=ris_df,
                            metadata={"type": "ris_analysis"}
                        )
                    except Exception as e:
                        pass
                    
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
                    brand_wise["RIS %"] = ((brand_wise["RIS"] / brand_wise["Grand Total"]) * 100).round(2)
                    brand_wise["Non RIS %"] = ((brand_wise["Non RIS"] / brand_wise["Grand Total"]) * 100).round(2)
                    # Add Grand Total row
                    grand_total_row = pd.DataFrame({
                        "Brand": ["Grand Total"],
                        "RIS": [brand_wise["RIS"].sum()],
                        "Non RIS": [brand_wise["Non RIS"].sum()],
                        "Grand Total": [brand_wise["Grand Total"].sum()],
                        "RIS %": [round((brand_wise["RIS"].sum() / brand_wise["Grand Total"].sum()) * 100, 2)],
                        "Non RIS %": [round((brand_wise["Non RIS"].sum() / brand_wise["Grand Total"].sum()) * 100, 2)]
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
                    st.success("✅ Data processed successfully!")
                    
                except Exception as e:
                    st.error(f"❌ Error processing files: {str(e)}")
        else:
            st.warning("⚠️ Please upload all three files first!")

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
        st.dataframe(df, use_container_width=True, height=400)
        
        st.download_button(
            label="📥 Download Processed Data (Excel)",
            data=to_excel(df),
            file_name=get_download_filename("processed_ris_data"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # Tab 2: Brand-wise RIS
    with tabs[1]:
        st.header("Brand-wise RIS Analysis")
        if 'brand_wise' in st.session_state.all_results:
            df = st.session_state.all_results['brand_wise']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download Brand-wise Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("brand_wise_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # Tab 3: ASIN-wise RIS
    with tabs[2]:
        st.header("ASIN-wise RIS Analysis")
        if 'asin_wise' in st.session_state.all_results:
            df = st.session_state.all_results['asin_wise']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download ASIN-wise Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("asin_wise_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # Tab 4: Cluster-wise RIS
    with tabs[3]:
        st.header("Cluster-wise RIS Analysis")
        if 'cluster_wise' in st.session_state.all_results:
            df = st.session_state.all_results['cluster_wise']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download Cluster-wise Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("cluster_wise_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # Tab 5: Cluster-Brand Analysis
    with tabs[4]:
        st.header("Cluster-Brand RIS Analysis")
        if 'cluster_brand' in st.session_state.all_results:
            df = st.session_state.all_results['cluster_brand']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download Cluster-Brand Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("cluster_brand_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # Tab 6: State Cluster Analysis
    with tabs[5]:
        st.header("State Cluster RIS Analysis")
        if 'state_cluster' in st.session_state.all_results:
            df = st.session_state.all_results['state_cluster']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download State Cluster Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("state_cluster_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # Tab 7: State-FC Analysis
    with tabs[6]:
        st.header("State-FC RIS Analysis")
        if 'state_fc' in st.session_state.all_results:
            df = st.session_state.all_results['state_fc']
            st.dataframe(df, use_container_width=True, height=400)
            st.download_button(
                label="📥 Download State-FC Analysis (Excel)",
                data=to_excel(df),
                file_name=get_download_filename("state_fc_ris"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

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
    - **Processed Data**: Complete dataset with RIS status calculations
    - **Brand-wise RIS**: Performance metrics by brand
    - **ASIN-wise RIS**: Product-level analysis
    - **Cluster-wise RIS**: FC cluster performance
    - **Cluster-Brand Analysis**: Combined cluster and brand insights (with Grand Total)
    - **State Cluster Analysis**: State-level cluster metrics
    - **State-FC Analysis**: Detailed state and FC mapping (with Grand Total)
    
    All reports can be downloaded as Excel files! 📥

    """)
