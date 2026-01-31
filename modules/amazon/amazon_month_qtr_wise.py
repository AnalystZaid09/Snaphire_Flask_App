import streamlit as st
import pandas as pd
import zipfile
from pathlib import Path
import io
import calendar
import gc

import base64
from datetime import datetime as dt
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style, 
    render_header, 
    download_module_report,
    auto_save_generated_reports
)

# Module name for MongoDB collection
MODULE_NAME = "amazon"
TOOL_NAME = "amazon_month_qtr_wise"

st.set_page_config(page_title="Month and Quarter Wise Sales Data Analysis", layout="wide", initial_sidebar_state="expanded")
apply_professional_style()

# Helper function to create download link (base64 approach - works reliably on Streamlit Cloud)
def create_download_link(df, filename, link_text, is_csv=False):
    """Generate a download link for a DataFrame using base64 encoding.
    Uses CSV for large files to save memory, Excel for smaller ones."""
    try:
        gc.collect()
        if is_csv or len(df) > 20000:
            # Use CSV for large files to save memory
            csv = df.to_csv(index=False)
            b64 = base64.b64encode(csv.encode()).decode()
            href = f'<a href="data:file/csv;base64,{b64}" download="{filename.replace(".xlsx", ".csv")}" style="display: inline-block; padding: 0.5rem 1rem; background-color: #2196F3; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">📥 {link_text.replace("Excel", "CSV")}</a>'
            return href
        else:
            # Excel for smaller ones
            output = io.BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            output.seek(0)
            b64 = base64.b64encode(output.getvalue()).decode()
            href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}" style="display: inline-block; padding: 0.5rem 1rem; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">📥 {link_text}</a>'
            return href
    except Exception as e:
        return f'<p style="color: red;">Error creating download: {e}</p>'
    finally:
        gc.collect()

render_header("Month and Quarter Wise Sales Data Analysis", "Analyze shipment data by month, quarter, and year with YoY comparison")

# File uploaders
st.sidebar.header("Upload Files")

# Add a clear cache button to ensure fresh data processing
if st.sidebar.button("🔄 Clear Cache & Refresh"):
    st.cache_data.clear()
    gc.collect()
    st.rerun()

zip_files = st.sidebar.file_uploader(
    "Upload ZIP files (B2B & B2C Reports)", 
    type=['zip'], 
    accept_multiple_files=True
)
pm_file = st.sidebar.file_uploader("Upload PM Excel File", type=['xlsx', 'xls'])

