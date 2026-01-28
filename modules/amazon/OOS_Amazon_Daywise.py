import streamlit as st
import pandas as pd
import io

from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    auto_save_generated_reports
)

# Module name for MongoDB collection
MODULE_NAME = "amazon"
TOOL_NAME = "amazon_oos_daywise"

st.set_page_config(page_title="Amazon OOS Daywise Analysis", layout="wide")
apply_professional_style()

render_header("Amazon OOS Daywise Analysis Dashboard")

# File upload section
st.sidebar.header("Upload Files")
max_days_file = st.sidebar.file_uploader("Upload 90 Days Sales File", type=['xlsx'])
min_days_file = st.sidebar.file_uploader("Upload 15 Days Sales File", type=['xlsx'])
inventory_file = st.sidebar.file_uploader("Upload Inventory File", type=['xlsx'])
pm_file = st.sidebar.file_uploader("Upload PM File", type=['xlsx'])

# Input parameters
st.sidebar.header("Parameters")
max_days = st.sidebar.number_input("Maximum Number of Days", min_value=1, value=90)
min_days = st.sidebar.number_input("Minimum Number of Days", min_value=1, value=15)

# Process button
process_data = st.sidebar.button("Process Data", type="primary")

def normalize_dataframe(df):
    """Normalize column names and ASIN values"""
    rename_mapping = {
        'asin': 'asin', 'ASIN': 'asin',
        'quantity': 'quantity', 'Quantity': 'quantity',
        'product-name': 'product-name', 'Product Name': 'product-name',
        'item-price': 'item-price', 'Item Price': 'item-price',
        'order-status': 'order-status', 'Order Status': 'order-status'
    }
    current_cols = {c.lower(): c for c in df.columns}
    final_rename = {}
    for standard_col, target in rename_mapping.items():
        if standard_col.lower() in current_cols:
            final_rename[current_cols[standard_col.lower()]] = target
    
    df = df.rename(columns=final_rename)
    
    if 'asin' in df.columns:
        df['asin'] = df['asin'].astype(str).str.strip().str.upper()
    return df

def load_and_clean_sales_data(file, price_col='item-price'):
    """Load and clean sales data"""
    df = pd.read_excel(file)
    df = normalize_dataframe(df)
    
    actual_price_col = 'item-price' if 'item-price' in df.columns else price_col
    if actual_price_col in df.columns:
        df[actual_price_col] = pd.to_numeric(df[actual_price_col], errors='coerce')
        df = df[(df[actual_price_col].notna()) & (df[actual_price_col] != 0)]
        
    junk_asins = {'UNKNOW', 'UNKNOWN', 'NAN', 'N/A', '', 'NONE', '0', 'NULL'}
    if 'asin' in df.columns:
        df = df[~df['asin'].astype(str).str.upper().isin(junk_asins)]
    
    if 'quantity' in df.columns:
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        
    df.reset_index(drop=True, inplace=True)
    return df

