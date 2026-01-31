import streamlit as st
import pandas as pd
import numpy as np
import gc
from io import BytesIO
from datetime import datetime
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    auto_save_generated_reports
)

MODULE_NAME = "flipkart"

st.set_page_config(page_title="Flipkart QWTT Reports", layout="wide")
apply_professional_style()

render_header("Flipkart QWTT Sales & Inventory Report")

# File uploaders in sidebar
st.sidebar.header("Upload Files")
sales_file = st.sidebar.file_uploader("Upload Shipped Orders CSV", type=['csv'])
pm_file = st.sidebar.file_uploader("Upload PM Excel (Flipkart)", type=['xlsx'])
inventory_file = st.sidebar.file_uploader("Upload Inventory Report CSV", type=['csv'])

# Generate button
generate_button = st.sidebar.button("🚀 Generate Reports", type="primary", use_container_width=True)

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

def to_excel(df, sheet_name):
    """Convert dataframe to Excel bytes"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

def process_flipkart_data(sales_df, pm_df, inventory_df):
    """Process Flipkart data and return sales and inventory reports"""
    
    # Process Sales Report
    # Filter only Flipkart marketplace
    sales_df = sales_df[sales_df["Marketplace"].str.strip().str.lower() == "flipkart"]
    
    # Pivot: SKU wise sales quantity
    sales_pivot = (
        sales_df
        .groupby("SKU", as_index=False)["Quantity"]
        .sum()
        .rename(columns={"Quantity": "Sales Qty"})
    )
    
    # Create lookup dictionaries from PM file - Optimized: set index once
    pm_lookup = pm_df.set_index("EasycomSKU")
    fsn_map = pm_lookup["FNS"].to_dict()
    vendor_sku_map = pm_lookup["Vendor SKU Codes"].to_dict()
    brand_map = pm_lookup["Brand"].to_dict()
    manager_map = pm_lookup["Brand Manager"].to_dict()
    product_map = pm_lookup["Product Name"].to_dict()
    cp_map = pm_lookup["CP"].to_dict()
    
    del pm_lookup
    gc.collect()
    
    # Map data to sales pivot
    sales_pivot["FNS"] = sales_pivot["SKU"].map(fsn_map)
    sales_pivot["Vendor SKU Codes"] = sales_pivot["SKU"].map(vendor_sku_map)
    sales_pivot["Brand"] = sales_pivot["SKU"].map(brand_map)
    sales_pivot["Brand Manager"] = sales_pivot["SKU"].map(manager_map)
    sales_pivot["Product Name"] = sales_pivot["SKU"].map(product_map)
    sales_pivot["CP"] = pd.to_numeric(sales_pivot["SKU"].map(cp_map), errors='coerce').round(2)
    
    # Process Inventory Report
    # Clean SKU column - remove backticks and trim
    inventory_df["sku"] = (
        inventory_df["sku"]
        .astype(str)
        .str.replace("`", "", regex=False)
        .str.strip()
    )
    
    # Pivot: SKU wise total stock
    inventory_pivot = (
        inventory_df
        .groupby("sku", as_index=False)["old_quantity"]
        .sum()
        .rename(columns={"old_quantity": "Stock"})
    )
    
    # Add stock to sales report
    stock_map = inventory_pivot.set_index("sku")["Stock"].to_dict()
    sales_pivot["Stock"] = sales_pivot["SKU"].map(stock_map)
    
    # Calculate CP as Per Sales Qty for sales report
    sales_pivot["CP as Per Sales Qty"] = (sales_pivot["CP"] * sales_pivot["Sales Qty"]).round(2)
    
    # Reorder columns for sales report
    sales_report = sales_pivot[[
        "SKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager",
        "Product Name", "Sales Qty", "CP", "Stock", "CP as Per Sales Qty"
    ]]
    
    # Process Inventory Report
    inventory_report = inventory_pivot.copy()
    
    # Map data to inventory report
    inventory_report["FNS"] = inventory_report["sku"].map(fsn_map)
    inventory_report["Vendor SKU Codes"] = inventory_report["sku"].map(vendor_sku_map)
    inventory_report["Brand"] = inventory_report["sku"].map(brand_map)
    inventory_report["Brand Manager"] = inventory_report["sku"].map(manager_map)
    inventory_report["Product Name"] = inventory_report["sku"].map(product_map)
    inventory_report["CP"] = pd.to_numeric(inventory_report["sku"].map(cp_map), errors='coerce').round(2)
    
    # Add sales qty to inventory report
    sale_qty_inv_map = sales_pivot.set_index("SKU")["Sales Qty"].to_dict()
    inventory_report["Sales Qty"] = inventory_report["sku"].map(sale_qty_inv_map)
    
    # Calculate CP as Per Stock and CP as Per Sales Qty for inventory report
    inventory_report["CP as Per Stock"] = (inventory_report["CP"] * inventory_report["Stock"]).round(2)
    inventory_report["CP as Per Sales Qty"] = (inventory_report["CP"] * inventory_report["Sales Qty"]).round(2)
    
    # Reorder columns for inventory report
    inventory_report = inventory_report[[
        "sku", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager",
        "Product Name", "Stock", "Sales Qty", "CP", "CP as Per Stock", "CP as Per Sales Qty"
    ]]
    
    return sales_report, inventory_report

# Main app logic
if sales_file and pm_file and inventory_file and generate_button:
    try:
        container = st.container()
        with st.spinner("Processing files..."):
            # 1. Read Sales File (Optimized)
            sales_df = pd.read_csv(
                sales_file, 
                usecols=["Marketplace", "SKU", "Quantity"],
                dtype={"Marketplace": "category", "SKU": "str", "Quantity": "float32"}
            )
            
            # 2. Read PM File (Optimized)
            pm_cols = ["EasycomSKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager", "Product Name", "CP"]
            if pm_file.name.endswith('.csv'):
                pm_df = pd.read_csv(pm_file, usecols=pm_cols)
            else:
                pm_df = pd.read_excel(pm_file, usecols=pm_cols)
            pm_df = pm_df.drop_duplicates(subset=["EasycomSKU"])
            
            # 3. Read Inventory File (Optimized)
            inventory_df = pd.read_csv(
                inventory_file,
                usecols=["sku", "old_quantity"],
                dtype={"sku": "str", "old_quantity": "float32"}
            )
            
            gc.collect()
        
        # Process data
        with st.spinner("Generating reports..."):
            sales_report, inventory_report = process_flipkart_data(sales_df, pm_df, inventory_df)
            
            # Clear raw dataframes to save RAM
            del sales_df
            del pm_df
            del inventory_df
            gc.collect()

        # Auto-save generated reports to MongoDB
        auto_save_generated_reports(
            reports={
                "QWTT Sales Report": sales_report,
                "QWTT Inventory Report": inventory_report
            },
            module_name=MODULE_NAME
        )
        
        st.success("✅ Reports generated successfully!")
        
        # Create tabs
        tab1, tab2 = st.tabs(["💰 Flipkart Sales Report", "📦 Flipkart Inventory Report"])
        
        with tab1:
            st.subheader("Flipkart Sales Report")
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Products Sold", len(sales_report))
            with col2:
                st.metric("Total Units Sold", int(sales_report["Sales Qty"].sum()))
            with col3:
                sales_total_val = sales_report['CP as Per Sales Qty'].sum()
                st.metric("Total Sales Value", f"₹{sales_total_val:,.2f}")
            with col4:
                sales_qty_total = sales_report['Sales Qty'].sum()
                avg_cp = sales_total_val / sales_qty_total if sales_qty_total > 0 else 0
                st.metric("Avg CP per Unit", f"₹{avg_cp:,.2f}")
            
            st.divider()
            
            # Add grand total to display (limited to 5000 rows for stability)
            display_df = sales_report.head(5000)
            if len(sales_report) > 5000:
                st.warning(f"⚠️ Showing first 5,000 products of {len(sales_report):,} for performance.")
            
            sales_report_with_total = add_grand_total(display_df)
            st.dataframe(sales_report_with_total, use_container_width=True, height=500)
            
            # Download with module-specific saving
            download_module_report(
                df=sales_report_with_total,
                module_name=MODULE_NAME,
                report_name="QWTT Sales Report",
                button_label="📥 Download Sales Report",
                key="dl_fk_qwtt_sales"
            )
        
        with tab2:
            st.subheader("Flipkart Inventory Report")
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total SKUs", len(inventory_report))
            with col2:
                st.metric("Total Stock", int(inventory_report["Stock"].sum()))
            with col3:
                sales_qty_total = inventory_report["Sales Qty"].sum()
                st.metric("Total Sales Qty", int(sales_qty_total) if pd.notna(sales_qty_total) else 0)
            with col4:
                cp_total = inventory_report['CP as Per Stock'].sum()
                st.metric("Total CP Value", f"₹{cp_total:,.2f}" if pd.notna(cp_total) else "₹0.00")
            
            st.divider()
            
            # Add grand total to display (limited to 5000 rows for stability)
            display_inv_df = inventory_report.head(5000)
            if len(inventory_report) > 5000:
                st.warning(f"⚠️ Showing first 5,000 SKUs of {len(inventory_report):,} for performance.")
                
            inventory_report_with_total = add_grand_total(display_inv_df)
            st.dataframe(inventory_report_with_total, use_container_width=True, height=500)
            
            # Download with module-specific saving
            download_module_report(
                df=inventory_report_with_total,
                module_name=MODULE_NAME,
                report_name="QWTT Inventory Report",
                button_label="📥 Download Inventory Report",
                key="dl_fk_qwtt_inventory"
            )
            
    except Exception as e:
        st.error(f"❌ Error processing files: {str(e)}")
        st.info("Please ensure all files are uploaded in the correct format.")
elif sales_file and pm_file and inventory_file and not generate_button:
    st.info("✅ All files uploaded! Click the '🚀 Generate Reports' button in the sidebar to process.")
else:
    st.info("👈 Please upload all three required files in the sidebar to begin:")
    st.markdown("""
    1. **Shipped Orders CSV** - Flipkart shipped orders file
    2. **PM Excel** - Product master file (Flipkart)
    3. **Inventory Report CSV** - Flipkart inventory report
    """)
    
    # Show sample format expectations
    with st.expander("ℹ️ File Format Requirements"):
        st.markdown("""
        **Shipped Orders CSV should contain:**
        - Company
        - Marketplace (must contain "Flipkart")
        - Order Number
        - SKU
        - Quantity
        - Brand
        - Product Name
        
        **PM Excel should contain:**
        - FNS
        - EasycomSKU
        - Vendor SKU Codes
        - Brand
        - Brand Manager
        - Product Name
        - CP
        
        **Inventory Report CSV should contain:**
        - sku (may have backticks)
        - old_quantity (will be summed as Stock)
        - Brand
        - Product Name
        """)

# Footer
st.divider()
st.caption("Flipkart Sales & Inventory Report Generator | Built with Streamlit")
