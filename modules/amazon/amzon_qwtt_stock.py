import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime

from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

# Module name for MongoDB collection
MODULE_NAME = "amazon"

st.set_page_config(page_title="QWTT Reports", layout="wide")
apply_professional_style()

render_header("QWTT Inventory & Sales Report")

# File uploaders in sidebar
st.sidebar.header("Upload Files")
inventory_file = st.sidebar.file_uploader("Upload Inventory CSV", type=['csv'])
pm_file = st.sidebar.file_uploader("Upload PM Excel", type=['xlsx'])
sales_file = st.sidebar.file_uploader("Upload Sales CSV", type=['csv'])

def process_data(inventory_df, pm_df, sales_df):
    """Process the data and return inventory and sales reports"""
    
    # Process Inventory Report
    inv_pivot = (
        inventory_df
        .pivot_table(index="Asin", values="Sellable", aggfunc="sum")
        .reset_index()
        .rename(columns={"Sellable": "Stock"})
    )
    
    # Create lookup dictionaries from PM
    vendor_sku_lookup = pm_df.set_index("ASIN")["Vendor SKU Codes"].to_dict()
    brand_lookup = pm_df.set_index("ASIN")["Brand"].to_dict()
    manager_lookup = pm_df.set_index("ASIN")["Brand Manager"].to_dict()
    product_lookup = pm_df.set_index("ASIN")["Product Name"].to_dict()
    cp_lookup = pm_df.set_index("ASIN")["CP"].to_dict()
    
    # Map data to inventory pivot
    inv_pivot["Vendor SKU Codes"] = inv_pivot["Asin"].map(vendor_sku_lookup)
    inv_pivot["Brand"] = inv_pivot["Asin"].map(brand_lookup)
    inv_pivot["Brand Manager"] = inv_pivot["Asin"].map(manager_lookup)
    inv_pivot["Product Name"] = inv_pivot["Asin"].map(product_lookup)
    inv_pivot["CP"] = inv_pivot["Asin"].map(cp_lookup)
    
    # Convert CP to numeric and round to 2 decimal places
    inv_pivot["CP"] = pd.to_numeric(inv_pivot["CP"], errors='coerce').round(2)
    
    # Reorder columns for inventory
    inv_pivot = inv_pivot[["Asin", "Vendor SKU Codes", "Brand", "Brand Manager", 
                           "Product Name", "Stock", "CP"]]
    
    # Process Sales Data
    sales_df_clean = sales_df[
        ~sales_df["Status"].fillna("").str.lower().isin(["cancelled", "sidelined"])
    ]
    sales_df_clean = sales_df_clean[sales_df_clean["Order Value"] != 0]
    
    sales_inv_pivot = (
        sales_df_clean
        .groupby("ASIN", as_index=False)["Units"]
        .sum()
        .rename(columns={"Units": "Sales Qty"})
    )
    
    # Add Sales Qty to inventory report
    sales_qty_lookup = sales_inv_pivot.set_index("ASIN")["Sales Qty"].to_dict()
    inv_pivot["Sales Qty"] = inv_pivot["Asin"].map(sales_qty_lookup).fillna(0)
    inv_pivot["CP as Per Stock"] = (inv_pivot["CP"] * inv_pivot["Stock"]).round(2)
    inv_pivot["CP as Per Sales Qty"] = (inv_pivot["CP"] * inv_pivot["Sales Qty"]).round(2)
    
    # Create Sales Report
    sales_report = sales_inv_pivot.copy()
    sales_report["Vendor SKU Codes"] = sales_report["ASIN"].map(vendor_sku_lookup)
    sales_report["Brand"] = sales_report["ASIN"].map(brand_lookup)
    sales_report["Brand Manager"] = sales_report["ASIN"].map(manager_lookup)
    sales_report["Product Name"] = sales_report["ASIN"].map(product_lookup)
    sales_report["CP"] = pd.to_numeric(sales_report["ASIN"].map(cp_lookup), errors='coerce').round(2)
    
    # Add Stock to sales report
    sales_stock_lookup = inv_pivot.set_index("Asin")["Stock"].to_dict()
    sales_report["Stock"] = sales_report["ASIN"].map(sales_stock_lookup)
    sales_report["CP as Per Sales Qty"] = (sales_report["CP"] * sales_report["Sales Qty"]).round(2)
    
    # Reorder columns for sales report
    sales_report = sales_report[["ASIN", "Vendor SKU Codes", "Brand", "Brand Manager",
                                 "Product Name", "Sales Qty", "CP", "Stock", "CP as Per Sales Qty"]]
    
    return inv_pivot, sales_report