def create_sales_report(day_max, day_min, PM, Inventory, max_days, min_days):
    """Create sales report dataframe"""
    PM = normalize_dataframe(PM)
    Inventory = normalize_dataframe(Inventory)

    all_asins = day_max['asin'].dropna().unique().tolist()
    df_new = pd.DataFrame({'ASIN': all_asins})
    
    df_pm_lookup = PM.iloc[:, [0, 6]].copy()
    df_pm_lookup.columns = ['ASIN', 'Brand']
    df_pm_lookup = df_pm_lookup.drop_duplicates(subset='ASIN', keep='first')
    df_new['Brand'] = df_new['ASIN'].map(df_pm_lookup.set_index('ASIN')['Brand'])
    
    pm_names = PM.set_index(PM.columns[0])[PM.columns[7]].to_dict()
    sales_names = day_max.set_index('asin')['product-name'].to_dict()
    inv_names = Inventory.set_index('asin')['product-name'].to_dict()
    full_product_map = {**inv_names, **sales_names, **pm_names}
    df_new['Product'] = df_new['ASIN'].map(full_product_map)
    
    asin_qty_sum = day_max.groupby('asin')['quantity'].sum()
    df_new['Sale last Max days'] = df_new['ASIN'].map(asin_qty_sum).fillna(0)
    df_new['DRR Max days'] = (df_new['Sale last Max days'] / max_days).round(2)
    
    asin_sales_sum = day_min.groupby('asin')['quantity'].sum()
    df_new['Sale last Min days'] = df_new['ASIN'].map(asin_sales_sum).fillna(0)
    df_new['DRR Min days'] = (df_new['Sale last Min days'] / min_days).round(2)
    
    inv_summed = Inventory.groupby('asin')[['afn-fulfillable-quantity', 'afn-reserved-quantity']].sum()
    df_new['SIH'] = df_new['ASIN'].map(inv_summed['afn-fulfillable-quantity']).fillna(0)
    df_new['Reserved Stock'] = df_new['ASIN'].map(inv_summed['afn-reserved-quantity']).fillna(0)
    df_new['Total Stock'] = df_new['SIH'] + df_new['Reserved Stock']
    
    df_pm_lookup_cp = PM.iloc[:, [0, 9]].copy()
    df_pm_lookup_cp.columns = ['ASIN', 'CP']
    df_pm_lookup_cp = df_pm_lookup_cp.drop_duplicates(subset='ASIN', keep='first')
    df_new['CP'] = df_new['ASIN'].map(df_pm_lookup_cp.set_index('ASIN')['CP']).fillna(0)
    
    df_new['Total Value'] = df_new["Total Stock"] * df_new["CP"]
    
    df_pm_lookup_mgr = PM.iloc[:, [0, 4]].copy()
    df_pm_lookup_mgr.columns = ['ASIN', 'Manager']
    df_pm_lookup_mgr = df_pm_lookup_mgr.drop_duplicates(subset='ASIN', keep='first')
    df_new['Manager'] = df_new['ASIN'].map(df_pm_lookup_mgr.set_index('ASIN')['Manager'])
    
    return df_new

def create_inventory_report(Inventory, PM, df_new, max_days, min_days):
    """Create inventory report dataframe"""
    Inventory_pivot = Inventory.pivot_table(
        index=["asin", "sku"],
        values=["afn-fulfillable-quantity", "afn-reserved-quantity"],
        aggfunc="sum"
    )
    Inventory_pivot.reset_index(inplace=True)
    Inventory_pivot["Total Stock"] = Inventory_pivot["afn-fulfillable-quantity"] + Inventory_pivot["afn-reserved-quantity"]
    
    Inventory_pivot = Inventory_pivot.merge(PM, left_on="asin", right_on=PM.columns[0], how="left")
    
    cols_to_keep = ['asin', 'sku', 'afn-fulfillable-quantity', 'afn-reserved-quantity', 'Total Stock']
    
    Inventory_pivot["Vendor SKU Codes"] = Inventory_pivot.iloc[:, 1 + 5]
    pm_cols = PM.columns.tolist()
    
    target_cols = {
        'Vendor SKU Codes': pm_cols[1] if len(pm_cols) > 1 else None,
        'Brand Manager': pm_cols[4] if len(pm_cols) > 4 else None,
        'Brand': pm_cols[6] if len(pm_cols) > 6 else None,
        'Product Name': pm_cols[7] if len(pm_cols) > 7 else None,
        'CP': pm_cols[9] if len(pm_cols) > 9 else None
    }
    
    for label, col_name in target_cols.items():
        if col_name:
            Inventory_pivot[label] = Inventory_pivot[col_name]
    
    final_cols = ['asin', 'sku', 'Vendor SKU Codes', 'Brand Manager', 'Brand',
                  'Product Name', 'afn-fulfillable-quantity', 'afn-reserved-quantity',
                  'Total Stock', 'CP']
    Inventory_pivot = Inventory_pivot[[c for c in final_cols if c in Inventory_pivot.columns]]
    
    df_new_indexed = df_new.set_index("ASIN")
    Inventory_pivot["Sales last Max days"] = Inventory_pivot["asin"].map(df_new_indexed["Sale last Max days"]).fillna(0)
    Inventory_pivot["DRR Max"] = (Inventory_pivot["Sales last Max days"] / max_days).round(2)
    
    Inventory_pivot["Sales last Min days"] = Inventory_pivot["asin"].map(df_new_indexed["Sale last Min days"]).fillna(0)
    Inventory_pivot["DRR Min"] = (Inventory_pivot["Sales last Min days"] / min_days).round(2)
    
    return Inventory_pivot

