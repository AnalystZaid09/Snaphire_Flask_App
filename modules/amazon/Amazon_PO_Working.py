import streamlit as st
import pandas as pd
import numpy as np
import os
from io import BytesIO

# Page configuration
st.set_page_config(
    page_title="Amazon PO Working Analysis",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

from common.ui_utils import (
    apply_professional_style, 
    save_module_reports_on_generate, 
    download_module_report,
    render_header
)

# Apply professional styling
apply_professional_style()


# Custom CSS
st.markdown("""
    <style>
    .main {
        background: linear-gradient(to bottom right, #EBF4FF, #E0E7FF);
    }
    .stAlert {
        background-color: #EBF4FF;
    }
    </style>
""", unsafe_allow_html=True)

# Header
render_header("📦 Amazon Po Working Analysis Dashboard", "Upload your files and analyze inventory, sales, and RIS data")

st.divider()

# Initialize session state
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'business_pivot' not in st.session_state:
    st.session_state.business_pivot = None

# Sidebar for file uploads
with st.sidebar:
    st.header("📁 Upload Files")
    
    role = st.selectbox("Select Role", ["Portal", "Manager"])
    
    if role == "Portal":
        business_report_file = st.file_uploader(
            "Business Report CSV", 
            type=['csv'],
            help="BusinessReport.csv",
            key="am_business"
        )
        
        pm_file = st.file_uploader(
            "Purchase Master (PM.xlsx)", 
            type=['xlsx', 'xls'],
            help="Contains ASIN, SKU, Brand information",
            key="am_pm"
        )
        
        inventory_file = st.file_uploader(
            "Inventory CSV", 
            type=['csv'],
            help="Current stock levels from Amazon",
            key="am_inv"
        )
        
        ris_file = st.file_uploader(
            "RIS Data (processed_ris_data.xlsx)", 
            type=['xlsx', 'xls'],
            help="Regional Inventory Storage data",
            key="am_ris"
        )
        
        state_fc_file = st.file_uploader(
            "State FC Cluster (Excel)", 
            type=['xlsx', 'xls'],
            help="Fulfillment center to state mapping",
            key="am_fc"
        )
        
    else:  # Manager
        business_report_file = st.file_uploader(
            "Business Report", 
            type=['csv'],
            help="Business Report File",
            key="m_business"
        )
        
        pm_file = st.file_uploader(
            "PM FILE", 
            type=['xlsx', 'xls'],
            help="PM File",
            key="m_pm"
        )
        
        inventory_file = st.file_uploader(
            "Inventory file", 
            type=['csv'],
            help="Inventory File",
            key="m_inv"
        )
        
        ris_file = st.file_uploader(
            "Manager RIS processed file", 
            type=['xlsx', 'xls'],
            help="Manager RIS Processed File",
            key="m_ris"
        )
        
        # State FC File not needed for Manager
        state_fc_file = None
    
    st.divider()
    
    days = st.number_input(
        "Number of Days for Analysis",
        min_value=1,
        max_value=365,
        value=90,
        help="Used to calculate DRR and DOC"
    )
    
    st.divider()
    
    process_button = st.button("🔄 Process Data", type="primary", use_container_width=True)

# Main processing logic
if process_button:
    # Determine required files based on role
    required_files = [business_report_file, pm_file, inventory_file, ris_file]
    if role == "Portal":
        required_files.append(state_fc_file)
        
    if not all(required_files):
        st.error("⚠️ Please upload all required files!")
    else:
        try:
            with st.spinner("Processing data... Please wait..."):
                # Load Business Report
                business_report = pd.read_csv(business_report_file)
                
                # Clean and prepare data
                business_report["Total Order Items"] = (
                    business_report["Total Order Items"]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .astype(float)
                )
                
                business_report["Total Order Items - B2B"] = (
                    business_report["Total Order Items - B2B"]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .astype(float)
                )
                
                # Create Business Pivot
                business_pivot = pd.pivot_table(
                    business_report,
                    index=["SKU", "(Child) ASIN"],
                    values=["Total Order Items", "Total Order Items - B2B"],
                    aggfunc="sum"
                ).reset_index()
                
                business_pivot["Total Sales"] = (
                    business_pivot["Total Order Items"] + 
                    business_pivot["Total Order Items - B2B"]
                )
                
                # Load PM file
                pm = pd.read_excel(pm_file)
                
                # Map PM data
                vendor_sku_map = pm.set_index("ASIN")["Vendor SKU Codes"].to_dict()
                brand_map = pm.set_index("ASIN")["Brand"].to_dict()
                brand_manager_map = pm.set_index("ASIN")["Brand Manager"].to_dict()
                
                business_pivot["Vendor SKU Codes"] = business_pivot["(Child) ASIN"].map(vendor_sku_map)
                business_pivot["Brand"] = business_pivot["(Child) ASIN"].map(brand_map)
                business_pivot["Brand Manager"] = business_pivot["(Child) ASIN"].map(brand_manager_map)
                
                # Load Inventory
                inventory = pd.read_csv(inventory_file)
                
                inventory["afn-fulfillable-quantity"] = pd.to_numeric(
                    inventory["afn-fulfillable-quantity"], errors="coerce"
                ).fillna(0)
                
                inventory["afn-reserved-quantity"] = pd.to_numeric(
                    inventory["afn-reserved-quantity"], errors="coerce"
                ).fillna(0)
                
                inventory_pivot = pd.pivot_table(
                    inventory,
                    index="asin",
                    values=["afn-fulfillable-quantity", "afn-reserved-quantity"],
                    aggfunc="sum"
                ).reset_index()
                
                inventory_pivot["Total Stock"] = (
                    inventory_pivot["afn-fulfillable-quantity"] +
                    inventory_pivot["afn-reserved-quantity"]
                )
                
                # Map inventory data
                afn_fulfillable_lookup = inventory_pivot.set_index("asin")["afn-fulfillable-quantity"].to_dict()
                afn_reserved_lookup = inventory_pivot.set_index("asin")["afn-reserved-quantity"].to_dict()
                stock_lookup = inventory_pivot.set_index("asin")["Total Stock"].to_dict()
                
                business_pivot["afn-fulfillable-quantity"] = business_pivot["(Child) ASIN"].map(afn_fulfillable_lookup)
                business_pivot["afn-reserved-quantity"] = business_pivot["(Child) ASIN"].map(afn_reserved_lookup)
                business_pivot["Total Stock"] = business_pivot["(Child) ASIN"].map(stock_lookup)
                
                # Calculate DRR and DOC
                business_pivot["DRR"] = business_pivot["Total Sales"] / days
                business_pivot["DRR"] = business_pivot["DRR"].replace(0, 0.0001)
                business_pivot["DOC"] = business_pivot["Total Stock"] / business_pivot["DRR"]
                business_pivot["DRR"] = business_pivot["DRR"].round(2)
                business_pivot["DOC"] = business_pivot["DOC"].round(1)
                
                # Load RIS Data
                ris_data = pd.read_excel(ris_file)
                
                if role == "Portal":
                    ris_data["Shipped Quantity"] = pd.to_numeric(
                        ris_data["Shipped Quantity"], errors="coerce"
                    ).fillna(0)
                    
                    asin_fc_ris_pivot = pd.pivot_table(
                        ris_data,
                        index=["ASIN", "FC Cluster"],
                        columns="RIS Status",
                        values="Shipped Quantity",
                        aggfunc="sum",
                        fill_value=0
                    ).reset_index()
                    
                    # RIS High Cluster (sorted by RIS descending)
                    if "RIS" in asin_fc_ris_pivot.columns:
                        ris_high = asin_fc_ris_pivot.sort_values("RIS", ascending=True)
                        ris_high_cluster_map = ris_high.set_index("ASIN")["FC Cluster"].to_dict()
                        ris_qty_map = ris_high.set_index("ASIN")["RIS"].to_dict()
                        
                        business_pivot["RIS Cluster"] = business_pivot["(Child) ASIN"].map(ris_high_cluster_map)
                        business_pivot["RIS Qty"] = business_pivot["(Child) ASIN"].map(ris_qty_map)
                        business_pivot["RIS Qty"] = business_pivot["RIS Qty"].fillna(0)
                        business_pivot["RIS Cluster"] = business_pivot["RIS Cluster"].fillna("")
                    
                    # RIS Low Cluster (sorted by Non RIS descending)
                    if "Non RIS" in asin_fc_ris_pivot.columns:
                        ris_low = asin_fc_ris_pivot.sort_values("Non RIS", ascending=True)
                        ris_low_cluster_map = ris_low.set_index("ASIN")["FC Cluster"].to_dict()
                        ris_low_qty_map = ris_low.set_index("ASIN")["Non RIS"].to_dict()
                        
                        business_pivot["Non RIS Cluster"] = business_pivot["(Child) ASIN"].map(ris_low_cluster_map)
                        business_pivot["Non RIS Qty"] = business_pivot["(Child) ASIN"].map(ris_low_qty_map)
                        business_pivot["Non RIS Qty"] = business_pivot["Non RIS Qty"].fillna(0)
                        business_pivot["Non RIS Cluster"] = business_pivot["Non RIS Cluster"].fillna("")
                        
                else: # Manager
                    # Normalize columns to handle variations
                    ris_data.columns = ris_data.columns.str.strip()
                    
                    # Handle specific column renaming if needed
                    col_map = {
                        "Non RIS": "non_ris",
                        "non ris": "non_ris",
                        "RIS Units": "ris_units",
                        "Total Units": "total_units",
                        "ASIN": "asin", # Normalize ASIN to asin
                        "Asin": "asin"
                    }
                    ris_data = ris_data.rename(columns=col_map)
                    
                    # Clean data ensures columns exist and are numeric
                    if "ris_units" not in ris_data.columns:
                        st.error(f"Column 'ris_units' not found. Available columns: {list(ris_data.columns)}")
                        st.stop()
                    
                    # Ensure asin column exists
                    if "asin" not in ris_data.columns:
                        st.error(f"Column 'asin' (or 'ASIN') not found. Available columns: {list(ris_data.columns)}")
                        st.stop()
                        
                    ris_data["ris_units"] = pd.to_numeric(ris_data["ris_units"], errors="coerce").fillna(0)
                    
                    # Handle non_ris specifically
                    if "non_ris" not in ris_data.columns:
                        # Try to find it case-insensitive
                        found = False
                        for col in ris_data.columns:
                            if col.lower().replace(" ", "") == "nonris":
                                ris_data = ris_data.rename(columns={col: "non_ris"})
                                found = True
                                break
                        if not found:
                             st.error(f"Column 'Non RIS' (or 'non_ris') not found. Available columns: {list(ris_data.columns)}")
                             st.stop()

                    ris_data["non_ris"] = pd.to_numeric(ris_data["non_ris"], errors="coerce").fillna(0)
                    ris_data["total_units"] = pd.to_numeric(ris_data["total_units"], errors="coerce").fillna(0)
                    
                    # Normalize ASINs for mapping
                    ris_data["asin"] = ris_data["asin"].astype(str).str.strip().str.upper()
                    
                    # Create pivot: rows=asin,cust_cluster, values=sum(ris, non_ris, total)
                    manager_pivot = pd.pivot_table(
                        ris_data,
                        index=["asin", "cust_cluster"],
                        values=["ris_units", "non_ris", "total_units"],
                        aggfunc="sum"
                    ).reset_index()
                    
                    # Sort by RIS Units descending to get the top RIS cluster for each ASIN
                    ris_high = manager_pivot.sort_values("ris_units", ascending=False)
                    ris_high_dedup = ris_high.drop_duplicates(subset=["asin"], keep="first")
                    
                    ris_high_cluster_map = ris_high_dedup.set_index("asin")["cust_cluster"].to_dict()
                    ris_qty_map = ris_high_dedup.set_index("asin")["ris_units"].to_dict()
                    
                    # Ensure business_pivot keys match
                    business_pivot["_mapping_key"] = business_pivot["(Child) ASIN"].astype(str).str.strip().str.upper()
                    
                    business_pivot["RIS Cluster"] = business_pivot["_mapping_key"].map(ris_high_cluster_map)
                    business_pivot["RIS Qty"] = business_pivot["_mapping_key"].map(ris_qty_map)
                    business_pivot["RIS Qty"] = business_pivot["RIS Qty"].fillna(0)
                    business_pivot["RIS Cluster"] = business_pivot["RIS Cluster"].fillna("")

                    # For Non RIS Cluster & Qty
                    ris_low = manager_pivot.sort_values("non_ris", ascending=False)
                    ris_low_dedup = ris_low.drop_duplicates(subset=["asin"], keep="first")
                    
                    ris_low_cluster_map = ris_low_dedup.set_index("asin")["cust_cluster"].to_dict()
                    ris_low_qty_map = ris_low_dedup.set_index("asin")["non_ris"].to_dict()
                    
                    business_pivot["Non RIS Cluster"] = business_pivot["_mapping_key"].map(ris_low_cluster_map)
                    business_pivot["Non RIS Qty"] = business_pivot["_mapping_key"].map(ris_low_qty_map)
                    business_pivot["Non RIS Qty"] = business_pivot["Non RIS Qty"].fillna(0)
                    business_pivot["Non RIS Cluster"] = business_pivot["Non RIS Cluster"].fillna("")
                    
                    # Map Total Units as well (Requested implicitly by user mentioning values)
                    # We can take total units from the highest RIS cluster row, or sum of all? 
                    # Usually "Vlookup" implies taking from the same row we got the cluster from. 
                    # Let's map Total Units from the RIS High row.
                    ris_total_map = ris_high_dedup.set_index("asin")["total_units"].to_dict()
                    business_pivot["Total RIS Units"] = business_pivot["_mapping_key"].map(ris_total_map).fillna(0) # Rename to differentiate from mapped stock? Or just Total RIS File Units
                    
                    # Debugging: Check match rate
                    bp_asins = set(business_pivot["_mapping_key"].unique())
                    ris_asins = set(ris_high_cluster_map.keys())
                    matches = bp_asins.intersection(ris_asins)
                    
                    st.info(f"debug: Manager Mode. Found {len(ris_asins)} distinct ASINs in RIS File. Matched {len(matches)} with Business Report.")
                    
                    # Cleanup temp key
                    if "_mapping_key" in business_pivot.columns:
                        business_pivot = business_pivot.drop(columns=["_mapping_key"])
                
                # Load State FC mapping
                if role == "Portal":
                    state_fc = pd.read_excel(state_fc_file, sheet_name="Sheet1")
                    ris_state_map = state_fc.set_index("Cluster")["State"].to_dict()
                    
                    business_pivot["RIS State"] = business_pivot["RIS Cluster"].map(ris_state_map)
                    business_pivot["RIS State"] = business_pivot["RIS State"].fillna("")
                    
                    business_pivot["Non RIS State"] = business_pivot["Non RIS Cluster"].map(ris_state_map)
                    business_pivot["Non RIS State"] = business_pivot["Non RIS State"].fillna("")
                else:
                    # For Manager, these columns are not in the main column order, 
                    # but just in case they are referenced somewhere else or standardizing schema
                    business_pivot["RIS State"] = ""
                    business_pivot["Non RIS State"] = ""
                
                # Create PO State
                business_pivot["PO State"] = business_pivot["DOC"].apply(
                    lambda x: "Create A PO" if x <= 7 else "We have Stock"
                )
                
                # Reorder columns
                if role == "Manager":
                    column_order = [
                        "SKU", "(Child) ASIN", "Vendor SKU Codes", "Brand", "Brand Manager",
                        "Total Order Items", "Total Order Items - B2B", "Total Sales",
                        "afn-fulfillable-quantity", "afn-reserved-quantity", "Total Stock",
                        "DRR", "DOC", 
                        "RIS Qty", "RIS Cluster", "Non RIS Cluster", "Non RIS Qty", 
                        "PO State"
                    ]
                    # Note: User didn't request State columns or Total RIS Units for Manager specific view.
                    # Keeping it minimal as requested.
                else:
                    column_order = [
                        "SKU", "(Child) ASIN", "Vendor SKU Codes", "Brand", "Brand Manager",
                        "Total Order Items", "Total Order Items - B2B", "Total Sales",
                        "afn-fulfillable-quantity", "afn-reserved-quantity", "Total Stock",
                        "DRR", "DOC", "RIS Cluster", "RIS Qty", "RIS State",
                        "Non RIS Cluster", "Non RIS Qty", "Non RIS State", "PO State"
                    ]
                
                # Ensure all columns exist
                for col in column_order:
                    if col not in business_pivot.columns:
                        business_pivot[col] = 0 if "Qty" in col or "Units" in col else ""
                
                business_pivot = business_pivot[column_order]
                
                st.session_state.business_pivot = business_pivot
                st.session_state.processed = True
                
                # Auto-save reports to MongoDB
                save_module_reports_on_generate(
                    reports={
                        "Amazon PO Working Analysis": business_pivot
                    },
                    module_name="amazon"
                )
                
                st.success("✅ Data processed successfully!")
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ Error processing data: {str(e)}")
            st.exception(e)

# Display results
if st.session_state.processed and st.session_state.business_pivot is not None:
    df = st.session_state.business_pivot
    
    # Summary metrics
    st.header("📊 Summary Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Products", len(df))
    
    with col2:
        needs_po = len(df[df["PO State"] == "Create A PO"])
        st.metric("Need Purchase Order", needs_po, delta=f"{(needs_po/len(df)*100):.1f}%")
    
    with col3:
        has_stock = len(df[df["PO State"] == "We have Stock"])
        st.metric("Has Adequate Stock", has_stock, delta=f"{(has_stock/len(df)*100):.1f}%")
    
    with col4:
        avg_doc = df["DOC"].mean()
        st.metric("Avg Days of Coverage", f"{avg_doc:.1f}")
    
    st.divider()
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📋 All Products", "⚠️ Low Stock Alert", "🗺️ RIS Analysis"])
    
    with tab1:
        st.subheader("All Products Data")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            brands = ["All"] + sorted(df["Brand"].dropna().unique().tolist())
            selected_brand = st.selectbox("Filter by Brand", brands)
        
        with col2:
            managers = ["All"] + sorted(df["Brand Manager"].dropna().unique().tolist())
            selected_manager = st.selectbox("Filter by Brand Manager", managers)
        
        with col3:
            po_states = ["All", "Create A PO", "We have Stock"]
            selected_po = st.selectbox("Filter by PO State", po_states)
        
        # Apply filters
        filtered_df = df.copy()
        
        if selected_brand != "All":
            filtered_df = filtered_df[filtered_df["Brand"] == selected_brand]
        
        if selected_manager != "All":
            filtered_df = filtered_df[filtered_df["Brand Manager"] == selected_manager]
        
        if selected_po != "All":
            filtered_df = filtered_df[filtered_df["PO State"] == selected_po]
        
        st.dataframe(filtered_df, use_container_width=True, height=400)
        
        # Download button for All Products
        st.divider()
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            download_module_report(
                df=filtered_df,
                module_name="amazon",
                report_name="Amazon PO Working Analysis",
                button_label="📥 Download All Products Report (Excel)",
                key="dl_po_working_all"
            )
    
    with tab2:
        st.subheader("⚠️ Products Requiring Purchase Orders (DOC ≤ 7)")
        
        low_stock = df[df["PO State"] == "Create A PO"].sort_values("DOC")
        
        if len(low_stock) > 0:
            st.warning(f"Found {len(low_stock)} products that need purchase orders!")
            
            # Show critical items (DOC = 0)
            critical = low_stock[low_stock["DOC"] == 0]
            if len(critical) > 0:
                st.error(f"🚨 {len(critical)} products have ZERO stock!")
                # Define desired columns
                desired_cols = ["SKU", "(Child) ASIN", "Brand", "Total Stock", "DRR", "DOC", "RIS State"]
                # Intersect with available columns to avoid KeyError
                display_cols = [col for col in desired_cols if col in critical.columns]
                
                st.dataframe(
                    critical[display_cols],
                    use_container_width=True
                )
            
            st.divider()
            st.write("All Low Stock Items:")
            st.dataframe(low_stock, use_container_width=True, height=400)
            
            # Download button for Low Stock
            st.divider()
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                download_module_report(
                    df=low_stock,
                    module_name="amazon",
                    report_name="Amazon PO Working - Low Stock Alert",
                    button_label="📥 Download Low Stock Report (Excel)",
                    key="dl_po_working_low"
                )
        else:
            st.success("✅ All products have adequate stock!")
    
    with tab3:
        st.subheader("🗺️ RIS (Regional Inventory Storage) Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Top RIS Clusters (Highest RIS Quantity)**")
            ris_high_summary = df.groupby("RIS Cluster")["RIS Qty"].sum().sort_values(ascending=False).head(10)
            st.dataframe(ris_high_summary, use_container_width=True)
        
        with col2:
            st.write("**Top Non-RIS Clusters (Highest Non-RIS Quantity)**")
            ris_low_summary = df.groupby("Non RIS Cluster")["Non RIS Qty"].sum().sort_values(ascending=False).head(10)
            st.dataframe(ris_low_summary, use_container_width=True)
        
        st.divider()
        
        if "RIS State" in df.columns and df["RIS State"].any():
            st.write("**RIS by State**")
            state_summary = df.groupby("RIS State").agg({
                "RIS Qty": "sum",
                "(Child) ASIN": "count"
            }).sort_values("RIS Qty", ascending=False)
            state_summary.columns = ["Total RIS Quantity", "Number of Products"]
            st.dataframe(state_summary, use_container_width=True)
            st.divider()
        
        st.write("**Detailed RIS Data by Product**")
        
        # Dynamic column selection for RIS details
        ris_ideal_cols = ["SKU", "(Child) ASIN", "Brand", "Brand Manager", "RIS Cluster", "RIS Qty", "RIS State", "Non RIS Cluster", "Non RIS Qty", "Non RIS State"]
        ris_display_cols = [c for c in ris_ideal_cols if c in df.columns]
        
        ris_detailed = df[df["RIS Cluster"] != ""][ris_display_cols]
        st.dataframe(ris_detailed, use_container_width=True, height=300)
        
        # Download button for RIS Analysis
        st.divider()
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            download_module_report(
                df=ris_detailed,
                module_name="amazon",
                report_name="Amazon PO Working - RIS Analysis",
                button_label="📥 Download RIS Analysis Report (Excel)",
                key="dl_po_working_ris"
            )
    
else:
    # Welcome screen
    st.info("👈 Please upload all required files in the sidebar and click 'Process Data' to begin analysis.")
    
    st.markdown("""
    ### 📝 Analysis Overview
    
    This application will:
    
    1. **Calculate Key Metrics:**
       - DRR (Daily Run Rate) = Total Sales / Number of Days
       - DOC (Days of Coverage) = Total Stock / DRR
       - Identify products needing purchase orders (DOC ≤ 7)
    
    2. **RIS Analysis:**
       - Identify highest RIS clusters
       - Map regional inventory distribution
       - Analyze Non-RIS patterns
    
    3. **Generate Reports:**
       - Complete inventory analysis
       - Low stock alerts
       - Regional distribution insights
    
    ### 📂 Required Files:
    - Business Report CSV (3-month sales data)
    - Purchase Master Excel (PM.xlsx with ASIN, SKU, Brand info)
    - Inventory CSV (current stock levels)
    - RIS Data Excel (regional inventory storage)
    - State FC Cluster Excel (fulfillment center mapping)
    """)
