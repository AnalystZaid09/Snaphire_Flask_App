import streamlit as st
import pandas as pd
import zipfile
from pathlib import Path
import io
import calendar
from ui_utils import apply_professional_style, get_download_filename, render_header

st.set_page_config(page_title="Sales Data Analysis", layout="wide", initial_sidebar_state="expanded")
apply_professional_style()

# Custom CSS for better UI
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem 0;
    }
    .filter-box {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 10px;
        margin-bottom: 1rem;
    }
    .quarter-badge {
        display: inline-block;
        padding: 0.25rem 0.5rem;
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
        font-size: 0.9rem;
        margin-left: 0.5rem;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

render_header("Sales Data Analysis Dashboard")

# File uploaders
st.sidebar.header("Upload Files")
zip_files = st.sidebar.file_uploader(
    "Upload ZIP files (B2B & B2C Reports)", 
    type=['zip'], 
    accept_multiple_files=True
)
pm_file = st.sidebar.file_uploader("Upload PM Excel File", type=['xlsx', 'xls'])

if zip_files and pm_file:
    # Process ZIP files
    @st.cache_data
    def process_zip_files(zip_file_list):
        all_dfs = []
        
        for uploaded_zip in zip_file_list:
            with zipfile.ZipFile(uploaded_zip, 'r') as z:
                for file_name in z.namelist():
                    if file_name.endswith('/'):
                        continue
                    
                    with z.open(file_name) as f:
                        if file_name.lower().endswith('.csv'):
                            df = pd.read_csv(f, low_memory=False)
                        elif file_name.lower().endswith(('.xlsx', '.xls')):
                            df = pd.read_excel(f)
                        else:
                            continue
                        
                        df['source_zip'] = uploaded_zip.name
                        df['source_file'] = file_name
                        all_dfs.append(df)
        
        combined_df = pd.concat(all_dfs, ignore_index=True)
        return combined_df
    
    @st.cache_data
    def process_data(combined_df, pm_df):
        # Filter for Shipment transactions only
        combined_df = combined_df[combined_df['Transaction Type'].str.strip().str.lower() == 'shipment'].copy()
        combined_df.reset_index(drop=True, inplace=True)
        
        # Process dates
        combined_df['Invoice Date'] = pd.to_datetime(combined_df['Invoice Date'], errors='coerce')
        combined_df['Date'] = combined_df['Invoice Date'].dt.date
        combined_df['Month'] = pd.to_datetime(combined_df['Date']).dt.month
        combined_df['Month_Name'] = pd.to_datetime(combined_df['Date']).dt.strftime('%B')
        combined_df['Month_Year'] = pd.to_datetime(combined_df['Date']).dt.strftime('%b-%y')
        combined_df['Year'] = pd.to_datetime(combined_df['Date']).dt.year
        
        # Define custom quarters
        def get_custom_quarter(month):
            if month in [1, 2, 3]:
                return 'Q1'
            elif month in [4, 5, 6]:
                return 'Q2'
            elif month in [7, 8, 9]:
                return 'Q3'
            else:
                return 'Q4'
        
        combined_df['Quarter'] = combined_df['Month'].apply(get_custom_quarter)
        combined_df['Quarter_Year'] = combined_df['Quarter'] + '-' + combined_df['Year'].astype(str)
        
        # Process PM file
        pm_df = pm_df[['ASIN', 'Brand', 'Brand Manager', 'Vendor SKU Codes', 'Product Name']]
        
        # Merge with PM data
        combined_df = combined_df.merge(
            pm_df,
            left_on='Asin',
            right_on='ASIN',
            how='left'
        )
        
        return combined_df
    
    with st.spinner("Processing files..."):
        combined_df = process_zip_files(zip_files)
        pm_df = pd.read_excel(pm_file)
        processed_df = process_data(combined_df, pm_df)
    
    st.success(f"✅ Loaded {len(processed_df):,} records")
    
    # Enhanced Sidebar filters
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎯 Time Period Filters")
    
    # Create filter box styling
    with st.sidebar.container():
        time_period = st.radio(
            "Select View Type",
            ["📅 All Data", "📆 Quarter View", "🗓️ Month View"],
            help="Choose how you want to view your data"
        )
    
    filtered_df = processed_df.copy()
    filter_info = ""
    
    if time_period == "📆 Quarter View":
        st.sidebar.markdown("---")
        
        # Get available years
        years = sorted(processed_df['Year'].dropna().unique(), reverse=True)
        selected_year = st.sidebar.selectbox(
            "📅 Select Year",
            years,
            help="Select the year for quarter analysis"
        )
        
        # Quarter selection with descriptions
        quarter_options = {
            'Q1': 'Q1 (Jan - Mar)',
            'Q2': 'Q2 (Apr - Jun)',
            'Q3': 'Q3 (Jul - Sep)',
            'Q4': 'Q4 (Oct - Dec)'
        }
        
        # Filter available quarters for selected year
        available_quarters = processed_df[processed_df['Year'] == selected_year]['Quarter'].unique()
        available_quarter_options = {k: v for k, v in quarter_options.items() if k in available_quarters}
        
        if available_quarter_options:
            selected_quarter_display = st.sidebar.selectbox(
                "📊 Select Quarter",
                list(available_quarter_options.values()),
                help="Q1: Jan-Mar | Q2: Apr-Jun | Q3: Jul-Sep | Q4: Oct-Dec"
            )
            
            # Get the quarter code (Q1, Q2, Q3, Q4)
            selected_quarter = [k for k, v in quarter_options.items() if v == selected_quarter_display][0]
            
            filtered_df = processed_df[
                (processed_df['Quarter'] == selected_quarter) & 
                (processed_df['Year'] == selected_year)
            ]
            
            # Define month ranges
            quarter_months = {
                'Q1': ['January', 'February', 'March'],
                'Q2': ['April', 'May', 'June'],
                'Q3': ['July', 'August', 'September'],
                'Q4': ['October', 'November', 'December']
            }
            
            filter_info = f"**{selected_quarter} {selected_year}** ({', '.join(quarter_months[selected_quarter])})"
            
            # Show summary for quarter
            st.sidebar.markdown("---")
            st.sidebar.markdown("#### Quarter Summary")
            st.sidebar.metric("Total Records", f"{len(filtered_df):,}")
            st.sidebar.metric("Date Range", f"{filtered_df['Date'].min()} to {filtered_df['Date'].max()}")
        else:
            st.sidebar.warning(f"No data available for {selected_year}")
    
    elif time_period == "🗓️ Month View":
        st.sidebar.markdown("---")
        
        # Get available years
        years = sorted(processed_df['Year'].dropna().unique(), reverse=True)
        selected_year = st.sidebar.selectbox(
            "📅 Select Year",
            years,
            help="Select the year for month analysis"
        )
        
        # Get available months for selected year
        year_data = processed_df[processed_df['Year'] == selected_year]
        available_months = sorted(year_data['Month'].dropna().unique())
        month_names = [calendar.month_name[m] for m in available_months]
        
        if month_names:
            selected_month_name = st.sidebar.selectbox(
                "📊 Select Month",
                month_names,
                help="Choose a specific month to analyze"
            )
            
            # Get month number
            selected_month = list(calendar.month_name).index(selected_month_name)
            
            filtered_df = processed_df[
                (processed_df['Month'] == selected_month) & 
                (processed_df['Year'] == selected_year)
            ]
            
            filter_info = f"**{selected_month_name} {selected_year}**"
            
            # Show summary for month
            st.sidebar.markdown("---")
            st.sidebar.markdown("#### Month Summary")
            st.sidebar.metric("Total Records", f"{len(filtered_df):,}")
            st.sidebar.metric("Date Range", f"{filtered_df['Date'].min()} to {filtered_df['Date'].max()}")
        else:
            st.sidebar.warning(f"No data available for {selected_year}")
    else:
        filter_info = "**All Available Data**"
    
    # Additional filters
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔍 Additional Filters")
    
    # Brand filter with count
    brands = sorted([b for b in filtered_df['Brand'].dropna().unique() if b])
    brand_counts = filtered_df['Brand'].value_counts()
    
    brand_options = ['All Brands'] + [f"{brand} ({brand_counts[brand]:,})" for brand in brands]
    selected_brand_display = st.sidebar.selectbox(
        "🏢 Filter by Brand",
        brand_options,
        help="Select a specific brand or view all brands"
    )
    
    if selected_brand_display != 'All Brands':
        selected_brand = selected_brand_display.split(' (')[0]
        filtered_df = filtered_df[filtered_df['Brand'] == selected_brand]
    
    # Brand Manager filter
    managers = sorted([m for m in filtered_df['Brand Manager'].dropna().unique() if m])
    manager_options = ['All Managers'] + managers
    selected_manager = st.sidebar.selectbox(
        "👤 Filter by Brand Manager",
        manager_options,
        help="Select a specific brand manager"
    )
    
    if selected_manager != 'All Managers':
        filtered_df = filtered_df[filtered_df['Brand Manager'] == selected_manager]
    
    # Display active filters
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📌 Active Filters")
    st.sidebar.info(f"""
    **Period:** {filter_info}
    **Brand:** {selected_brand_display.split(' (')[0]}
    **Manager:** {selected_manager}
    **Records:** {len(filtered_df):,}
    """)
    
    # Main content - Show filter summary
    st.markdown(f"### Current View: {filter_info}")
    st.markdown("---")
    
    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Summary", "🏢 Brand Analysis", "📦 ASIN Analysis", "📋 Raw Data"])
    
    with tab1:
        st.header("Summary Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Quantity", f"{filtered_df['Quantity'].sum():,.0f}")
        with col2:
            st.metric("Total Invoice Amount", f"₹{filtered_df['Invoice Amount'].sum():,.2f}")
        with col3:
            st.metric("Unique ASINs", f"{filtered_df['Asin'].nunique():,}")
        with col4:
            st.metric("Unique Brands", f"{filtered_df['Brand'].nunique():,}")
        
        st.subheader("Monthly Trend")
        monthly_trend = filtered_df.groupby('Month_Year').agg({
            'Quantity': 'sum',
            'Invoice Amount': 'sum'
        }).reset_index()
        
        # Sort by date
        monthly_trend['sort_date'] = pd.to_datetime(monthly_trend['Month_Year'], format='%b-%y')
        monthly_trend = monthly_trend.sort_values('sort_date')
        
        col1, col2 = st.columns(2)
        with col1:
            st.line_chart(monthly_trend.set_index('Month_Year')['Quantity'])
            st.caption("Quantity Trend")
        with col2:
            st.line_chart(monthly_trend.set_index('Month_Year')['Invoice Amount'])
            st.caption("Invoice Amount Trend")
    
    with tab2:
        st.header("Brand Analysis")
        
        # Brand pivot
        brand_pivot = pd.pivot_table(
            filtered_df,
            index='Brand',
            values=['Quantity', 'Invoice Amount'],
            aggfunc='sum',
            margins=False
        )
        brand_pivot = brand_pivot.sort_values(by='Quantity', ascending=False)
        brand_pivot.loc['Grand Total'] = brand_pivot.sum()
        brand_pivot = brand_pivot.reset_index()
        
        # Format numbers
        brand_pivot['Invoice Amount'] = brand_pivot['Invoice Amount'].apply(lambda x: f"₹{x:,.2f}")
        brand_pivot['Quantity'] = brand_pivot['Quantity'].apply(lambda x: f"{x:,.0f}")
        
        st.dataframe(brand_pivot, use_container_width=True, height=600)
        
        # Download button
        csv = brand_pivot.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Brand Analysis CSV",
            data=csv,
            file_name=get_download_filename(f"brand_analysis_{time_period}", "csv"),
            mime="text/csv",
        )
    
    with tab3:
        st.header("ASIN Analysis")
        
        # ASIN pivot
        asin_pivot = pd.pivot_table(
            filtered_df,
            index=['Asin', 'Brand'],
            values=['Quantity', 'Invoice Amount'],
            aggfunc='sum'
        )
        asin_pivot = asin_pivot.sort_values(by='Quantity', ascending=False)
        
        grand_total = pd.DataFrame(asin_pivot.sum()).T
        grand_total.index = pd.MultiIndex.from_tuples(
            [('Grand Total', '')],
            names=asin_pivot.index.names
        )
        asin_pivot = pd.concat([asin_pivot, grand_total])
        asin_pivot = asin_pivot.reset_index()
        
        # Format numbers
        asin_pivot['Invoice Amount'] = asin_pivot['Invoice Amount'].apply(lambda x: f"₹{x:,.2f}")
        asin_pivot['Quantity'] = asin_pivot['Quantity'].apply(lambda x: f"{x:,.0f}")
        
        st.dataframe(asin_pivot, use_container_width=True, height=600)
        
        # Download button
        csv = asin_pivot.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download ASIN Analysis CSV",
            data=csv,
            file_name=get_download_filename(f"asin_analysis_{time_period}", "csv"),
            mime="text/csv",
        )
    
    with tab4:
        st.header("Raw/Processed Data")
        
        # Select columns to display
        all_columns = filtered_df.columns.tolist()
        default_columns = ['Invoice Date', 'Asin', 'Brand', 'Product Name', 'Quantity', 
                          'Invoice Amount', 'Month_Year', 'Quarter', 'Year', 'Order Id', 'Shipment Id']
        
        selected_columns = st.multiselect(
            "Select columns to display",
            all_columns,
            default=[col for col in default_columns if col in all_columns]
        )
        
        if selected_columns:
            display_df = filtered_df[selected_columns].copy()
            st.dataframe(display_df, use_container_width=True, height=600)
            
            # Download button for raw data
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Filtered Data CSV",
                data=csv,
                file_name=get_download_filename(f"filtered_data_{time_period}", "csv"),
                mime="text/csv",
            )
        else:
            st.warning("Please select at least one column to display")

