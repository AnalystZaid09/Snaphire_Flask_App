import streamlit as st
import pandas as pd
import zipfile
import io
from datetime import datetime
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "leakagereconciliation"

# ==============================
# Page configuration
# ==============================
st.set_page_config(
    page_title="Amazon Support NCEMI Analysis Tool",
    page_icon="📊",
    layout="wide"
)
apply_professional_style()

# ==============================
# Custom CSS
# ==============================
st.markdown("""
<style>
.main { background-color: #F8FAFC; }

.upload-card {
    background: white;
    padding: 20px;
    border-radius: 14px;
    border: 1px solid #E5E7EB;
}

.metric-box {
    background: white;
    padding: 22px;
    border-radius: 16px;
    border: 1px solid #E5E7EB;
    text-align: center;
}

.metric-value { font-size: 30px; font-weight: 700; }
.metric-label { color: #6B7280; font-size: 14px; }

.info-box {
    background: #EFF6FF;
    color: #1E40AF;
    padding: 14px 18px;
    border-radius: 12px;
    border: 1px solid #BFDBFE;
    margin-bottom: 10px;
}

.success-box {
    background: #ECFDF5;
    color: #065F46;
    padding: 14px 18px;
    border-radius: 12px;
    border: 1px solid #A7F3D0;
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# Helpers
# ==============================
def normalize_sku(val):
    if pd.isna(val):
        return None
    val = str(val).strip()
    if val.endswith(".0"):
        val = val[:-2]
    return val

def make_arrow_safe(df):
    df = df.copy().reset_index(drop=True)
    for col in df.columns:
        df[col] = df[col].astype(str)
    return df

# ==============================
# Cached Loaders
# ==============================
@st.cache_data
def load_payment_csv(file, skiprows=11):
    return pd.read_csv(file, skiprows=skiprows)

@st.cache_data
def load_excel_file(file):
    return pd.read_excel(file)

@st.cache_data
def load_zip_csv(file):
    with zipfile.ZipFile(file) as z:
        csv_file = [f for f in z.namelist() if f.endswith(".csv")][0]
        with z.open(csv_file) as f:
            return pd.read_csv(f)

# ==============================
# Processing Functions
# ==============================
def process_payment_data(payment_df):
    cols = ["other transaction fees", "other", "total"]
    payment_df[cols] = payment_df[cols].replace({",": ""}, regex=True).apply(
        pd.to_numeric, errors="coerce"
    )

    df = payment_df[payment_df["type"] == "Order"].copy()
    df["product sales"] = pd.to_numeric(df["product sales"], errors="coerce")
    df = df[df["product sales"] == 0]

    df["Sku"] = df["Sku"].apply(normalize_sku)
    df["order id"] = df["order id"].apply(normalize_sku)

    df = df[df["Sku"].isna() | (df["Sku"] == "")]
    return df.reset_index(drop=True)

def fill_sku_from_report(payment_order, report_df, order_col_idx=4, sku_col_idx=13):
    order_col = report_df.columns[order_col_idx]
    sku_col = report_df.columns[sku_col_idx]

    report_df[order_col] = report_df[order_col].apply(normalize_sku)
    report_df[sku_col] = report_df[sku_col].apply(normalize_sku)

    lookup = (
        report_df.dropna(subset=[order_col])
        .drop_duplicates(order_col)
        .set_index(order_col)[sku_col]
        .to_dict()
    )

    mask = payment_order["Sku"].isna()
    payment_order.loc[mask, "Sku"] = payment_order.loc[mask, "order id"].map(lookup)
    return payment_order

def add_brand_info(payment_order, pm_df):
    sku_key = pm_df.columns[2]
    pm_df[sku_key] = pm_df[sku_key].apply(normalize_sku)
    payment_order["Sku"] = payment_order["Sku"].apply(normalize_sku)

    pm_unique = pm_df.drop_duplicates(subset=sku_key)

    payment_order["Brand"] = payment_order["Sku"].map(pm_unique.set_index(sku_key)[pm_df.columns[6]])
    payment_order["Brand Manager"] = payment_order["Sku"].map(pm_unique.set_index(sku_key)[pm_df.columns[4]])
    payment_order["Vendor SKU"] = payment_order["Sku"].map(pm_unique.set_index(sku_key)[pm_df.columns[3]])
    payment_order["Product Name"] = payment_order["Sku"].map(pm_unique.set_index(sku_key)[pm_df.columns[7]])

    for col in ["Sku", "Vendor SKU"]:
        payment_order[col] = payment_order[col].astype(str)

    cols = payment_order.columns.tolist()
    sku_idx = cols.index("Sku")
    for c in ["Brand", "Brand Manager", "Vendor SKU", "Product Name"]:
        cols.remove(c)
    for i, c in enumerate(["Brand", "Brand Manager", "Vendor SKU", "Product Name"]):
        cols.insert(sku_idx + 1 + i, c)

    return payment_order[cols]

def create_pivot_table(df, index_col):
    df["total"] = pd.to_numeric(df["total"], errors="coerce")
    pivot = pd.pivot_table(df, index=index_col, values="total", aggfunc="sum")

    grand_total = pivot["total"].sum()
    pivot = pivot.reset_index()
    pivot.loc[len(pivot)] = ["Grand Total", grand_total]

    return pivot

def process_service_fees(payment_df):
    df = payment_df[payment_df["type"] == "Service Fee"].copy()
    cols = ["other transaction fees", "other", "total"]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")

    summary = df[cols].sum()
    return summary, df

# ==============================
# UI – HEADER
# ==============================
render_header("Amazon Support NCEMI Analysis Tool", "Upload your payment data and match SKUs with B2B / B2C reports")

# ==============================
# Upload Section in Sidebar
# ==============================
st.sidebar.header("📁 Required Files")
payment_file = st.sidebar.file_uploader("Payment Transaction CSV", type="csv", key="payment")
pm_file = st.sidebar.file_uploader("Product Master (PM) Excel", type=["xlsx", "xls"], key="pm")

st.sidebar.markdown("---")
st.sidebar.header("📦 B2B / B2C Files")
b2b_files = st.sidebar.file_uploader("B2B Files", type=["csv", "zip"], accept_multiple_files=True, key="b2b")
b2c_files = st.sidebar.file_uploader("B2C Files", type=["csv", "zip"], accept_multiple_files=True, key="b2c")

st.sidebar.markdown("---")
st.sidebar.info("👆 Upload files, then click **Process Data** below")

# ==============================
# Process Button in Main Content
# ==============================
if st.button("🚀 Process Data", type="primary", use_container_width=True):
    payment_df = load_payment_csv(payment_file)
    payment_order = process_payment_data(payment_df)

    st.markdown(f"<div class='info-box'>✅ Found {len(payment_order)} promotion deduction orders</div>", unsafe_allow_html=True)

    for f in b2b_files + b2c_files:
        df_rep = load_zip_csv(f) if f.name.endswith(".zip") else pd.read_csv(f)
        payment_order = fill_sku_from_report(payment_order, df_rep)
        st.markdown(f"<div class='info-box'>✅ Processed: {f.name}</div>", unsafe_allow_html=True)

    pm_df = load_excel_file(pm_file)
    payment_order = add_brand_info(payment_order, pm_df)

    st.markdown("<div class='success-box'>🎉 Processing complete</div>", unsafe_allow_html=True)

    # Save to MongoDB
    from common.mongo import save_reconciliation_report
    save_reconciliation_report(
        collection_name="support_ncemi",
        invoice_no=f"NCEMI_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        summary_data={
            "total_orders": len(payment_order),
            "skus_filled": int(payment_order['Sku'].notna().sum()),
            "skus_missing": int(payment_order['Sku'].isna().sum())
        },
        line_items_data=payment_order,
        metadata={"report_type": "support_ncemi"}
    )

    st.session_state.payment_order = payment_order
    st.session_state.payment_df = payment_df

# ==============================
# Results
# ==============================
if "payment_order" in st.session_state:
    df = st.session_state.payment_order

    st.markdown("## 📊 Results")

    m1, m2, m3 = st.columns(3)
    m1.markdown(f"<div class='metric-box'><div class='metric-label'>Total Orders</div><div class='metric-value'>{len(df)}</div></div>", unsafe_allow_html=True)
    m2.markdown(f"<div class='metric-box'><div class='metric-label'>SKUs Filled</div><div class='metric-value'>{df['Sku'].notna().sum()}</div></div>", unsafe_allow_html=True)
    m3.markdown(f"<div class='metric-box'><div class='metric-label'>SKUs Missing</div><div class='metric-value'>{df['Sku'].isna().sum()}</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Brand Analysis",
        "👥 Brand Manager Analysis",
        "💰 Service Fees",
        "📋 Raw Data"
    ])

    with tab1:
        pivot_brand = create_pivot_table(df, "Brand")
        st.dataframe(make_arrow_safe(pivot_brand), use_container_width=True)
        download_module_report(
            df=pivot_brand,
            module_name=MODULE_NAME,
            report_name="Brand Analysis",
            button_label="📥 Download Brand Analysis",
            key="ncemi_brand"
        )

    with tab2:
        pivot_mgr = create_pivot_table(df, "Brand Manager")
        st.dataframe(make_arrow_safe(pivot_mgr), use_container_width=True)
        download_module_report(
            df=pivot_mgr,
            module_name=MODULE_NAME,
            report_name="Brand Manager Analysis",
            button_label="📥 Download Brand Manager Analysis",
            key="ncemi_manager"
        )

    with tab3:
        summary, service_df = process_service_fees(st.session_state.payment_df)

        c1, c2, c3 = st.columns(3)
        c1.metric("Other Transaction Fees", f"₹{summary['other transaction fees']:,.2f}")
        c2.metric("Other", f"₹{summary['other']:,.2f}")
        c3.metric("Total", f"₹{summary['total']:,.2f}")

        st.dataframe(make_arrow_safe(service_df), use_container_width=True)
        download_module_report(
            df=service_df,
            module_name=MODULE_NAME,
            report_name="Service Fees Details",
            button_label="📥 Download Service Fees",
            key="ncemi_service_fees"
        )

    with tab4:
        st.dataframe(make_arrow_safe(df), use_container_width=True)
        download_module_report(
            df=df,
            module_name=MODULE_NAME,
            report_name="Raw Data",
            button_label="📥 Download Raw Data",
            key="ncemi_raw_data"
        )
