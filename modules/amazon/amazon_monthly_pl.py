import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    auto_save_generated_reports
)

# Module name for MongoDB collection
MODULE_NAME = "amazon"
TOOL_NAME = "amazon_monthly_pl"

# Page configuration is handled by the main app
apply_professional_style()

render_header("Amazon Monthly P&L Analysis Dashboard")

# File uploaders
st.sidebar.header("Upload Files")
transaction_file = st.sidebar.file_uploader("Upload Transaction CSV", type=['csv'])
pm_file = st.sidebar.file_uploader("Upload PM Excel", type=['xlsx'])
ncemi_file = st.sidebar.file_uploader("Upload NCEMI CSV", type=['csv'])
dyson_file = st.sidebar.file_uploader("Upload Dyson Support CSV", type=['csv'])

def normalize_sku(series):
    return series.astype(str).str.strip().str.upper()

def normalize_asin(series):
    return series.astype(str).str.strip().str.upper()

def process_data(transaction_file, pm_file, ncemi_file, dyson_file):
    # Read Transaction file
    Transaction = pd.read_csv(transaction_file, header=11)
    
    # Filter Order type
    order_df_1 = Transaction[Transaction["type"] == "Order"].copy()
    
    # Clean product sales
    order_df_1["product sales"] = (
        order_df_1["product sales"]
        .astype(str)
        .str.replace(",", "", regex=False)
    )
    order_df_1["product sales"] = pd.to_numeric(
        order_df_1["product sales"], errors="coerce"
    ).fillna(0)
    
    # Remove zero sales
    order_df_1 = order_df_1[order_df_1["product sales"] != 0].copy()
    
    # Clean GST column
    order_df_1["Total sales tax liable(GST before adjusting TCS)"] = (
        order_df_1["Total sales tax liable(GST before adjusting TCS)"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    order_df_1["Total sales tax liable(GST before adjusting TCS)"] = pd.to_numeric(
        order_df_1["Total sales tax liable(GST before adjusting TCS)"],
        errors="coerce"
    ).fillna(0)

    
    # Calculate Sales Amount
    order_df_1["Sales Amount"] = (
        order_df_1["product sales"] + 
        order_df_1["Total sales tax liable(GST before adjusting TCS)"]
    )
    
    # Normalize SKU
    order_df_1["Sku"] = normalize_sku(order_df_1["Sku"])
    
    # Read PM file
    PM = pd.read_excel(pm_file)
    PM["Amazon Sku Name"] = normalize_sku(PM["Amazon Sku Name"])
    
    # Map ASIN, Brand, Brand Manager
    asin_map = dict(zip(PM["Amazon Sku Name"], PM["ASIN"]))
    brand_map = dict(zip(PM["Amazon Sku Name"], PM["Brand"]))
    manager_map = dict(zip(PM["Amazon Sku Name"], PM["Brand Manager"]))
    
    order_df_1["ASIN"] = order_df_1["Sku"].map(asin_map).fillna("")
    order_df_1["Brand"] = order_df_1["Sku"].map(brand_map).fillna("")
    order_df_1["Brand Manager"] = order_df_1["Sku"].map(manager_map).fillna("")
    
    # Clean total column
    order_df_1["total"] = (
        order_df_1["total"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    order_df_1["total"] = pd.to_numeric(
        order_df_1["total"], errors="coerce"
    ).fillna(0)
    
    # Calculate difference and percentage
    order_df_1["difference"] = order_df_1["Sales Amount"] - order_df_1["total"]
    order_df_1["percentage"] = np.where(
        order_df_1["Sales Amount"] != 0,
        (order_df_1["difference"] / order_df_1["Sales Amount"]) * 100,
        0
    ).round(2)
    
    order_df_1["quantity"] = (
        order_df_1["quantity"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    order_df_1["quantity"] = pd.to_numeric(
        order_df_1["quantity"], errors="coerce"
    ).fillna(0)

    # Normalize ASIN
    order_df_1["ASIN"] = normalize_asin(order_df_1["ASIN"])
    PM["ASIN"] = normalize_asin(PM["ASIN"])
    
    # Map Our Cost
    PM["CP"] = (
        PM["CP"]
        .astype(str)
        .str.replace("₹", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.strip()
    )

    PM["CP"] = pd.to_numeric(
        PM["CP"], errors="coerce"
    ).fillna(0)

    cp_sum_df = PM.groupby("ASIN", as_index=False)["CP"].sum()
    our_cost_map = dict(zip(cp_sum_df["ASIN"], cp_sum_df["CP"]))
    order_df_1["Our Cost"] = order_df_1["ASIN"].map(our_cost_map)
    order_df_1["Our Cost As per Qty"] = order_df_1["Our Cost"] * order_df_1["quantity"]
    
    # Calculate Profit
    order_df_1["Profit"] = order_df_1["total"] - order_df_1["Our Cost As per Qty"]
    order_df_1["Profit"] = pd.to_numeric(order_df_1["Profit"], errors="coerce").fillna(0)
    order_df_1["Our Cost As per Qty"] = pd.to_numeric(
        order_df_1["Our Cost As per Qty"], errors="coerce"
    ).fillna(0)
    
    # Calculate Profit %
    order_df_1["Profit %"] = np.where(
        order_df_1["Our Cost As per Qty"] != 0,
        (order_df_1["Profit"] / order_df_1["Our Cost As per Qty"]) * 100,
        0
    ).round(2)
    
    # Map Support Amount
    PM["Additional Support"] = (
        PM["Additional Support"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.strip()
    )

    PM["Additional Support"] = pd.to_numeric(
        PM["Additional Support"], errors="coerce"
    ).fillna(0)

    support_sum_df = PM.groupby("ASIN", as_index=False)["Additional Support"].sum()
    support_map = dict(zip(support_sum_df["ASIN"], support_sum_df["Additional Support"]))
    order_df_1["Support Amount"] = order_df_1["ASIN"].map(support_map).fillna(0)
    
    # Create Combine column
    order_df_1["order id"] = order_df_1["order id"].astype(str).str.strip()

    order_df_1["Combine"] = (
        order_df_1["order id"].astype(str).fillna("") +
        order_df_1["Sku"].astype(str).fillna("")
    )
    
    # Process Coupon data
    Coupon = Transaction.copy()
    Coupon["order id"] = Coupon["order id"].astype(str).str.strip()
    Coupon["Sku"] = normalize_sku(Coupon["Sku"])
    Coupon = Coupon[Coupon["type"].astype(str).str.strip().str.lower() == "order"]
    Coupon["product sales"] = (
        Coupon["product sales"]
        .astype(str)
        .str.replace(",", "", regex=False)
    )
    Coupon["product sales"] = pd.to_numeric(
        Coupon["product sales"], errors="coerce"
    ).fillna(0)
    Coupon = Coupon[Coupon["product sales"] != 0]
    
    Coupon["shipping credits"] = (
        Coupon["shipping credits"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    Coupon["shipping credits"] = pd.to_numeric(
        Coupon["shipping credits"], errors="coerce"
    ).fillna(0)

    Coupon = Coupon[Coupon["shipping credits"] == 0]
    
    Coupon["promotional rebates"] = (
        Coupon["promotional rebates"]
        .astype(str)
        .str.replace(",", "", regex=False)
    )
    Coupon["promotional rebates"] = pd.to_numeric(
        Coupon["promotional rebates"], errors="coerce"
    ).fillna(0)
    Coupon = Coupon[Coupon["promotional rebates"] != 0]
    
    Coupon["Combine"] = (
        Coupon["order id"].astype(str).fillna("") +
        Coupon["Sku"].astype(str).fillna("")
    )
    
    coupon_sum_df = Coupon.groupby("Combine", as_index=False)["promotional rebates"].sum()
    coupon_map = dict(zip(coupon_sum_df["Combine"], coupon_sum_df["promotional rebates"]))
    order_df_1["Coupon Amount"] = order_df_1["Combine"].map(coupon_map).fillna(0)
    
    # Process NCEMI data
    NCEMI = pd.read_csv(ncemi_file)
    NCEMI["order id"] = NCEMI["order id"].astype(str).str.strip()
    NCEMI["Sku"] = normalize_sku(NCEMI["Sku"])
    NCEMI["Combine"] = (
        NCEMI["order id"].astype(str).fillna("") +
        NCEMI["Sku"].astype(str).fillna("")
    )
    NCEMI["total"] = (
        NCEMI["total"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )
    NCEMI_sum_df = NCEMI.groupby("Combine", as_index=False)["total"].sum()
    NCEMI_map = dict(zip(NCEMI_sum_df["Combine"], NCEMI_sum_df["total"]))
    order_df_1["NCEMI Amount"] = order_df_1["Combine"].map(NCEMI_map).fillna(0)
    
    # Process Dyson Support
    Dyson_Support = pd.read_csv(dyson_file)
    Dyson_Support["Asin"] = normalize_asin(Dyson_Support["Asin"])
    Dyson_Support["Support"] = (
        Dyson_Support["Support"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )
    dyson_support_sum = Dyson_Support.groupby("Asin", as_index=False)["Support"].sum()
    support_map = dict(zip(dyson_support_sum["Asin"], dyson_support_sum["Support"]))
    order_df_1["Dyson Support"] = order_df_1["ASIN"].map(support_map).fillna(0)
    
    # Set Dyson Support Amount to 0 for Dyson brand
    dyson_mask = order_df_1["Brand"].astype(str).str.strip().str.lower() == "dyson"
    order_df_1.loc[dyson_mask, "Support Amount"] = 0
    
    # Calculate With Support Purchase Cost
    cols_to_numeric = ["Our Cost", "Support Amount", "Dyson Support", "Coupon Amount"]
    for col in cols_to_numeric:
        order_df_1[col] = pd.to_numeric(order_df_1[col], errors="coerce").fillna(0)
    
    order_df_1["With Support Purchase Cost"] = (
        order_df_1["Our Cost"]
        - order_df_1["Support Amount"]
        - order_df_1["Dyson Support"]
        + order_df_1["Coupon Amount"]
    )
    
    order_df_1["With Support Purchase Cost As per Qty"] = (
        order_df_1["With Support Purchase Cost"] * order_df_1["quantity"]
    )
    
    order_df_1["With All Profit"] = (
        order_df_1["total"] - order_df_1["With Support Purchase Cost As per Qty"]
    )
    
    order_df_1["TP 3%"] = (order_df_1["total"] * 0.03).round(2)
    order_df_1["Profit Diff"] = order_df_1["With All Profit"] - order_df_1["TP 3%"]
    
    order_df_1["Profit in %"] = np.where(
        order_df_1["With Support Purchase Cost As per Qty"] != 0,
        (order_df_1["Profit Diff"] / order_df_1["With Support Purchase Cost As per Qty"]) * 100,
        0
    ).round(2)
    
    return order_df_1

if transaction_file and pm_file and ncemi_file and dyson_file:
    # Process button
    if st.button("🔄 Process Data", type="primary", use_container_width=True):
        try:
            with st.spinner('Processing data...'):
                result_df = process_data(transaction_file, pm_file, ncemi_file, dyson_file)
                st.session_state['result_df'] = result_df
                
                # Auto-save reports
                auto_save_generated_reports(
                    reports={
                        "Monthly PL Analysis": result_df
                    },
                    module_name=MODULE_NAME,
                    tool_name=TOOL_NAME
                )
                
                st.success(f"✅ Data processed successfully! Total records: {len(result_df)}")
        except Exception as e:
            st.error(f"❌ Error processing data: {str(e)}")
            st.exception(e)
    
    # Display results if data has been processed
    if 'result_df' in st.session_state:
        result_df = st.session_state['result_df']
        
        # Summary metrics
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Sales", f"₹{result_df['Sales Amount'].sum():,.2f}")
        with col2:
            st.metric("Total Profit", f"₹{result_df['With All Profit'].sum():,.2f}")
        with col3:
            st.metric(
                "Total Orders",
                result_df["order id"].nunique()
            )
        with col4:
            avg_profit = result_df['Profit in %'].mean()
            st.metric("Avg Profit %", f"{avg_profit:.2f}%")
        
        st.markdown("---")
        
        # Main data view
        st.subheader("📊 Processed Transaction Data")
        st.dataframe(result_df, use_container_width=True, height=400)
        
        st.markdown("---")
        
        # Analysis sections
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.subheader("📈 Brand-wise Analysis")
            brand_analysis = result_df.groupby('Brand').agg({
                'Sales Amount': 'sum',
                'With All Profit': 'sum',
                'quantity': 'sum'
            }).reset_index()
            st.dataframe(brand_analysis, use_container_width=True)
        
        with col_right:
            st.subheader("👤 Manager-wise Analysis")
            manager_analysis = result_df.groupby('Brand Manager').agg({
                'Sales Amount': 'sum',
                'With All Profit': 'sum',
                'quantity': 'sum'
            }).reset_index()
            st.dataframe(manager_analysis, use_container_width=True)
        
        st.markdown("---")
        
        # Download buttons
        st.subheader("💾 Download Reports")
        
        download_module_report(
            df=result_df,
            module_name=MODULE_NAME,
            report_name="Monthly PL Analysis",
            button_label="📥 Download Excel",
            key="dl_monthly_pl",
            tool_name=TOOL_NAME
        )

else:
    st.info("👈 Please upload all required files from the sidebar to begin analysis")
    
    st.markdown("""
    ### Required Files:
    1. **Transaction CSV** - Amazon transaction report (header at row 11)
    2. **PM Excel** - Purchase Master file
    3. **NCEMI CSV** - No Cost EMI data
    4. **Dyson Support CSV** - Dyson support information
    
    ### Features:
    - ✨ Automatic data processing
    - 📊 Summary metrics and insights
    - 📈 Brand and manager-wise analysis
    - 💾 Download results as Excel or CSV

    """)