else:
    # Landing page with instructions
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div style='text-align: center; padding: 2rem;'>
            <h2>👋 Welcome to Sales Data Analysis Dashboard</h2>
            <p style='font-size: 1.1rem; color: #666;'>
                Upload your files to get started with comprehensive sales analysis
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        st.markdown("""
        ### 📋 Getting Started
        
        **Step 1:** Upload Files
        - Navigate to the sidebar (left side)
        - Upload all B2B and B2C report ZIP files
        - Upload the PM (Product Master) Excel file
        
        **Step 2:** Select Filters
        - Choose time period: All Data, Quarter, or Month
        - **Quarter Definitions:**
          - 🌱 Q1: January - March
          - ☀️ Q2: April - June  
          - 🍂 Q3: July - September
          - ❄️ Q4: October - December
        - Apply additional filters for Brand and Brand Manager
        
        **Step 3:** Analyze Data
        - View Summary statistics and trends
        - Explore Brand-wise analysis
        - Check ASIN-level details
        - Export filtered data as CSV
        
        ### ✨ Key Features
        
        | Feature | Description |
        |---------|-------------|
        | 📊 **Summary Dashboard** | Overview metrics, trends, and KPIs |
        | 🏢 **Brand Analysis** | Sales grouped by brand with totals |
        | 📦 **ASIN Analysis** | Detailed product-level breakdown |
        | 📋 **Raw Data Export** | Customizable data export options |
        | 🎯 **Smart Filters** | Quarter, Month, Brand, and Manager filters |
        
        ### 💡 Tips
        
        - Use Quarter View for quarterly business reviews
        - Use Month View for detailed monthly analysis
        - Download reports for offline analysis
        - Apply multiple filters for targeted insights
        
        """)
        
        st.markdown("---")
        
        st.info("👈 **Ready to begin?** Upload your files using the sidebar on the left!")