# Main processing logic
if process_data and all([max_days_file, min_days_file, inventory_file, pm_file]):
    with st.spinner('Processing data...'):
        try:
            day_max = load_and_clean_sales_data(max_days_file)
            day_min = load_and_clean_sales_data(min_days_file)
            Inventory = pd.read_excel(inventory_file)
            PM = pd.read_excel(pm_file)
            
            sales_report = create_sales_report(day_max, day_min, PM, Inventory, max_days, min_days)
            inventory_report = create_inventory_report(Inventory, PM, sales_report, max_days, min_days)
            
            st.session_state['processed'] = True
            
            # Auto-save all generated reports to MongoDB
            all_reports = {
                "OOS Daywise Sales Report": sales_report,
                "OOS Daywise Inventory Report": inventory_report
            }
            auto_save_generated_reports(all_reports, MODULE_NAME, tool_name=TOOL_NAME)
            
            st.success('✅ Data processed successfully!')
            
        except Exception as e:
            st.error(f'❌ Error processing data: {str(e)}')
            st.session_state['processed'] = False
            st.exception(e)

elif process_data:
    st.warning('⚠️ Please upload all required files before processing.')

# Display results in tabs
if st.session_state.get('processed', False):
    tab1, tab2 = st.tabs(["📈 Sales Report", "📦 Inventory Report"])
    
    with tab1:
        st.header("Sales Report")
        sales_df = st.session_state['sales_report']
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Products", len(sales_df))
        with col2:
            st.metric("Total Sales (Max)", f"{sales_df['Sale last Max days'].sum():,.0f}")
        with col3:
            st.metric("Total Sales (Min)", f"{sales_df['Sale last Min days'].sum():,.0f}")
        with col4:
            st.metric("Total Stock Value", f"₹{sales_df['Total Value'].sum():,.2f}")
        
        st.dataframe(sales_df, use_container_width=True, height=500)
        
        download_module_report(
            df=sales_df,
            module_name=MODULE_NAME,
            report_name="OOS Daywise Sales Report",
            button_label="📥 Download Sales Report",
            key="dl_oos_sales",
            tool_name=TOOL_NAME
        )
    
    with tab2:
        st.header("Inventory Report")
        inventory_df = st.session_state['inventory_report']
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total SKUs", len(inventory_df))
        with col2:
            st.metric("Total Fulfillable", f"{inventory_df['afn-fulfillable-quantity'].sum():,.0f}")
        with col3:
            st.metric("Total Reserved", f"{inventory_df['afn-reserved-quantity'].sum():,.0f}")
        with col4:
            st.metric("Total Stock", f"{inventory_df['Total Stock'].sum():,.0f}")
        
        st.dataframe(inventory_df, use_container_width=True, height=500)
        
        download_module_report(
            df=inventory_df,
            module_name=MODULE_NAME,
            report_name="OOS Daywise Inventory Report",
            button_label="📥 Download Inventory Report",
            key="dl_oos_inventory",
            tool_name=TOOL_NAME
        )
else:
    st.info("👆 Upload all required files and click 'Process Data' to generate reports.")
    
    with st.expander("ℹ️ Instructions"):
        st.markdown("""
        ### How to use this application:
        
        1. **Upload Files** (in the sidebar):
           - 90 Days Sales File
           - 15 Days Sales File
           - Inventory File
           - PM File
        
        2. **Set Parameters**:
           - Maximum Number of Days (default: 90)
           - Minimum Number of Days (default: 15)
        
        3. **Click 'Process Data'** to generate reports
        
        4. **View Results**:
           - Sales Report tab
           - Inventory Report tab
        
        5. **Download Reports** using the download buttons
        """)