def add_grand_total(df):
    """Add grand total row to dataframe"""
    df_copy = df.copy()
    
    # Create grand total row
    total_row = {}
    for col in df_copy.columns:
        if df_copy[col].dtype in ['int64', 'float64']:
            total_value = df_copy[col].sum()
            # Round CP and CP as Per columns to 2 decimal places
            if col in ['CP', 'CP as Per Sales Qty', 'CP as Per Stock']:
                total_row[col] = round(total_value, 2)
            else:
                total_row[col] = total_value
        else:
            total_row[col] = 'GRAND TOTAL' if col == df_copy.columns[0] else ''
    
    # Add total row
    total_df = pd.DataFrame([total_row])
    df_with_total = pd.concat([df_copy, total_df], ignore_index=True)
    
    return df_with_total

# Generate button
generate_button = st.sidebar.button("🚀 Generate Reports", type="primary", use_container_width=True)

# Main app logic
if inventory_file and pm_file and sales_file and generate_button:
    try:
        with st.spinner("Processing files..."):
            # Read files
            inventory_df = pd.read_csv(inventory_file)
            pm_df = pd.read_excel(pm_file)
            sales_df = pd.read_csv(sales_file)
        
        # Process data
        with st.spinner("Generating reports..."):
            inv_report, sales_report = process_data(inventory_df, pm_df, sales_df)
        
        st.success("✅ Reports generated successfully!")
        
        # Create tabs
        tab1, tab2 = st.tabs(["📦 QWTT Inventory Report", "💰 QWTT Sales Report"])
        
        with tab1:
            st.subheader("QWTT Inventory Report")
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total ASINs", len(inv_report))
            with col2:
                st.metric("Total Stock", int(inv_report["Stock"].sum()))
            with col3:
                st.metric("Total Sales Qty", int(inv_report["Sales Qty"].sum()))
            with col4:
                st.metric("Total CP Value", f"₹{inv_report['CP as Per Stock'].sum():,.2f}")
            
            st.divider()
            
            # Add grand total to display
            inv_report_with_total = add_grand_total(inv_report)
            
            # Display dataframe
            st.dataframe(inv_report_with_total, use_container_width=True, height=500)
            
            # Download with module-specific saving
            download_module_report(
                df=inv_report_with_total,
                module_name=MODULE_NAME,
                report_name="QWTT Inventory Report",
                button_label="📥 Download Inventory Report",
                key="dl_qwtt_inventory"
            )
        
        with tab2:
            st.subheader("QWTT Sales Report")
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Products Sold", len(sales_report))
            with col2:
                st.metric("Total Units Sold", int(sales_report["Sales Qty"].sum()))
            with col3:
                st.metric("Total Sales Value", f"₹{sales_report['CP as Per Sales Qty'].sum():,.2f}")
            with col4:
                avg_cp = sales_report['CP as Per Sales Qty'].sum() / sales_report['Sales Qty'].sum()
                st.metric("Avg CP per Unit", f"₹{avg_cp:,.2f}")
            
            st.divider()
            
            # Add grand total to display
            sales_report_with_total = add_grand_total(sales_report)
            
            # Display dataframe
            st.dataframe(sales_report_with_total, use_container_width=True, height=500)
            
            # Download with module-specific saving
            download_module_report(
                df=sales_report_with_total,
                module_name=MODULE_NAME,
                report_name="QWTT Sales Report",
                button_label="📥 Download Sales Report",
                key="dl_qwtt_sales"
            )
            
    except Exception as e:
        st.error(f"❌ Error processing files: {str(e)}")
        st.info("Please ensure all files are uploaded in the correct format.")
elif inventory_file and pm_file and sales_file and not generate_button:
    st.info("✅ All files uploaded! Click the '🚀 Generate Reports' button in the sidebar to process.")
else:
    st.info("👈 Please upload all three required files in the sidebar to begin:")
    st.markdown("""
    1. **Inventory CSV** - QWTT inventory by bin file
    2. **PM Excel** - Purchase master file
    3. **Sales CSV** - QWTT customer shipments file
    """)
    
    # Show sample format expectations
    with st.expander("ℹ️ File Format Requirements"):
        st.markdown("""
        **Inventory CSV should contain:**
        - Asin
        - Sellable
        - Other inventory columns
        
        **PM Excel should contain:**
        - ASIN
        - Vendor SKU Codes
        - Brand
        - Brand Manager
        - Product Name
        - CP
        
        **Sales CSV should contain:**
        - ASIN
        - Units
        - Status
        - Order Value
        """)

# Footer
st.divider()
st.caption("QWTT Inventory & Sales Report Generator | Built with Streamlit")
