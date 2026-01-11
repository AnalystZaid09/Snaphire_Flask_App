# old code in main.py in folder use that if you need 
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import zipfile
import warnings
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "leakagereconciliation"

# Suppress FutureWarnings
warnings.filterwarnings('ignore', category=FutureWarning)

# Page configuration
st.set_page_config(
    page_title="Support Dyson Monthly",
    page_icon="🧮",
    layout="wide"
)
apply_professional_style()

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1e40af 0%, #4f46e5 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .main-header h1 {
        color: white;
        margin: 0;
    }
    .main-header p {
        color: #dbeafe;
        margin: 0.5rem 0 0 0;
    }
    .metric-card {
        background: #f0f9ff;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #2563eb;
    }
    .success-box {
        background: #dcfce7;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #16a34a;
    }
    .info-box {
        background: #dbeafe;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #2563eb;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 12px 24px;
        background-color: #f3f4f6;
        border-radius: 8px 8px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2563eb;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# Header
render_header("Support Dyson Monthly", "Calculate promotional support for B2B & B2C channels")


def convert_df_to_csv(df):
    """Convert dataframe to CSV for download"""
    return df.to_csv(index=False).encode('utf-8')


def format_currency(value):
    """Format number as Indian currency"""
    if pd.isna(value):
        return "-"
    return f"₹{value:,.0f}"


def process_data(zip_files, pm_file, promo_file):
    """Process B2B/B2C data and calculate support"""
    try:
        # ---------- READ FILES ----------
        all_dfs = []
        for zip_file in zip_files:
            with zipfile.ZipFile(zip_file) as z:
                csv_files = [name for name in z.namelist() if name.endswith('.csv')]

                for csv_name in csv_files:
                    with z.open(csv_name) as f:
                        temp_df = pd.read_csv(f)
                        all_dfs.append(temp_df)

        df = pd.concat(all_dfs, ignore_index=True)

        PM = pd.read_excel(pm_file)
        Promo = pd.read_excel(promo_file)
        
        # Clean and prepare data
        df["Asin"] = df["Asin"].astype(str).str.strip()
        PM["ASIN"] = PM["ASIN"].astype(str).str.strip()
        Promo["ASIN"] = Promo["ASIN"].astype(str).str.strip()
        
        # ---------- BRAND MAP ----------
        brand_map = PM.groupby("ASIN", as_index=True)["Brand"].first()
        df["Brand"] = df["Asin"].map(brand_map)
        
        # Move Brand column after Sku if Sku exists
        cols = list(df.columns)
        if "Sku" in cols:
            sku_idx = cols.index("Sku")
            cols.remove("Brand")
            cols.insert(sku_idx + 1, "Brand")
            df = df[cols]
        
        # ---------- DYSON ONLY ----------
        dyson_df = df[df["Brand"].notna() & (df["Brand"].astype(str).str.strip().str.upper() == "DYSON")].copy()
        
        # ---------- ORDER STATUS ----------
        cancel_orders = set(
            dyson_df[dyson_df["Transaction Type"].astype(str).str.strip().str.upper() == "CANCEL"]["Order Id"]
        )
        
        dyson_df["Order Status"] = np.where(
            dyson_df["Order Id"].isin(cancel_orders),
            "Cancel",
            dyson_df["Transaction Type"]
        )
        
        # Move Order Status after Order Id
        cols = list(dyson_df.columns)
        order_idx = cols.index("Order Id")
        cols.remove("Order Status")
        cols.insert(order_idx + 1, "Order Status")
        dyson_df = dyson_df[cols]
        
        # ---------- PROCESSED DATA (BEFORE PIVOT) ----------
        processed_df = dyson_df.copy()
        
        # ---------- PIVOT ----------
        pivot = pd.pivot_table(
            dyson_df,
            index="Asin",
            columns="Order Status",
            values="Quantity",
            aggfunc="sum",
            fill_value=0,
            margins=False
        ).reset_index()
        
        # ---------- NET SALE ----------
        pivot["Net Sale / Actual Shipment"] = (
            pivot.get("Shipment", 0) - pivot.get("Refund", 0)
        )
        
        # ---------- PROMO MAP ----------
        pivot["SKU CODE"] = pivot["Asin"].map(Promo.groupby("ASIN")["SKU Code"].first())
        pivot["SSP"] = pivot["Asin"].map(Promo.groupby("ASIN")["SSP"].first())
        pivot["Cons Promo"] = pivot["Asin"].map(Promo.groupby("ASIN")["Cons Promo"].first())
        pivot["Margin %"] = pivot["Asin"].map(Promo.groupby("ASIN")["Margin"].first()) * 100
        
        # ---------- SUPPORT ----------
        pivot["Support"] = (
            (pivot["SSP"] - pivot["Cons Promo"])
            * (1 - pivot["Margin %"] / 100)
        )
        
        pivot["SUPPORT AS PER NET SALE"] = (
            pivot["Support"].fillna(0)
            * pivot["Net Sale / Actual Shipment"].fillna(0)
        )
        
        # ---------- CLEAN NUMERIC ----------
        pivot.replace("", np.nan, inplace=True)
        
        # Get all numeric columns (excluding Asin and SKU CODE)
        exclude_cols = ["Asin", "SKU CODE"]
        numeric_cols = [col for col in pivot.columns if col not in exclude_cols]
        
        for col in numeric_cols:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce").fillna(0)
        
        # ---------- GRAND TOTAL ----------
        grand_total = {}
        for col in pivot.columns:
            if col == "Asin":
                grand_total[col] = "Grand Total"
            elif col == "SKU CODE":
                grand_total[col] = ""
            elif col in numeric_cols:
                grand_total[col] = pivot[col].sum()
            else:
                grand_total[col] = 0
        
        pivot = pd.concat([pivot, pd.DataFrame([grand_total])], ignore_index=True)
        
        # Convert SKU CODE to string to avoid Arrow serialization issues
        pivot["SKU CODE"] = pivot["SKU CODE"].astype(str)
        
        return pivot, processed_df
        
    except Exception as e:
        st.error(f"Error processing data: {str(e)}")
        return None, None


# Main App
tab1, tab2, tab3 = st.tabs(["📊 B2B Analysis", "📈 B2C Analysis", "🔄 Combined Analysis"])


def render_tab(tab, key):
    """Render B2B, B2C or Combined tab"""
    with tab:
        st.markdown(f"### {key} Support Calculation")
        
        st.info("📁 Please upload required files below:")
        
        if key == "Combined":
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**1️⃣ B2B Report ZIP**")
                b2b_zip = st.file_uploader(
                    "Choose B2B ZIP files",
                    type=['zip'],
                    accept_multiple_files=True,
                    key='combined_b2b_zip'
                )
            with col2:
                st.markdown("**2️⃣ B2C Report ZIP**")
                b2c_zip = st.file_uploader(
                    "Choose B2C ZIP files",
                    type=['zip'],
                    accept_multiple_files=True,
                    key='combined_b2c_zip'
                )
            
            col_pm, col_promo = st.columns(2)
            with col_pm:
                st.markdown("**3️⃣ PM File**")
                pm_file = st.file_uploader("Choose PM Excel file", type=['xlsx', 'xls'], key='combined_pm')
            with col_promo:
                st.markdown("**4️⃣ Dyson Promo**")
                promo_file = st.file_uploader("Choose Dyson Promo file", type=['xlsx', 'xls'], key='combined_promo')
            
            if st.button("🔄 Calculate Combined Support", type="primary", use_container_width=True):
                if (b2b_zip or b2c_zip) and pm_file and promo_file:
                    all_zips = (b2b_zip if b2b_zip else []) + (b2c_zip if b2c_zip else [])
                    with st.spinner("Processing combined data..."):
                        pivot, processed = process_data(all_zips, pm_file, promo_file)
                        if pivot is not None:
                            st.session_state[f'{key}_pivot'] = pivot
                            st.session_state[f'{key}_processed'] = processed
                            st.success("✅ Combined data processed successfully!")
                else:
                    st.warning("⚠️ Please upload at least one report ZIP and both PM/Promo files.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**1️⃣ Report ZIP**")
                zip_files = st.file_uploader(
                    f"Choose {key} ZIP files",
                    type=['zip'],
                    accept_multiple_files=True,
                    key=f'{key}_zip'
                )
            with col2:
                st.markdown("**2️⃣ PM File**")
                pm_file = st.file_uploader("Choose PM Excel file", type=['xlsx', 'xls'], key=f'{key}_pm')
            with col3:
                st.markdown("**3️⃣ Dyson Promo**")
                promo_file = st.file_uploader("Choose Dyson Promo file", type=['xlsx', 'xls'], key=f'{key}_promo')
            
            if st.button(f"🔄 Calculate {key} Support", type="primary", use_container_width=True):
                if zip_files and pm_file and promo_file:
                    with st.spinner(f"Processing {key} data..."):
                        pivot, processed = process_data(zip_files, pm_file, promo_file)
                        if pivot is not None:
                            st.session_state[f'{key}_pivot'] = pivot
                            st.session_state[f'{key}_processed'] = processed
                            st.success(f"✅ {key} data processed successfully!")
                else:
                    st.warning("⚠️ Please upload all three files to proceed.")
        
        # -------- PROCESSED DATA --------
        if f'{key}_processed' in st.session_state:
            st.markdown("---")
            st.markdown("### 🧾 Processed Dyson Data (Before Pivot)")
            st.dataframe(
                st.session_state[f'{key}_processed'],
                height=350,
                use_container_width=True
            )
            
            download_module_report(
                df=st.session_state[f'{key}_processed'],
                module_name=MODULE_NAME,
                report_name=f"{key} Processed Data (Before Pivot)",
                button_label="📥 Download Processed Data (Before Pivot)",
                key=f"dyson_processed_{key.lower()}"
            )
            st.markdown("---")
        
        # -------- FINAL RESULT --------
        if f'{key}_pivot' in st.session_state:
            result = st.session_state[f'{key}_pivot']
            
            # Key Metrics
            grand_total = result[result['Asin'] == 'Grand Total'].iloc[0]
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Total Shipments", f"{int(grand_total.get('Shipment', 0)):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Net Sales", f"{int(grand_total.get('Net Sale / Actual Shipment', 0)):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                metric_label = "Total Cancels" if key == "B2B" else "Total Refunds"
                metric_value = grand_total.get('Cancel', 0) if key == "B2B" else grand_total.get('Refund', 0)
                st.metric(metric_label, f"{int(metric_value):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                support_total = grand_total.get('SUPPORT AS PER NET SALE', 0)
                st.metric("Total Support", format_currency(support_total))
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Data table
            st.markdown("### 📊 Final Support Calculation")
            
            # Format numeric columns for display
            display_df = result.copy()
            numeric_cols = ['SSP', 'Cons Promo', 'Support', 'SUPPORT AS PER NET SALE']
            for col in numeric_cols:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: format_currency(x) if pd.notna(x) else '-')
            
            # Highlight Grand Total row
            def highlight_grand_total(row):
                if row['Asin'] == 'Grand Total':
                    return ['background-color: #dbeafe; font-weight: bold'] * len(row)
                return [''] * len(row)
            
            st.dataframe(
                display_df.style.apply(highlight_grand_total, axis=1),
                use_container_width=True,
                height=400
            )
            
            # Download button
            download_module_report(
                df=result,
                module_name=MODULE_NAME,
                report_name=f"{key} Final Support Analysis",
                button_label=f"📥 Download {key} Final Results",
                key=f"dyson_final_{key.lower()}"
            )


# Render tabs
render_tab(tab1, "B2B")
render_tab(tab2, "B2C")
render_tab(tab3, "Combined")

# Footer with instructions
st.markdown("---")
st.markdown("### 📖 How to Use This Application")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    **Steps:**
    1. Select either **B2B** or **B2C** tab
    2. Upload the report ZIP file
    3. Upload the PM Excel file
    4. Upload the Dyson Promo Excel file (Dyson Promo file header should be in same format if there is error while uploading file please check header of Dyson Promo file)
    5. Click the **Calculate** button
    6. View processed data (before pivot) and final results
    7. Download CSV files as needed
    """)

with col2:
    st.markdown("""
    **Required Files:**
    - **B2B/B2C Report**: ZIP file with CSV data
    - **PM.xlsx**: Product Master file
    - **PromoCN Email.xlsx**: Dyson Promo data
    
    **Key Calculations:**
    - **Net Sale** = Shipment - Refund
    - **Support** = (SSP - Cons Promo) × (1 - Margin%)
    - **Support Total** = Support × Net Sale
    """)

st.markdown('<div class="info-box">', unsafe_allow_html=True)
st.info("💡 **Tip:** Make sure your files are in the correct format (ZIP for reports, XLSX for promo data) before uploading.")
st.markdown('</div>', unsafe_allow_html=True)
