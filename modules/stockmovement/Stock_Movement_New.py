import streamlit as st
import pandas as pd
import io
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    to_excel,
    auto_save_generated_reports
)

# Module name for MongoDB collection
MODULE_NAME = "stock_movement"

st.set_page_config(page_title="Stock Movement Analysis Dashboard", layout="wide")
apply_professional_style()

render_header("Stock Movement Analysis Dashboard")

# File uploaders
st.sidebar.header("Upload Files")

qwtt_inventory_file = st.sidebar.file_uploader("QWTT Inventory (Excel)", type=['xlsx'])
amazon_stock_file = st.sidebar.file_uploader("Amazon Stock (CSV)", type=['csv'])
flipkart_business_file = st.sidebar.file_uploader("Flipkart Business Report (Excel)", type=['xlsx'])
amazon_business_file = st.sidebar.file_uploader("Amazon Business Report (Excel)", type=['xlsx'])
amazon_pm_file = st.sidebar.file_uploader("Amazon PM (Excel)", type=['xlsx'])
flipkart_pm_file = st.sidebar.file_uploader("Flipkart PM (Excel)", type=['xlsx'])
flipkart_inventory_file = st.sidebar.file_uploader("Flipkart Easycom Inventory (CSV)", type=['csv'])

if all([qwtt_inventory_file, amazon_stock_file, flipkart_business_file, 
        amazon_business_file, amazon_pm_file, flipkart_pm_file, flipkart_inventory_file]):
    
    with st.spinner("Processing data..."):
        # Load data
        Qwtt_Inventory = pd.read_excel(qwtt_inventory_file)
        Amazon_Stock = pd.read_csv(amazon_stock_file)
        Flipkart_Business_Report = pd.read_excel(flipkart_business_file)
        Amazon_Business_Report = pd.read_excel(amazon_business_file)
        Amazon_PM = pd.read_excel(amazon_pm_file)
        Flipkart_PM = pd.read_excel(flipkart_pm_file)
        Flipkart_Easycom_Inventory = pd.read_csv(flipkart_inventory_file)
        
        # Process QWTT Inventory
        Qwtt_Inventory_Pivot = (
            Qwtt_Inventory
            .pivot_table(index="Asin", values="Sellable", aggfunc="sum")
            .reset_index()
            .sort_values(by="Sellable", ascending=False)
        )
        
        # Process Amazon Stock
        amazon_stock_pivot = (
            Amazon_Stock
            .pivot_table(index="asin", values="afn-warehouse-quantity", aggfunc="sum")
            .reset_index()
        )
        
        # Process Flipkart Business Report
        Flipkart_Business_Report["Final Sale Units"] = Flipkart_Business_Report["Final Sale Units"].apply(
            lambda x: 0 if x < 0 else x
        )
        
        Flipkart_Business_Pivot = (
            Flipkart_Business_Report
            .pivot_table(index="Product Id", values="Final Sale Units", aggfunc="sum")
            .reset_index()
        )
        
        # Process Amazon Business Report
        Amazon_Business_Report["Total Orders"] = (
            Amazon_Business_Report["Total Order Items"] + 
            Amazon_Business_Report["Total Order Items - B2B"]
        )
        
        amazon_business_pivot = (
            Amazon_Business_Report
            .pivot_table(index="(Parent) ASIN", values="Total Orders", aggfunc="sum")
            .reset_index()
            .sort_values(by="Total Orders", ascending=False)
        )
        
        # Clean and standardize columns
        Amazon_PM["ASIN"] = Amazon_PM["ASIN"].astype(str).str.strip().str.upper()
        Amazon_PM["Vendor SKU Codes"] = Amazon_PM["Vendor SKU Codes"].astype(str).str.strip()
        Amazon_PM["EasycomSKU"] = Amazon_PM["EasycomSKU"].astype(str).str.strip()
        
        amazon_business_pivot["(Parent) ASIN"] = (
            amazon_business_pivot["(Parent) ASIN"].astype(str).str.strip().str.upper()
        )
        amazon_business_pivot.columns = amazon_business_pivot.columns.str.strip()
        
        # Merge Amazon Business with PM
        amazon_business_pivot = amazon_business_pivot.merge(
            Amazon_PM[["ASIN", "Brand", "Brand Manager", "Product Name", 
                      "Vendor SKU Codes", "EasycomSKU", "CP"]],
            left_on="(Parent) ASIN",
            right_on="ASIN",
            how="left"
        )
        
        amazon_business_pivot = amazon_business_pivot[[
            "(Parent) ASIN", "Brand", "Brand Manager", "Product Name",
            "Vendor SKU Codes", "EasycomSKU", "Total Orders", "CP"
        ]].drop_duplicates()
        
        amazon_business_pivot["CP"] = amazon_business_pivot["CP"].fillna(0)
        amazon_business_pivot["Total Orders"] = amazon_business_pivot["Total Orders"].fillna(0)
        amazon_business_pivot["CP As Per Qty"] = (
            amazon_business_pivot["CP"] * amazon_business_pivot["Total Orders"]
        )
        
        # Add QWTT Stock to Amazon
        Qwtt_Inventory_Pivot["Asin"] = (
            Qwtt_Inventory_Pivot["Asin"].astype(str).str.strip().str.upper()
        )
        qwtt_stock_map = Qwtt_Inventory_Pivot.set_index("Asin")["Sellable"]
        amazon_business_pivot["QWTT Stock"] = (
            amazon_business_pivot["(Parent) ASIN"]
            .map(qwtt_stock_map)
            .fillna(0)
            .astype(int)
        )
        
        # Process Flipkart PM
        Flipkart_PM.columns = Flipkart_PM.columns.str.strip()
        Flipkart_Business_Pivot.columns = Flipkart_Business_Pivot.columns.str.strip()
        
        Flipkart_Business_Pivot = Flipkart_Business_Pivot.merge(
            Flipkart_PM[["FNS", "Brand", "Brand Manager", "Product Name",
                        "Vendor SKU Codes", "EasycomSKU", "CP"]],
            left_on="Product Id",
            right_on="FNS",
            how="left"
        )
        
        Flipkart_Business_Pivot = Flipkart_Business_Pivot[[
            "Product Id", "Brand", "Brand Manager", "Product Name",
            "Vendor SKU Codes", "EasycomSKU", "Final Sale Units", "CP", "FNS"
        ]].drop_duplicates()
        
        Flipkart_Business_Pivot["CP As Per Qty"] = (
            Flipkart_Business_Pivot["CP"] * Flipkart_Business_Pivot["Final Sale Units"]
        )
        
        # Add Flipkart QWTT Stock
        Flipkart_Easycom_Inventory["sku"] = (
            Flipkart_Easycom_Inventory["sku"].str.replace(r"^`", "", regex=True)
        )
        
        flipkart_inventory_pivot = (
            Flipkart_Easycom_Inventory
            .pivot_table(index="sku", values="old_quantity", aggfunc="sum")
            .reset_index()
        )
        
        flipkart_stock_map = flipkart_inventory_pivot.set_index("sku")["old_quantity"]
        Flipkart_Business_Pivot["QWTT Stock"] = (
            Flipkart_Business_Pivot["EasycomSKU"].map(flipkart_stock_map)
        )
        
        # Create Flipkart QWTT Inward
        flipkart_qwtt_inward = amazon_business_pivot.copy()
        
        flipkart_sales_map = (
            Flipkart_Business_Pivot
            .groupby("EasycomSKU")["Final Sale Units"]
            .sum()
        )
        flipkart_qwtt_inward["Flipkart Sales"] = (
            flipkart_qwtt_inward["EasycomSKU"]
            .map(flipkart_sales_map)
            .fillna(0)
            .astype(int)
        )
        
        flipkart_stock_map_inward = (
            Flipkart_Business_Pivot
            .groupby("EasycomSKU")["QWTT Stock"]
            .sum()
        )
        flipkart_qwtt_inward["Flipkart QWTT Stock"] = (
            flipkart_qwtt_inward["EasycomSKU"]
            .map(flipkart_stock_map_inward)
            .fillna(0)
            .astype(int)
        )
        
        flipkart_fns_map = (
            Flipkart_Business_Pivot
            .groupby("EasycomSKU")["FNS"]
            .sum()
        )
        flipkart_qwtt_inward["FNS"] = (
            flipkart_qwtt_inward["EasycomSKU"].map(flipkart_fns_map)
        )
        
        flipkart_qwtt_inward_filter = flipkart_qwtt_inward[
            flipkart_qwtt_inward["Flipkart QWTT Stock"] == 0
        ].reset_index(drop=True)
        
        # Create Amazon QWTT Inward
        amazon_qwtt_inward = Flipkart_Business_Pivot.copy()
        
        amazon_sales_map = (
            amazon_business_pivot
            .groupby("EasycomSKU")["Total Orders"]
            .sum()
        )
        amazon_qwtt_inward["Amazon Sales"] = (
            amazon_qwtt_inward["EasycomSKU"]
            .map(amazon_sales_map)
            .fillna(0)
            .astype(int)
        )
        
        amazon_stock_map = (
            amazon_business_pivot
            .groupby("EasycomSKU")["QWTT Stock"]
            .sum()
        )
        amazon_qwtt_inward["Amazon Stock"] = (
            amazon_qwtt_inward["EasycomSKU"]
            .map(amazon_stock_map)
            .fillna(0)
            .astype(int)
        )
        
        amazon_asin_map = (
            amazon_business_pivot
            .groupby("EasycomSKU")["(Parent) ASIN"]
            .sum()
        )
        amazon_qwtt_inward["Amazon ASIN"] = (
            amazon_qwtt_inward["EasycomSKU"].map(amazon_asin_map)
        )
        
        amazon_qwtt_inward_filter = amazon_qwtt_inward[
            amazon_qwtt_inward["Amazon Stock"] == 0
        ].reset_index(drop=True)

        # Auto-save all generated reports to MongoDB
        auto_save_generated_reports(
            reports={
                "Amazon Business Pivot": amazon_business_pivot,
                "Flipkart Business Pivot": Flipkart_Business_Pivot,
                "Flipkart QWTT Inward": flipkart_qwtt_inward,
                "Amazon QWTT Inward": amazon_qwtt_inward
            },
            module_name=MODULE_NAME
        )
    
    # Display tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Amazon Business Pivot",
        "Flipkart Business Pivot",
        "Flipkart QWTT Inward",
        "Amazon QWTT Inward"
    ])
    
    with tab1:
        st.header("Amazon Business Pivot")
        st.dataframe(amazon_business_pivot, use_container_width=True, height=600)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Products", len(amazon_business_pivot))
            st.metric("Total Orders", f"{amazon_business_pivot['Total Orders'].sum():,.0f}")
        with col2:
            st.metric("Total CP Value", f"₹{amazon_business_pivot['CP As Per Qty'].sum():,.2f}")
            st.metric("Total QWTT Stock", f"{amazon_business_pivot['QWTT Stock'].sum():,.0f}")
        
        # Download with module-specific collection saving
        download_module_report(
            df=amazon_business_pivot,
            module_name=MODULE_NAME,
            report_name="Amazon Business Pivot",
            button_label="📥 Download Amazon Business Pivot",
            key="dl_amazon_business"
        )
    
    with tab2:
        st.header("Flipkart Business Pivot")
        st.dataframe(Flipkart_Business_Pivot, use_container_width=True, height=600)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Products", len(Flipkart_Business_Pivot))
            st.metric("Total Sale Units", f"{Flipkart_Business_Pivot['Final Sale Units'].sum():,.0f}")
        with col2:
            st.metric("Total CP Value", f"₹{Flipkart_Business_Pivot['CP As Per Qty'].sum():,.2f}")
            st.metric("Total QWTT Stock", f"{Flipkart_Business_Pivot['QWTT Stock'].sum():,.0f}")
        
        download_module_report(
            df=Flipkart_Business_Pivot,
            module_name=MODULE_NAME,
            report_name="Flipkart Business Pivot",
            button_label="📥 Download Flipkart Business Pivot",
            key="dl_flipkart_business"
        )
    
    with tab3:
        st.header("Flipkart QWTT Inward")
        
        show_filter = st.checkbox("Show only products with zero Flipkart QWTT Stock", value=False)
        
        if show_filter:
            st.dataframe(flipkart_qwtt_inward_filter, use_container_width=True, height=600)
            data_to_show = flipkart_qwtt_inward_filter
        else:
            st.dataframe(flipkart_qwtt_inward, use_container_width=True, height=600)
            data_to_show = flipkart_qwtt_inward
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Products", len(data_to_show))
            st.metric("Total Amazon Orders", f"{data_to_show['Total Orders'].sum():,.0f}")
        with col2:
            st.metric("Total Flipkart Sales", f"{data_to_show['Flipkart Sales'].sum():,.0f}")
            st.metric("Total Flipkart QWTT Stock", f"{data_to_show['Flipkart QWTT Stock'].sum():,.0f}")
        
        download_module_report(
            df=data_to_show,
            module_name=MODULE_NAME,
            report_name="Flipkart QWTT Inward",
            button_label="📥 Download Flipkart QWTT Inward",
            key="dl_flipkart_inward"
        )
    
    with tab4:
        st.header("Amazon QWTT Inward")
        
        show_filter = st.checkbox("Show only products with zero Amazon Stock", value=False, key="amazon_filter")
        
        if show_filter:
            st.dataframe(amazon_qwtt_inward_filter, use_container_width=True, height=600)
            data_to_show = amazon_qwtt_inward_filter
        else:
            st.dataframe(amazon_qwtt_inward, use_container_width=True, height=600)
            data_to_show = amazon_qwtt_inward
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Products", len(data_to_show))
            st.metric("Total Flipkart Sales", f"{data_to_show['Final Sale Units'].sum():,.0f}")
        with col2:
            st.metric("Total Amazon Sales", f"{data_to_show['Amazon Sales'].sum():,.0f}")
            st.metric("Total Amazon Stock", f"{data_to_show['Amazon Stock'].sum():,.0f}")
        
        download_module_report(
            df=data_to_show,
            module_name=MODULE_NAME,
            report_name="Amazon QWTT Inward",
            button_label="📥 Download Amazon QWTT Inward",
            key="dl_amazon_inward"
        )

else:
    st.info("👈 Please upload all required files from the sidebar to begin analysis.")
    st.markdown("""
    ### Required Files:
    1. QWTT Inventory (Excel)
    2. Amazon Stock (CSV)
    3. Flipkart Business Report (Excel)
    4. Amazon Business Report (Excel)
    5. Amazon PM (Excel)
    6. Flipkart PM (Excel)
    7. Flipkart Easycom Inventory (CSV)
    """)
