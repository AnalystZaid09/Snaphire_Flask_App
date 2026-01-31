import streamlit as st
import pandas as pd
import numpy as np
import gc
import os
import tempfile
from io import BytesIO
from datetime import datetime
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
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

def save_to_tmp(uploaded_file):
    """Save an uploaded file to a temporary disk location to free up RAM"""
    if uploaded_file is None:
        return None
    # Ensure uploaded file's buffer is at start
    uploaded_file.seek(0)
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(uploaded_file.name)[1])
    with os.fdopen(fd, 'wb') as tmp:
        tmp.write(uploaded_file.getbuffer())
    return path

def process_flipkart_data(sales_file, pm_file, inventory_file, chunk_size=10000):
    """Process Flipkart data using disk-backed loads and minimal column selection"""
    
    # Define required columns to minimize RAM usage
    SALES_COLS = ["Marketplace", "SKU", "Quantity"]
    PM_COLS = ["EasycomSKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager", "Product Name", "CP"]
    INV_COLS = ["sku", "old_quantity"]

    # Save files to disk to prevent Streamlit from holding them in RAM
    sales_path = save_to_tmp(sales_file)
    pm_path = save_to_tmp(pm_file)
    inv_path = save_to_tmp(inventory_file)
    
    try:
        # 1. Process Sales Report in Chunks (Selective Loading)
        sales_agg = {} # SKU -> Quantity
        if sales_path:
            with st.spinner("Processing Sales (Disk)..."):
                # CSV Chunking with usecols and float32 for RAM
                # detecting format via extension
                is_excel = sales_path.endswith(('.xlsx', '.xls'))
                
                if is_excel:
                    df = pd.read_excel(sales_path, usecols=SALES_COLS)
                    df = df[df["Marketplace"].str.strip().str.lower() == "flipkart"]
                    for sku, qty in df.groupby("SKU")["Quantity"].sum().items():
                        sku_clean = str(sku).strip()
                        sales_agg[sku_clean] = sales_agg.get(sku_clean, 0) + float(qty)
                    del df
                else:
                    for chunk in pd.read_csv(sales_path, chunksize=chunk_size, usecols=SALES_COLS, dtype={"Quantity": "float32"}):
                        chunk = chunk[chunk["Marketplace"].str.strip().str.lower() == "flipkart"]
                        if not chunk.empty:
                            chunk_agg = chunk.groupby("SKU")["Quantity"].sum().to_dict()
                            for sku, qty in chunk_agg.items():
                                sku_clean = str(sku).strip()
                                sales_agg[sku_clean] = sales_agg.get(sku_clean, 0) + qty
                        del chunk
                        gc.collect()

        # 2. Process PM File (Master lookup)
        fsn_map = {}
        vendor_sku_map = {}
        brand_map = {}
        manager_map = {}
        product_map = {}
        cp_map = {}

        if pm_path:
            with st.spinner("Processing Master (Disk)..."):
                is_excel = pm_path.endswith(('.xlsx', '.xls'))
                if is_excel:
                    pm_df = pd.read_excel(pm_path, usecols=PM_COLS)
                else:
                    pm_df = pd.read_csv(pm_path, usecols=PM_COLS)
                
                pm_df = pm_df.drop_duplicates(subset=["EasycomSKU"])
                
                # Manual iterate to build maps (more RAM efficient than whole series to_dict)
                for _, row in pm_df.iterrows():
                    sku = str(row["EasycomSKU"]).strip()
                    if sku:
                        fsn_map[sku] = row.get("FNS")
                        vendor_sku_map[sku] = row.get("Vendor SKU Codes")
                        brand_map[sku] = row.get("Brand")
                        manager_map[sku] = row.get("Brand Manager")
                        product_map[sku] = row.get("Product Name")
                        cp_map[sku] = row.get("CP", 0)
                
                del pm_df
                gc.collect()

        # 3. Process Inventory in Chunks
        inventory_agg = {} # SKU -> Stock
        if inv_path:
            with st.spinner("Processing Inventory (Disk)..."):
                is_excel = inv_path.endswith(('.xlsx', '.xls'))
                if is_excel:
                    df = pd.read_excel(inv_path, usecols=INV_COLS)
                    df["sku"] = df["sku"].astype(str).str.replace("`", "", regex=False).str.strip()
                    for sku, stock in df.groupby("sku")["old_quantity"].sum().items():
                        inventory_agg[sku] = inventory_agg.get(sku, 0) + float(stock)
                    del df
                else:
                    for chunk in pd.read_csv(inv_path, chunksize=chunk_size, usecols=INV_COLS, dtype={"old_quantity": "float32"}):
                        chunk["sku"] = chunk["sku"].astype(str).str.replace("`", "", regex=False).str.strip()
                        chunk_agg = chunk.groupby("sku")["old_quantity"].sum().to_dict()
                        for sku, stock in chunk_agg.items():
                            inventory_agg[sku] = inventory_agg.get(sku, 0) + stock
                        del chunk
                        gc.collect()

        # 4. Assemble Reports
        all_skus = set(sales_agg.keys()) | set(inventory_agg.keys())
        records = []
        for sku in all_skus:
            sale_qty = sales_agg.get(sku, 0)
            stock_qty = inventory_agg.get(sku, 0)
            cp = cp_map.get(sku, 0)
            if not isinstance(cp, (int, float)) or pd.isna(cp):
                cp = 0
                
            records.append({
                "SKU": sku,
                "FNS": fsn_map.get(sku),
                "Vendor SKU Codes": vendor_sku_map.get(sku),
                "Brand": brand_map.get(sku),
                "Brand Manager": manager_map.get(sku),
                "Product Name": product_map.get(sku),
                "Sales Qty": sale_qty,
                "Stock": stock_qty,
                "CP": cp,
                "CP as Per Sales Qty": cp * sale_qty,
                "CP as Per Stock": cp * stock_qty
            })
        
        full_df = pd.DataFrame(records)
        del records
        
        # Split into required reports
        sales_report = full_df[full_df["Sales Qty"] > 0][[
            "SKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager",
            "Product Name", "Sales Qty", "CP", "Stock", "CP as Per Sales Qty"
        ]].copy()

        inventory_report = full_df[full_df["Stock"] > 0][[
            "SKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager",
            "Product Name", "Stock", "Sales Qty", "CP", "CP as Per Stock", "CP as Per Sales Qty"
        ]].rename(columns={"SKU": "sku"}).copy()
        
        del full_df
        gc.collect()
        
        return sales_report, inventory_report
        
    finally:
        # ABSOLUTELY CLEAN UP DISK
        for p in [sales_path, pm_path, inv_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass
        gc.collect()

if sales_file and pm_file and inventory_file and generate_button:
    try:
        container = st.container()
        
        # Process data sequentially
        sales_report, inventory_report = process_flipkart_data(sales_file, pm_file, inventory_file)
        
        st.success("✅ Reports generated successfully!")
        
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
