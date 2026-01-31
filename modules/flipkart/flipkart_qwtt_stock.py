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

def process_flipkart_data(sales_file, pm_file, inventory_file, chunk_size=50000):
    """Process Flipkart data using chunking to keep RAM usage near-zero"""
    
    # 1. Process Sales Report in Chunks
    sales_agg = {} # SKU -> Quantity
    with st.spinner("Reading Sales data in chunks..."):
        # Reset file pointer if needed
        sales_file.seek(0)
        chunks = pd.read_csv(
            sales_file, 
            usecols=["Marketplace", "SKU", "Quantity"],
            dtype={"Marketplace": "str", "SKU": "str", "Quantity": "float32"},
            chunksize=chunk_size
        )
        
        for chunk in chunks:
            # Filter only Flipkart
            chunk = chunk[chunk["Marketplace"].str.strip().str.lower() == "flipkart"]
            if not chunk.empty:
                # Aggregate into dictionary
                for _, row in chunk.iterrows():
                    sku = str(row["SKU"]).strip()
                    sales_agg[sku] = sales_agg.get(sku, 0) + row["Quantity"]
            del chunk
            gc.collect()

    # 2. Process PM File (Master lookup)
    with st.spinner("Loading Product Master..."):
        pm_file.seek(0)
        pm_cols = ["EasycomSKU", "FNS", "Vendor SKU Codes", "Brand", "Brand Manager", "Product Name", "CP"]
        if pm_file.name.endswith('.csv'):
            pm_df = pd.read_csv(pm_file, usecols=pm_cols)
        else:
            pm_df = pd.read_excel(pm_file, usecols=pm_cols)
        
        pm_df = pm_df.drop_duplicates(subset=["EasycomSKU"])
        
        # Maps for lookup
        fsn_map = pm_df.set_index("EasycomSKU")["FNS"].to_dict()
        vendor_sku_map = pm_df.set_index("EasycomSKU")["Vendor SKU Codes"].to_dict()
        brand_map = pm_df.set_index("EasycomSKU")["Brand"].to_dict()
        manager_map = pm_df.set_index("EasycomSKU")["Brand Manager"].to_dict()
        product_map = pm_df.set_index("EasycomSKU")["Product Name"].to_dict()
        cp_map = pm_df.set_index("EasycomSKU")["CP"].to_dict()
        
        del pm_df
        gc.collect()

    # 3. Process Inventory in Chunks
    inventory_agg = {} # SKU -> Stock
    with st.spinner("Reading Inventory data in chunks..."):
        inventory_file.seek(0)
        chunks = pd.read_csv(
            inventory_file,
            usecols=["sku", "old_quantity"],
            dtype={"sku": "str", "old_quantity": "float32"},
            chunksize=chunk_size
        )
        
        for chunk in chunks:
            if not chunk.empty:
                for _, row in chunk.iterrows():
                    sku = str(row["sku"]).replace("`", "").strip()
                    inventory_agg[sku] = inventory_agg.get(sku, 0) + row["old_quantity"]
            del chunk
            gc.collect()

    # 4. Assemble Reports from Aggregated Dictionaries
    # Sales Report
    sales_report_data = []
    for sku, qty in sales_agg.items():
        sales_report_data.append({
            "SKU": sku,
            "FNS": fsn_map.get(sku),
            "Vendor SKU Codes": vendor_sku_map.get(sku),
            "Brand": brand_map.get(sku),
            "Brand Manager": manager_map.get(sku),
            "Product Name": product_map.get(sku),
            "Sales Qty": qty,
            "CP": cp_map.get(sku, 0),
            "Stock": inventory_agg.get(sku, 0),
            "CP as Per Sales Qty": (cp_map.get(sku, 0) if pd.notna(cp_map.get(sku)) else 0) * qty
        })
    sales_report = pd.DataFrame(sales_report_data)
    del sales_report_data
    gc.collect()

    # Inventory Report
    inventory_report_data = []
    for sku, stock in inventory_agg.items():
        inventory_report_data.append({
            "sku": sku,
            "FNS": fsn_map.get(sku),
            "Vendor SKU Codes": vendor_sku_map.get(sku),
            "Brand": brand_map.get(sku),
            "Brand Manager": manager_map.get(sku),
            "Product Name": product_map.get(sku),
            "Stock": stock,
            "Sales Qty": sales_agg.get(sku, 0),
            "CP": cp_map.get(sku, 0),
            "CP as Per Stock": (cp_map.get(sku, 0) if pd.notna(cp_map.get(sku)) else 0) * stock,
            "CP as Per Sales Qty": (cp_map.get(sku, 0) if pd.notna(cp_map.get(sku)) else 0) * sales_agg.get(sku, 0)
        })
    inventory_report = pd.DataFrame(inventory_report_data)
    del inventory_report_data
    gc.collect()
    
    return sales_report, inventory_report

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