if zip_files and pm_file:
    # Process ZIP files (Extreme Memory Optimization: removed @st.cache_data)
    def process_zip_files(zip_file_list):
        all_dfs = []
        # Essential columns for processing
        essential_cols = ["Invoice Date", "Transaction Type", "Asin", "Quantity", "Invoice Amount", "Order Id", "Shipment Id"]
        
        for uploaded_zip in zip_file_list:
            with zipfile.ZipFile(uploaded_zip, 'r') as z:
                for file_name in z.namelist():
                    if file_name.endswith('/'):
                        continue
                    
                    with z.open(file_name) as f:
                        if file_name.lower().endswith('.csv'):
                            # Use usecols to minimize memory usage
                            df = pd.read_csv(f, usecols=lambda x: x in essential_cols, low_memory=True)
                        elif file_name.lower().endswith(('.xlsx', '.xls')):
                            df = pd.read_excel(f, usecols=lambda x: x in essential_cols)
                        else:
                            continue
                        
                        # Downcast and categorize immediately if possible
                        if "Transaction Type" in df.columns:
                            df["Transaction Type"] = df["Transaction Type"].astype("category")
                        if "Quantity" in df.columns:
                            df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0).astype("int32")
                        if "Invoice Amount" in df.columns:
                            df["Invoice Amount"] = pd.to_numeric(df["Invoice Amount"], errors='coerce').fillna(0).astype("float32")
                            
                        # df['source_zip'] = uploaded_zip.name # Optional: omit to save memory
                        # df['source_file'] = file_name
                        all_dfs.append(df)
                        gc.collect()
        
        combined_df = pd.concat(all_dfs, ignore_index=True)
        del all_dfs
        gc.collect()
        return combined_df
    
    # Process data (Extreme Memory Optimization: removed @st.cache_data)
    def process_data(combined_df, pm_df):
        # Store original count before filtering
        original_count = len(combined_df)
        
        # Store transaction type counts for debugging
        transaction_counts = combined_df['Transaction Type'].value_counts().to_dict()
        
        # Filter for Shipment transactions only
        filtered_df = combined_df[combined_df['Transaction Type'].astype(str).str.strip().str.lower() == 'shipment'].copy()
        
        # AGGRESSIVE PRUNING for unfiltered_df (Tab 5)
        # Tab 5 only needs a subset of columns. Let's drop everything else to save RAM.
        needed_unfiltered_cols = ['Invoice Date', 'Transaction Type', 'Asin', 'Quantity', 'Invoice Amount', 'Order Id', 'Shipment Id']
        unfiltered_df = combined_df[[c for c in combined_df.columns if c in needed_unfiltered_cols]].copy()
        
        del combined_df
        gc.collect()

        filtered_df.reset_index(drop=True, inplace=True)
        unfiltered_df.reset_index(drop=True, inplace=True)
        
        # Store counts
        filtered_count = len(filtered_df)
        unfiltered_count = len(unfiltered_df)
        
        # Function to process date columns
        def add_date_columns(df):
            if 'Invoice Date' in df.columns:
                df['Invoice Date'] = pd.to_datetime(df['Invoice Date'], errors='coerce')
                df['Date'] = df['Invoice Date'].dt.date
                df['Month'] = pd.to_datetime(df['Date']).dt.month.astype("int8")
                df['Month_Name'] = pd.to_datetime(df['Date']).dt.strftime('%B').astype("category")
                df['Month_Year'] = pd.to_datetime(df['Date']).dt.strftime('%b-%y').astype("category")
                df['Year'] = pd.to_datetime(df['Date']).dt.year.astype("int16")
                
                # Define custom quarters
                def get_custom_quarter(month):
                    if month in [1, 2, 3]: return 'Q1'
                    if month in [4, 5, 6]: return 'Q2'
                    if month in [7, 8, 9]: return 'Q3'
                    return 'Q4'
                
                df['Quarter'] = df['Month'].apply(get_custom_quarter).astype("category")
                df['Quarter_Year'] = (df['Quarter'].astype(str) + '-' + df['Year'].astype(str)).astype("category")
            return df
        
        # Process dates for both dataframes
        filtered_df = add_date_columns(filtered_df)
        unfiltered_df = add_date_columns(unfiltered_df)
        
        # Process PM file - DEDUPLICATE and use essential columns
        pm_cols_list = ['ASIN', 'Brand', 'Brand Manager', 'Vendor SKU Codes', 'Product Name']
        pm_cols = pm_df[pm_cols_list].drop_duplicates(subset=['ASIN'], keep='first')
        
        # Categorize PM strings
        for col in ['Brand', 'Brand Manager']:
            pm_cols[col] = pm_cols[col].astype("category")
        
        # Merge with PM data for both dataframes
        # Use on='Asin' but ensure casing matches
        filtered_df = filtered_df.merge(pm_cols, left_on='Asin', right_on='ASIN', how='left')
        unfiltered_df = unfiltered_df.merge(pm_cols, left_on='Asin', right_on='ASIN', how='left')
        
        # Final drop of duplicate ID columns to save memory
        for df in [filtered_df, unfiltered_df]:
            if 'ASIN' in df.columns:
                df.drop(columns=['ASIN'], inplace=True)
        
        del pm_cols, pm_df
        gc.collect()
        
        return filtered_df, unfiltered_df, filtered_count, unfiltered_count, transaction_counts
    
    with st.spinner("Processing files (Extreme Memory Optimization)..."):
        combined_df = process_zip_files(zip_files)
        pm_df = pd.read_excel(pm_file)
        processed_df, unfiltered_combined_df, filtered_count, unfiltered_count, transaction_counts = process_data(combined_df, pm_df)
        gc.collect()
    
    # Show detailed record counts
    col1, col2 = st.columns(2)
    with col1:
        st.success(f"✅ Filtered (Shipment only): **{filtered_count:,}** records")
    with col2:
        st.info(f"📊 Total Combined (Unfiltered): **{unfiltered_count:,}** records")
    
    # Save to MongoDB
    try:
        # Auto-save for general tracking
        auto_save_generated_reports(
            reports={
                "Amazon Month/Quarter Analysis": processed_df
            },
            module_name=MODULE_NAME,
            tool_name=TOOL_NAME
        )
        
        # Also keep reconciliation specific dump but in 'amazon' collection
        save_reconciliation_report(
            collection_name=MODULE_NAME,
            invoice_no=f"MON_QTR_{dt.now().strftime('%Y%m%d_%H%M%S')}",
            summary_data={
                "filtered_count": filtered_count,
                "unfiltered_count": unfiltered_count,
                "total_quantity": int(processed_df["Quantity"].sum()) if "Quantity" in processed_df.columns else 0,
                "total_invoice_amount": float(processed_df["Invoice Amount"].sum()) if "Invoice Amount" in processed_df.columns else 0
            },
            line_items_data=processed_df,
            metadata={
                "report_type": "amazon_month_qtr_wise",
                "tool_name": TOOL_NAME
            }
        )
    except Exception:
        pass
    
    # Show transaction type breakdown in expander for debugging
    with st.expander("🔍 Transaction Type Breakdown"):
        st.write("Records by Transaction Type:")
        for trans_type, count in sorted(transaction_counts.items(), key=lambda x: -x[1]):
            st.write(f"  - **{trans_type}**: {count:,}")
    
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
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📈 Summary", 
        "🏢 Brand Analysis", 
        "📦 ASIN Analysis", 
        "📋 Raw Data", 
        "📊 Combined Data (Unfiltered)",
        "📊 Brand Comparison (YoY)",
        "📦 ASIN Comparison (YoY)"
    ])
    
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
        monthly_trend = filtered_df.groupby('Month_Year', observed=False).agg({
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
            margins=False,
            observed=False
        )
        brand_pivot = brand_pivot.sort_values(by='Quantity', ascending=False)
        brand_pivot.loc['Grand Total'] = brand_pivot.sum()
        brand_pivot = brand_pivot.reset_index()
        
        # Format numbers
        brand_pivot['Invoice Amount'] = brand_pivot['Invoice Amount'].apply(lambda x: f"₹{x:,.2f}")
        brand_pivot['Quantity'] = brand_pivot['Quantity'].apply(lambda x: f"{x:,.0f}")
        
        st.dataframe(brand_pivot, width='stretch', height=600)
        
        # Download link - Excel format (base64 approach for Streamlit Cloud)
        st.markdown(create_download_link(brand_pivot, f"brand_analysis_{time_period}.xlsx", "Download Brand Analysis Excel"), unsafe_allow_html=True)
    
    with tab3:
        st.header("ASIN Analysis")
        
        # ASIN pivot
        asin_pivot = pd.pivot_table(
            filtered_df,
            index=['Asin', 'Brand'],
            values=['Quantity', 'Invoice Amount'],
            aggfunc='sum',
            observed=False
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
        
        st.dataframe(asin_pivot, width='stretch', height=600)
        
        # Download link - Excel format (base64 approach for Streamlit Cloud)
        st.markdown(create_download_link(asin_pivot, f"asin_analysis_{time_period}.xlsx", "Download ASIN Analysis Excel"), unsafe_allow_html=True)
    
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
            display_df = filtered_df[selected_columns]
            
            # UI Row Cap for stability
            if len(display_df) > 5000:
                st.warning(f"⚠️ **Showing first 5,000 rows out of {len(display_df):,}** to prevent server crash. Use the button below to download the FULL dataset.")
                st.dataframe(display_df.head(5000), width='stretch', height=600)
            else:
                st.dataframe(display_df, width='stretch', height=600)
            
            # Download link - Full Data
            st.markdown(create_download_link(display_df, f"filtered_data_{time_period}.csv", "Download Filtered Data (CSV)", is_csv=True), unsafe_allow_html=True)
            gc.collect()
        else:
            st.warning("Please select at least one column to display")
    
    with tab5:
        st.header("Combined Data (Unfiltered)")
        st.info(f"📊 This tab shows ALL {unfiltered_count:,} records without the 'Shipment' transaction type filter.")
        
        # Show transaction type breakdown
        st.subheader("Transaction Type Distribution")
        trans_type_counts = unfiltered_combined_df['Transaction Type'].value_counts().reset_index()
        trans_type_counts.columns = ['Transaction Type', 'Count']
        trans_type_counts['Percentage'] = (trans_type_counts['Count'] / trans_type_counts['Count'].sum() * 100).round(2).astype(str) + '%'
        st.dataframe(trans_type_counts, width='stretch')
        
        st.subheader("All Data")
        
        # Select columns to display
        all_columns_unfiltered = unfiltered_combined_df.columns.tolist()
        default_columns_unfiltered = ['Invoice Date', 'Transaction Type', 'Asin', 'Brand', 'Product Name', 'Quantity', 
                          'Invoice Amount', 'Month_Year', 'Quarter', 'Year', 'Order Id', 'Shipment Id']
        
        selected_columns_unfiltered = st.multiselect(
            "Select columns to display",
            all_columns_unfiltered,
            default=[col for col in default_columns_unfiltered if col in all_columns_unfiltered],
            key="unfiltered_columns"
        )
        
        if selected_columns_unfiltered:
            display_unfiltered_df = unfiltered_combined_df[selected_columns_unfiltered]
            
            # UI Row Cap for stability
            if len(display_unfiltered_df) > 5000:
                st.warning(f"⚠️ **Showing first 5,000 rows out of {len(display_unfiltered_df):,}** to prevent server crash. Use the button below to download the FULL dataset.")
                st.dataframe(display_unfiltered_df.head(5000), width='stretch', height=600)
            else:
                st.dataframe(display_unfiltered_df, width='stretch', height=600)
            
            # Download link - Full Data
            st.markdown(create_download_link(display_unfiltered_df, f"combined_unfiltered_data_{time_period}.csv", "Download Combined (Unfiltered) Data (CSV)", is_csv=True), unsafe_allow_html=True)
            gc.collect()
        else:
            st.warning("Please select at least one column to display")

    # Year-over-Year Comparison Tabs
    with tab6:
        st.header("📊 Brand Comparison (Year-over-Year)")
        
        # Get available years
        available_years = sorted(processed_df['Year'].dropna().unique(), reverse=True)
        
        if len(available_years) >= 2:
            st.markdown("### Select Years to Compare")
            col1, col2 = st.columns(2)
            
            with col1:
                current_year = st.selectbox(
                    "📅 Current Year (to be analyzed)",
                    available_years,
                    index=0,
                    key="brand_current_year"
                )
            
            with col2:
                # Filter out the current year from previous year options
                prev_year_options = [y for y in available_years if y != current_year]
                if prev_year_options:
                    previous_year = st.selectbox(
                        "📅 Previous Year (to compare against)",
                        prev_year_options,
                        index=0,
                        key="brand_previous_year"
                    )
                else:
                    previous_year = None
                    st.warning("No other year available for comparison")
            
            if previous_year:
                # Filter data by years
                current_year_data = processed_df[processed_df['Year'] == current_year]
                previous_year_data = processed_df[processed_df['Year'] == previous_year]
                
                # Create brand pivots for each year
                current_brand_pivot = pd.pivot_table(
                    current_year_data,
                    index='Brand',
                    values=['Quantity', 'Invoice Amount'],
                    aggfunc='sum',
                    observed=False
                ).reset_index()
                current_brand_pivot.columns = ['Brand', f'Invoice Amount ({current_year})', f'Quantity ({current_year})']
                
                previous_brand_pivot = pd.pivot_table(
                    previous_year_data,
                    index='Brand',
                    values=['Quantity', 'Invoice Amount'],
                    aggfunc='sum',
                    observed=False
                ).reset_index()
                gc.collect()
                previous_brand_pivot.columns = ['Brand', f'Invoice Amount ({previous_year})', f'Quantity ({previous_year})']
                
                # Merge the two pivots
                brand_comparison = pd.merge(
                    previous_brand_pivot,
                    current_brand_pivot,
                    on='Brand',
                    how='outer'
                ).fillna(0)
                
                # Calculate differences and percentage changes
                brand_comparison['Qty Difference'] = brand_comparison[f'Quantity ({current_year})'] - brand_comparison[f'Quantity ({previous_year})']
                brand_comparison['Qty % Change'] = brand_comparison.apply(
                    lambda row: ((row[f'Quantity ({current_year})'] - row[f'Quantity ({previous_year})']) / row[f'Quantity ({previous_year})'] * 100) 
                    if row[f'Quantity ({previous_year})'] != 0 else (100 if row[f'Quantity ({current_year})'] > 0 else 0), axis=1
                )
                
                brand_comparison['Amount Difference'] = brand_comparison[f'Invoice Amount ({current_year})'] - brand_comparison[f'Invoice Amount ({previous_year})']
                brand_comparison['Amount % Change'] = brand_comparison.apply(
                    lambda row: ((row[f'Invoice Amount ({current_year})'] - row[f'Invoice Amount ({previous_year})']) / row[f'Invoice Amount ({previous_year})'] * 100) 
                    if row[f'Invoice Amount ({previous_year})'] != 0 else (100 if row[f'Invoice Amount ({current_year})'] > 0 else 0), axis=1
                )
                
                # Reorder columns
                brand_comparison = brand_comparison[[
                    'Brand',
                    f'Quantity ({previous_year})', f'Quantity ({current_year})', 'Qty Difference', 'Qty % Change',
                    f'Invoice Amount ({previous_year})', f'Invoice Amount ({current_year})', 'Amount Difference', 'Amount % Change'
                ]]
                
                # Sort by current year quantity descending
                brand_comparison = brand_comparison.sort_values(by=f'Quantity ({current_year})', ascending=False)
                
                # Add Grand Total row
                grand_total = pd.DataFrame({
                    'Brand': ['Grand Total'],
                    f'Quantity ({previous_year})': [brand_comparison[f'Quantity ({previous_year})'].sum()],
                    f'Quantity ({current_year})': [brand_comparison[f'Quantity ({current_year})'].sum()],
                    'Qty Difference': [brand_comparison['Qty Difference'].sum()],
                    'Qty % Change': [
                        (brand_comparison[f'Quantity ({current_year})'].sum() - brand_comparison[f'Quantity ({previous_year})'].sum()) / 
                        brand_comparison[f'Quantity ({previous_year})'].sum() * 100 if brand_comparison[f'Quantity ({previous_year})'].sum() != 0 else 0
                    ],
                    f'Invoice Amount ({previous_year})': [brand_comparison[f'Invoice Amount ({previous_year})'].sum()],
                    f'Invoice Amount ({current_year})': [brand_comparison[f'Invoice Amount ({current_year})'].sum()],
                    'Amount Difference': [brand_comparison['Amount Difference'].sum()],
                    'Amount % Change': [
                        (brand_comparison[f'Invoice Amount ({current_year})'].sum() - brand_comparison[f'Invoice Amount ({previous_year})'].sum()) / 
                        brand_comparison[f'Invoice Amount ({previous_year})'].sum() * 100 if brand_comparison[f'Invoice Amount ({previous_year})'].sum() != 0 else 0
                    ]
                })
                brand_comparison = pd.concat([brand_comparison, grand_total], ignore_index=True)
                
                # Format display dataframe
                display_brand_comparison = brand_comparison.copy()
                display_brand_comparison[f'Quantity ({previous_year})'] = display_brand_comparison[f'Quantity ({previous_year})'].apply(lambda x: f"{x:,.0f}")
                display_brand_comparison[f'Quantity ({current_year})'] = display_brand_comparison[f'Quantity ({current_year})'].apply(lambda x: f"{x:,.0f}")
                display_brand_comparison['Qty Difference'] = display_brand_comparison['Qty Difference'].apply(lambda x: f"{x:+,.0f}")
                display_brand_comparison['Qty % Change'] = display_brand_comparison['Qty % Change'].apply(lambda x: f"{x:+.2f}%")
                display_brand_comparison[f'Invoice Amount ({previous_year})'] = display_brand_comparison[f'Invoice Amount ({previous_year})'].apply(lambda x: f"₹{x:,.2f}")
                display_brand_comparison[f'Invoice Amount ({current_year})'] = display_brand_comparison[f'Invoice Amount ({current_year})'].apply(lambda x: f"₹{x:,.2f}")
                display_brand_comparison['Amount Difference'] = display_brand_comparison['Amount Difference'].apply(lambda x: f"₹{x:+,.2f}")
                display_brand_comparison['Amount % Change'] = display_brand_comparison['Amount % Change'].apply(lambda x: f"{x:+.2f}%")
                
                # Show summary metrics
                st.markdown(f"### Comparison: {current_year} vs {previous_year}")
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                
                total_qty_change = brand_comparison.iloc[-1]['Qty Difference']
                total_qty_pct = brand_comparison.iloc[-1]['Qty % Change']
                total_amt_change = brand_comparison.iloc[-1]['Amount Difference']
                total_amt_pct = brand_comparison.iloc[-1]['Amount % Change']
                
                with metric_col1:
                    st.metric("Total Qty Change", f"{total_qty_change:+,.0f}", f"{total_qty_pct:+.2f}%")
                with metric_col2:
                    st.metric("Total Amount Change", f"₹{total_amt_change:+,.0f}", f"{total_amt_pct:+.2f}%")
                with metric_col3:
                    st.metric(f"Brands in {current_year}", f"{len(current_year_data['Brand'].dropna().unique()):,}")
                with metric_col4:
                    st.metric(f"Brands in {previous_year}", f"{len(previous_year_data['Brand'].dropna().unique()):,}")
                
                st.dataframe(display_brand_comparison, width='stretch', height=600)
                
                # Download link (base64 approach for Streamlit Cloud)
                st.markdown(create_download_link(brand_comparison, f"brand_comparison_{current_year}_vs_{previous_year}.xlsx", "Download Brand Comparison Excel"), unsafe_allow_html=True)
        else:
            st.warning("⚠️ Need at least 2 years of data for comparison. Please upload data from multiple years.")
    
    with tab7:
        st.header("📦 ASIN Comparison (Year-over-Year)")
        
        # Get available years
        available_years_asin = sorted(processed_df['Year'].dropna().unique(), reverse=True)
        
        if len(available_years_asin) >= 2:
            st.markdown("### Select Years to Compare")
            col1, col2 = st.columns(2)
            
            with col1:
                current_year_asin = st.selectbox(
                    "📅 Current Year (to be analyzed)",
                    available_years_asin,
                    index=0,
                    key="asin_current_year"
                )
            
            with col2:
                # Filter out the current year from previous year options
                prev_year_options_asin = [y for y in available_years_asin if y != current_year_asin]
                if prev_year_options_asin:
                    previous_year_asin = st.selectbox(
                        "📅 Previous Year (to compare against)",
                        prev_year_options_asin,
                        index=0,
                        key="asin_previous_year"
                    )
                else:
                    previous_year_asin = None
                    st.warning("No other year available for comparison")
            
            if previous_year_asin:
                # Filter data by years
                current_year_data_asin = processed_df[processed_df['Year'] == current_year_asin]
                previous_year_data_asin = processed_df[processed_df['Year'] == previous_year_asin]
                
                # Create ASIN pivots for each year
                current_asin_pivot = pd.pivot_table(
                    current_year_data_asin,
                    index=['Asin', 'Brand'],
                    values=['Quantity', 'Invoice Amount'],
                    aggfunc='sum',
                    observed=False
                ).reset_index()
                current_asin_pivot.columns = ['Asin', 'Brand', f'Invoice Amount ({current_year_asin})', f'Quantity ({current_year_asin})']
                
                previous_asin_pivot = pd.pivot_table(
                    previous_year_data_asin,
                    index=['Asin', 'Brand'],
                    values=['Quantity', 'Invoice Amount'],
                    aggfunc='sum',
                    observed=False
                ).reset_index()
                gc.collect()
                previous_asin_pivot.columns = ['Asin', 'Brand', f'Invoice Amount ({previous_year_asin})', f'Quantity ({previous_year_asin})']
                
                # Merge the two pivots
                asin_comparison = pd.merge(
                    previous_asin_pivot,
                    current_asin_pivot,
                    on=['Asin', 'Brand'],
                    how='outer'
                ).fillna(0)
                
                # Calculate differences and percentage changes
                asin_comparison['Qty Difference'] = asin_comparison[f'Quantity ({current_year_asin})'] - asin_comparison[f'Quantity ({previous_year_asin})']
                asin_comparison['Qty % Change'] = asin_comparison.apply(
                    lambda row: ((row[f'Quantity ({current_year_asin})'] - row[f'Quantity ({previous_year_asin})']) / row[f'Quantity ({previous_year_asin})'] * 100) 
                    if row[f'Quantity ({previous_year_asin})'] != 0 else (100 if row[f'Quantity ({current_year_asin})'] > 0 else 0), axis=1
                )
                
                asin_comparison['Amount Difference'] = asin_comparison[f'Invoice Amount ({current_year_asin})'] - asin_comparison[f'Invoice Amount ({previous_year_asin})']
                asin_comparison['Amount % Change'] = asin_comparison.apply(
                    lambda row: ((row[f'Invoice Amount ({current_year_asin})'] - row[f'Invoice Amount ({previous_year_asin})']) / row[f'Invoice Amount ({previous_year_asin})'] * 100) 
                    if row[f'Invoice Amount ({previous_year_asin})'] != 0 else (100 if row[f'Invoice Amount ({current_year_asin})'] > 0 else 0), axis=1
                )
                
                # Reorder columns
                asin_comparison = asin_comparison[[
                    'Asin', 'Brand',
                    f'Quantity ({previous_year_asin})', f'Quantity ({current_year_asin})', 'Qty Difference', 'Qty % Change',
                    f'Invoice Amount ({previous_year_asin})', f'Invoice Amount ({current_year_asin})', 'Amount Difference', 'Amount % Change'
                ]]
                
                # Sort by current year quantity descending
                asin_comparison = asin_comparison.sort_values(by=f'Quantity ({current_year_asin})', ascending=False)
                
                # Add Grand Total row
                grand_total_asin = pd.DataFrame({
                    'Asin': ['Grand Total'],
                    'Brand': [''],
                    f'Quantity ({previous_year_asin})': [asin_comparison[f'Quantity ({previous_year_asin})'].sum()],
                    f'Quantity ({current_year_asin})': [asin_comparison[f'Quantity ({current_year_asin})'].sum()],
                    'Qty Difference': [asin_comparison['Qty Difference'].sum()],
                    'Qty % Change': [
                        (asin_comparison[f'Quantity ({current_year_asin})'].sum() - asin_comparison[f'Quantity ({previous_year_asin})'].sum()) / 
                        asin_comparison[f'Quantity ({previous_year_asin})'].sum() * 100 if asin_comparison[f'Quantity ({previous_year_asin})'].sum() != 0 else 0
                    ],
                    f'Invoice Amount ({previous_year_asin})': [asin_comparison[f'Invoice Amount ({previous_year_asin})'].sum()],
                    f'Invoice Amount ({current_year_asin})': [asin_comparison[f'Invoice Amount ({current_year_asin})'].sum()],
                    'Amount Difference': [asin_comparison['Amount Difference'].sum()],
                    'Amount % Change': [
                        (asin_comparison[f'Invoice Amount ({current_year_asin})'].sum() - asin_comparison[f'Invoice Amount ({previous_year_asin})'].sum()) / 
                        asin_comparison[f'Invoice Amount ({previous_year_asin})'].sum() * 100 if asin_comparison[f'Invoice Amount ({previous_year_asin})'].sum() != 0 else 0
                    ]
                })
                asin_comparison = pd.concat([asin_comparison, grand_total_asin], ignore_index=True)
                
                # Format display dataframe
                display_asin_comparison = asin_comparison.copy()
                display_asin_comparison[f'Quantity ({previous_year_asin})'] = display_asin_comparison[f'Quantity ({previous_year_asin})'].apply(lambda x: f"{x:,.0f}")
                display_asin_comparison[f'Quantity ({current_year_asin})'] = display_asin_comparison[f'Quantity ({current_year_asin})'].apply(lambda x: f"{x:,.0f}")
                display_asin_comparison['Qty Difference'] = display_asin_comparison['Qty Difference'].apply(lambda x: f"{x:+,.0f}")
                display_asin_comparison['Qty % Change'] = display_asin_comparison['Qty % Change'].apply(lambda x: f"{x:+.2f}%")
                display_asin_comparison[f'Invoice Amount ({previous_year_asin})'] = display_asin_comparison[f'Invoice Amount ({previous_year_asin})'].apply(lambda x: f"₹{x:,.2f}")
                display_asin_comparison[f'Invoice Amount ({current_year_asin})'] = display_asin_comparison[f'Invoice Amount ({current_year_asin})'].apply(lambda x: f"₹{x:,.2f}")
                display_asin_comparison['Amount Difference'] = display_asin_comparison['Amount Difference'].apply(lambda x: f"₹{x:+,.2f}")
                display_asin_comparison['Amount % Change'] = display_asin_comparison['Amount % Change'].apply(lambda x: f"{x:+.2f}%")
                
                # Show summary metrics
                st.markdown(f"### Comparison: {current_year_asin} vs {previous_year_asin}")
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                
                total_qty_change_asin = asin_comparison.iloc[-1]['Qty Difference']
                total_qty_pct_asin = asin_comparison.iloc[-1]['Qty % Change']
                total_amt_change_asin = asin_comparison.iloc[-1]['Amount Difference']
                total_amt_pct_asin = asin_comparison.iloc[-1]['Amount % Change']
                
                with metric_col1:
                    st.metric("Total Qty Change", f"{total_qty_change_asin:+,.0f}", f"{total_qty_pct_asin:+.2f}%")
                with metric_col2:
                    st.metric("Total Amount Change", f"₹{total_amt_change_asin:+,.0f}", f"{total_amt_pct_asin:+.2f}%")
                with metric_col3:
                    st.metric(f"Unique ASINs in {current_year_asin}", f"{len(current_year_data_asin['Asin'].dropna().unique()):,}")
                with metric_col4:
                    st.metric(f"Unique ASINs in {previous_year_asin}", f"{len(previous_year_data_asin['Asin'].dropna().unique()):,}")
                
                st.dataframe(display_asin_comparison, width='stretch', height=600)
                
                # Download link (base64 approach for Streamlit Cloud)
                st.markdown(create_download_link(asin_comparison, f"asin_comparison_{current_year_asin}_vs_{previous_year_asin}.xlsx", "Download ASIN Comparison Excel"), unsafe_allow_html=True)
        else:
            st.warning("⚠️ Need at least 2 years of data for comparison. Please upload data from multiple years.")

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