import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

from mongo_utils import save_reconciliation_report
from ui_utils import apply_professional_style, get_download_filename, render_header

st.set_page_config(page_title="Amazon Monthly P&L Analysis", layout="wide")
apply_professional_style()

render_header("Amazon Monthly P&L Analysis Dashboard")

# File uploaders
st.sidebar.header("Upload Files")
transaction_file = st.sidebar.file_uploader("Upload Transaction CSV", type=['csv'])
pm_file = st.sidebar.file_uploader("Upload PM Excel", type=['xlsx'])
ncemi_file = st.sidebar.file_uploader("Upload NCEMI CSV", type=['csv'])
dyson_file = st.sidebar.file_uploader("Upload Dyson Support CSV", type=['csv'])

def normalize_sku(series):
    return series.astype(str).str.strip()

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
    order_df_1["total"] = pd.to_numeric(order_df_1["total"], errors="coerce").fillna(0)
    
    # Calculate difference and percentage
    order_df_1["difference"] = order_df_1["Sales Amount"] - order_df_1["total"]
    order_df_1["percentage"] = np.where(
        order_df_1["Sales Amount"] != 0,
        (order_df_1["difference"] / order_df_1["Sales Amount"]) * 100,
        0
    ).round(2)
    
    # Normalize ASIN
    order_df_1["ASIN"] = normalize_asin(order_df_1["ASIN"])
    PM["ASIN"] = normalize_asin(PM["ASIN"])
    
    # Map Our Cost
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
    support_sum_df = PM.groupby("ASIN", as_index=False)["Additional Support"].sum()
    support_map = dict(zip(support_sum_df["ASIN"], support_sum_df["Additional Support"]))
    order_df_1["Support Amount"] = order_df_1["ASIN"].map(support_map).fillna(0)
    
    # Create Combine column
    order_df_1["Combine"] = (
        order_df_1["order id"].astype(str).fillna("") +
        order_df_1["Sku"].astype(str).fillna("")
    )
    
    # Process Coupon data
    Coupon = Transaction.copy()
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
                st.success(f"✅ Data processed successfully! Total records: {len(result_df)}")
        except Exception as e:
            st.error(f"❌ Error processing data: {str(e)}")
            st.exception(e)
            
        # Save to MongoDB
        try:
            # We save here if processed successfully
            save_reconciliation_report(
                collection_name="amazon_monthly_pl",
                invoice_no=f"MonthlyPL_{pd.Timestamp.now().strftime('%Y%m%d%H%M')}",
                summary_data=pd.DataFrame([{"Total Sales": result_df['Sales Amount'].sum(), "Total Profit": result_df['With All Profit'].sum()}]),
                line_items_data=result_df,
                metadata={"type": "monthly_pl"}
            )
        except Exception as e:
            pass
    
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
            st.metric("Total Orders", len(result_df))
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
        
        col_dl1, col_dl2, col_dl3 = st.columns([1, 1, 2])
        
        with col_dl1:
            # Convert to Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                result_df.to_excel(writer, index=False, sheet_name='Processed Data')
            
            st.download_button(
                label="📥 Download Excel",
                data=output.getvalue(),
                file_name=get_download_filename("amazon_analysis_output"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with col_dl2:
            # Convert to CSV
            csv = result_df.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=get_download_filename("amazon_analysis_output.csv"),
                mime="text/csv",
                use_container_width=True
            )

else:
    st.info("👈 Please upload all required files from the sidebar to begin analysis")
    
    st.markdown("""
    ### Required Files:
    1. **Transaction CSV** - Amazon transaction report (header at row 11)
    2. **PM Excel** - Product Master file
    3. **NCEMI CSV** - No Cost EMI data
    4. **Dyson Support CSV** - Dyson support information
    
    ### Features:
    - ✨ Automatic data processing
    - 📊 Summary metrics and insights
    - 📈 Brand and manager-wise analysis
    - 💾 Download results as Excel or CSV

    """)