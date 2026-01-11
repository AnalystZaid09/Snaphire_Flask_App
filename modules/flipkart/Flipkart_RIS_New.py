import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "flipkart"

# Page configuration
st.set_page_config(
    page_title="Flipkart RIS Analysis Dashboard",
    page_icon="📊",
    layout="wide"
)
apply_professional_style()

# Custom CSS for better styling
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# Title
render_header("Flipkart RIS Analysis Dashboard", "Analyze your Flipkart sales data and RIS status")
st.divider()

# Helper function to convert DataFrame to Excel
def to_excel(df, sheet_name='Sheet1'):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

# Initialize session state
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'sales_report' not in st.session_state:
    st.session_state.sales_report = None

# Sidebar for file uploads
with st.sidebar:
    st.header("📁 Upload Files")
    st.markdown("Upload the required Excel files:")
    
    sales_file = st.file_uploader(
        "1. Sales Report",
        type=['xlsx', 'xls'],
        help="Upload your Flipkart Sales Report Excel file"
    )
    
    state_fc_file = st.file_uploader(
        "2. State FC Mapping",
        type=['xlsx', 'xls'],
        help="Upload the Flipkart State FC Excel file"
    )
    
    pm_file = st.file_uploader(
        "3. Purchase Master",
        type=['xlsx', 'xls'],
        help="Upload the Flipkart PM Excel file"
    )
    
    st.divider()
    
    if st.button("🚀 Process Data", type="primary", use_container_width=True):
        if sales_file and state_fc_file and pm_file:
            with st.spinner("Processing data... Please wait..."):
                try:
                    # Read files
                    Sales_Report = pd.read_excel(sales_file, sheet_name="Sales Report")
                    State_FC = pd.read_excel(state_fc_file)
                    PM = pd.read_excel(pm_file)

                    # Remove rows where Event Type is Return
                    if "Event Type" in Sales_Report.columns:
                        Sales_Report = Sales_Report[~Sales_Report["Event Type"].astype(str).str.upper().str.contains("RETURN")]
                    
                    # Process State mapping
                    warehouse_to_state = (
                        State_FC.drop_duplicates(subset=["Warehouse ID"])
                        .set_index("Warehouse ID")["State"]
                        .to_dict()
                    )
                    
                    Sales_Report["State"] = Sales_Report["Warehouse ID"].map(warehouse_to_state)
                    
                    # Clean and standardize state names
                    Sales_Report["State"] = Sales_Report["State"].astype(str).str.upper().str.strip()
                    Sales_Report["Customer's Delivery State"] = (
                        Sales_Report["Customer's Delivery State"]
                        .astype(str)
                        .str.upper()
                        .str.strip()
                    )
                    
                    # Handle Haryana/Delhi variants
                    haryana_variants = {"HARYANA", "DELHI", "NEW DELHI", "DL"}
                    delhi_variants = {"HARYANA", "DELHI", "NEW DELHI", "DL"}
                    
                    mask_haryana = (
                        (Sales_Report["State"] == "HARYANA") &
                        (Sales_Report["Customer's Delivery State"].isin(haryana_variants))
                    )
                    Sales_Report.loc[mask_haryana, "State"] = "HARYANA"
                    
                    mask_delhi = (
                        (Sales_Report["State"] == "DELHI") &
                        (Sales_Report["Customer's Delivery State"].isin(delhi_variants))
                    )
                    Sales_Report.loc[mask_delhi, "State"] = "DELHI"
                    
                    # Calculate RIS Status
                    Sales_Report["RIS Status"] = np.where(
                        Sales_Report["State"] == Sales_Report["Customer's Delivery State"],
                        "RIS",
                        "Non RIS"
                    )
                    
                    # Clean FSN, SKU, Product Title columns
                    cols_to_clean = ["Product Title/Description", "FSN", "SKU"]
                    for col in cols_to_clean:
                        Sales_Report[col] = (
                            Sales_Report[col]
                            .astype(str)
                            .str.strip()
                            .str.strip('"')
                        )
                    
                    # Map Product Master data
                    Sales_Report["FSN"] = Sales_Report["FSN"].astype(str).str.strip()
                    PM["FNS"] = PM["FNS"].astype(str).str.strip()
                    
                    vendor_sku_map = PM.drop_duplicates("FNS").set_index("FNS")["Vendor SKU Codes"].to_dict()
                    brand_map = PM.drop_duplicates("FNS").set_index("FNS")["Brand"].to_dict()
                    manager_map = PM.drop_duplicates("FNS").set_index("FNS")["Brand Manager"].to_dict()
                    
                    Sales_Report["Vendor SKU Codes"] = Sales_Report["FSN"].map(vendor_sku_map)
                    Sales_Report["Brand"] = Sales_Report["FSN"].map(brand_map)
                    Sales_Report["Manager"] = Sales_Report["FSN"].map(manager_map)
                    
                    # Create Pivot Tables
                    # 1. Brand Pivot
                    brand_pivot = pd.pivot_table(
                        Sales_Report,
                        index="Brand",
                        columns="RIS Status",
                        values="Item Quantity",
                        aggfunc="sum",
                        fill_value=0,
                        margins=True,
                        margins_name="Grand Total"
                    )
                    brand_pivot["RIS%"] = ((brand_pivot.get("RIS", 0) / brand_pivot["Grand Total"]) * 100).round(2)
                    brand_pivot["Non RIS%"] = ((brand_pivot.get("Non RIS", 0) / brand_pivot["Grand Total"]) * 100).round(2)
                    
                    # 2. FSN-Brand Pivot
                    FSN_Brand_pivot = pd.pivot_table(
                        Sales_Report,
                        index=["FSN", "Brand"],
                        columns="RIS Status",
                        values="Item Quantity",
                        aggfunc="sum",
                        fill_value=0,
                        margins=True,
                        margins_name="Grand Total"
                    )
                    FSN_Brand_pivot["RIS%"] = ((FSN_Brand_pivot.get("RIS", 0) / FSN_Brand_pivot["Grand Total"]) * 100).round(2)
                    FSN_Brand_pivot["Non RIS%"] = ((FSN_Brand_pivot.get("Non RIS", 0) / FSN_Brand_pivot["Grand Total"]) * 100).round(2)
                    
                    # 3. State Pivot
                    State_Wise_pivot = pd.pivot_table(
                        Sales_Report,
                        index="State",
                        columns="RIS Status",
                        values="Item Quantity",
                        aggfunc="sum",
                        fill_value=0,
                        margins=True,
                        margins_name="Grand Total"
                    )
                    State_Wise_pivot["RIS%"] = ((State_Wise_pivot.get("RIS", 0) / State_Wise_pivot["Grand Total"]) * 100).round(2)
                    State_Wise_pivot["Non RIS%"] = ((State_Wise_pivot.get("Non RIS", 0) / State_Wise_pivot["Grand Total"]) * 100).round(2)
                    
                    # 4. State-Brand Pivot
                    State_Brand_pivot = pd.pivot_table(
                        Sales_Report,
                        index=["Brand", "State"],
                        columns="RIS Status",
                        values="Item Quantity",
                        aggfunc="sum",
                        fill_value=0,
                        margins=True,
                        margins_name="Grand Total"
                    )
                    State_Brand_pivot["RIS%"] = ((State_Brand_pivot.get("RIS", 0) / State_Brand_pivot["Grand Total"]) * 100).round(2)
                    State_Brand_pivot["Non RIS%"] = ((State_Brand_pivot.get("Non RIS", 0) / State_Brand_pivot["Grand Total"]) * 100).round(2)
                    
                    # Store in session state
                    st.session_state.sales_report = Sales_Report
                    st.session_state.brand_pivot = brand_pivot
                    st.session_state.fsn_brand_pivot = FSN_Brand_pivot
                    st.session_state.state_pivot = State_Wise_pivot
                    st.session_state.state_brand_pivot = State_Brand_pivot
                    st.session_state.processed = True
                    
                    st.success("✅ Data processed successfully!")
                    
                    # Auto-log key reports to MongoDB
                    from common.ui_utils import auto_log_reports
                    auto_log_reports({
                        "Brand RIS Analysis": brand_pivot,
                        "State RIS Analysis": State_Wise_pivot
                    }, "flipkart")
                    
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error processing data: {str(e)}")
        else:
            st.error("⚠️ Please upload all three files before processing!")

# Main content area
if not st.session_state.processed:
    st.info("👈 Please upload the required files from the sidebar and click 'Process Data' to begin.")
    
    # Show instructions
    with st.expander("📖 Instructions", expanded=True):
        st.markdown("""
        ### How to use this dashboard:
        
        1. **Upload Files**: Use the sidebar to upload three required Excel files:
           - Sales Report (with sheet name "Sales Report")
           - State FC Mapping
           - Purchase Master (PM)
        
        2. **Process Data**: Click the "Process Data" button to analyze your data
        
        3. **View Results**: Navigate through different tabs to see:
           - Complete Sales Report with RIS status
           - Brand-wise analysis
           - FSN-level analysis
           - State-wise analysis
           - Combined State-Brand analysis
        
        4. **Download**: Use the download button on each tab to export data to Excel"""
        )

else:
    # Create tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Sales Report",
        "📈 Brand Analysis",
        "🔢 FSN-Brand Analysis",
        "🗺️ State Analysis",
        "📊 State-Brand Analysis"
    ])


    # Tab 1: Sales Report
    with tab1:
        st.header("Sales Report with RIS Status")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Orders", len(st.session_state.sales_report))
        with col2:
            ris_count = (st.session_state.sales_report["RIS Status"] == "RIS").sum()
            st.metric("RIS Orders", ris_count)
        with col3:
            non_ris_count = (st.session_state.sales_report["RIS Status"] == "Non RIS").sum()
            st.metric("Non-RIS Orders", non_ris_count)
        with col4:
            ris_percentage = (ris_count / len(st.session_state.sales_report) * 100)
            st.metric("RIS %", f"{ris_percentage:.2f}%")
        
        st.divider()
        
        # Download button using centralized utility
        download_module_report(
            df=st.session_state.sales_report,
            module_name=MODULE_NAME,
            report_name="Sales Report with RIS Status",
            button_label="📥 Download Sales Report",
            key="ris_sales_report"
        )
        
        # Display dataframe
        st.dataframe(
            st.session_state.sales_report,
            use_container_width=True,
            height=500
        )
    
    # Tab 2: Brand Analysis
    with tab2:
        st.header("Brand-wise RIS Analysis")
        
        # Summary metrics
        brand_pivot = st.session_state.brand_pivot
        total_row = brand_pivot.loc["Grand Total"]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Quantity", f"{int(total_row['Grand Total']):,}")
        with col2:
            st.metric("Total RIS", f"{int(total_row.get('RIS', 0)):,}")
        with col3:
            st.metric("Overall RIS %", f"{total_row['RIS%']:.2f}%")
        
        st.divider()
        
        # Download button using centralized utility
        download_module_report(
            df=brand_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="Brand RIS Analysis",
            button_label="📥 Download Brand Analysis",
            key="ris_brand_analysis"
        )
        
        # Display pivot table
        st.dataframe(
            brand_pivot.style.format({
                'Non RIS': '{:,.0f}',
                'RIS': '{:,.0f}',
                'Grand Total': '{:,.0f}',
                'RIS%': '{:.2f}%',
                'Non RIS%': '{:.2f}%'
            }),
            use_container_width=True,
            height=600
        )
    
    # Tab 3: FSN-Brand Analysis
    with tab3:
        st.header("FSN-Brand Level Analysis")
        
        fsn_pivot = st.session_state.fsn_brand_pivot
        
        # Download button using centralized utility
        download_module_report(
            df=fsn_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="FSN Brand RIS Analysis",
            button_label="📥 Download FSN-Brand Analysis",
            key="ris_fsn_analysis"
        )
        
        # Display pivot table
        st.dataframe(
            fsn_pivot.style.format({
                'Non RIS': '{:,.0f}',
                'RIS': '{:,.0f}',
                'Grand Total': '{:,.0f}',
                'RIS%': '{:.2f}%',
                'Non RIS%': '{:.2f}%'
            }),
            use_container_width=True,
            height=600
        )
    
    # Tab 4: State Analysis
    with tab4:
        st.header("State-wise RIS Analysis")
        
        state_pivot = st.session_state.state_pivot
        total_row = state_pivot.loc["Grand Total"]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total States", len(state_pivot) - 1)  # Exclude Grand Total
        with col2:
            st.metric("Total Quantity", f"{int(total_row['Grand Total']):,}")
        with col3:
            st.metric("Average RIS %", f"{total_row['RIS%']:.2f}%")
        
        st.divider()
        
        # Download button using centralized utility
        download_module_report(
            df=state_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="State RIS Analysis",
            button_label="📥 Download State Analysis",
            key="ris_state_analysis"
        )
        
        # Display pivot table
        st.dataframe(
            state_pivot.style.format({
                'Non RIS': '{:,.0f}',
                'RIS': '{:,.0f}',
                'Grand Total': '{:,.0f}',
                'RIS%': '{:.2f}%',
                'Non RIS%': '{:.2f}%'
            }),
            use_container_width=True,
            height=600
        )
    
    # Tab 5: State-Brand Analysis
    with tab5:
        st.header("State-Brand Combined Analysis")
        
        state_brand_pivot = st.session_state.state_brand_pivot
        
        # Download button using centralized utility
        download_module_report(
            df=state_brand_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="State Brand RIS Analysis",
            button_label="📥 Download State-Brand Analysis",
            key="ris_state_brand_analysis"
        )
        
        # Display pivot table
        st.dataframe(
            state_brand_pivot.style.format({
                'Non RIS': '{:,.0f}',
                'RIS': '{:,.0f}',
                'Grand Total': '{:,.0f}',
                'RIS%': '{:.2f}%',
                'Non RIS%': '{:.2f}%'
            }),
            use_container_width=True,
            height=600
        )

# Footer
st.divider()
st.markdown("""
    <div style='text-align: center; color: gray; padding: 20px;'>
        RIS Analysis Dashboard | Built with Streamlit
    </div>

    """, unsafe_allow_html=True)
