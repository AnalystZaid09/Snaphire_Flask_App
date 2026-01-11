import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
from ui_utils import apply_professional_style, get_download_filename, render_header

st.set_page_config(page_title="Amazon Replacement Without Reimbursement Analyzer", page_icon="🔄", layout="wide")
apply_professional_style()

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f2937;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #6b7280;
        margin-bottom: 2rem;
    }
    .metric-card {
        padding: 1rem;
        border-radius: 0.5rem;
        border: 2px solid #e5e7eb;
        background-color: #f9fafb;
    }
</style>
""", unsafe_allow_html=True)

def read_any_file(file, sheet_name=None):
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    else:
        if sheet_name:
            return pd.read_excel(file, sheet_name=sheet_name)
        return pd.read_excel(file)
        
def process_replacement_data(replace_file, return_file, refund_file, bulk_rto_file, reim_file, days_threshold: int):
    """Process replacement data with all lookups and filters"""
    try:
        # Load Replace.csv
        Replace = read_any_file(replace_file)
        
        # Convert date and calculate difference
        Replace['Date'] = pd.to_datetime(Replace['shipment-date'], errors='coerce').dt.date
        Replace['Today_Date'] = date.today()
        Replace['Date_Difference'] = (pd.to_datetime(Replace['Today_Date']) - pd.to_datetime(Replace['Date'])).dt.days
        
        # Load Return.csv
        Return = read_any_file(return_file)
        
        # FBA Original Return Lookup (Column I → Column B → Column 8)
        lookup_value_col = Replace.columns[8]
        lookup_key_col = Return.columns[1]
        return_value_col = Return.columns[8]
        
        Replace = Replace.merge(
            Return[[lookup_key_col, return_value_col]],
            how="left",
            left_on=lookup_value_col,
            right_on=lookup_key_col
        )
        Replace.rename(columns={return_value_col: "FBA Original Return"}, inplace=True)
        Replace.drop(columns=[lookup_key_col], inplace=True, errors="ignore")
        
        # FBA Replacement Return Lookup (Column H → Column B → Column 8)
        lookup_value_col = Replace.columns[7]
        lookup_key_col = Return.columns[1]
        return_value_col = Return.columns[8]
        
        Replace = Replace.merge(
            Return[[lookup_key_col, return_value_col]],
            how="left",
            left_on=lookup_value_col,
            right_on=lookup_key_col
        )
        Replace.rename(columns={return_value_col: "FBA Replacement Return"}, inplace=True)
        Replace.drop(columns=[lookup_key_col], inplace=True, errors="ignore")
        
        # Filter 1: Damaged Returns
        filtered_df = Replace[
            (
                Replace["FBA Original Return"].isin(["CARRIER_DAMAGED", "CUSTOMER_DAMAGED"]) &
                Replace["FBA Replacement Return"].isin(["CARRIER_DAMAGED", "CUSTOMER_DAMAGED"])
            )
        ].copy()
        
        # Load Reimbursement
        Reimbursement =read_any_file(reim_file, sheet_name='Sheet1')
        
        # Filter reimbursement data
        filtered_reimb = Reimbursement[
            Reimbursement["reason"].isin(["CustomerReturn", "CustomerServiceIssue"])
        ].copy()
        
        # Add CountIF
        filtered_reimb.loc[:, "CountIF"] = (
            filtered_reimb.groupby("amazon-order-id")["amazon-order-id"].transform("count")
        )
        
        # Merge CountIF into filtered_df
        lookup_value_col = filtered_df.columns[8]
        lookup_key_col = filtered_reimb.columns[3]
        return_value_col = filtered_reimb.columns[18]
        
        filtered_df = filtered_df.merge(
            filtered_reimb[[lookup_key_col, return_value_col]],
            how="left",
            left_on=lookup_value_col,
            right_on=lookup_key_col
        )
        filtered_df.rename(columns={return_value_col: "CountIF"}, inplace=True)
        filtered_df.drop(columns=[lookup_key_col], inplace=True, errors="ignore")
        
        # 🔍 Filter: CountIF = 1 and Date_Difference >= days_threshold
        filtered_df_final = filtered_df[
            (filtered_df["CountIF"] == 1.0) &
            (filtered_df["Date_Difference"] >= days_threshold)
        ].copy()
        
        # Load Refund Only file
        Refund = read_any_file(refund_file, sheet_name='Sheet1')
        
        # Refund Check Lookup
        lookup_value_col = Replace.columns[8]
        lookup_key_col = Refund.columns[4]
        
        Replace = Replace.merge(
            Refund[[lookup_key_col]].drop_duplicates(),
            how="left",
            left_on=lookup_value_col,
            right_on=lookup_key_col
        )
        Replace["Refund Check"] = Replace[lookup_key_col]
        Replace.drop(columns=[lookup_key_col], inplace=True, errors="ignore")
        
        # Filter 2: Refund without Returns
        filtered_df_step2 = Replace[
            (
                (Replace["FBA Original Return"].isna()) |
                (Replace["FBA Original Return"].astype(str).str.upper().eq("NA"))
            ) &
            (
                (Replace["FBA Replacement Return"].isna()) |
                (Replace["FBA Replacement Return"].astype(str).str.upper().eq("NA"))
            ) &
            (
                (~Replace["Refund Check"].astype(str).str.upper().eq("NA")) &
                (~Replace["Refund Check"].isna())
            ) &
            (
                (Replace["Date_Difference"] >= days_threshold)
            )
        ].copy()
        
        # Load Bulk RTO
        BulkRTO = read_any_file(bulk_rto_file, sheet_name="All")
        
        # Door Step Return Lookup
        lookup_value_col = filtered_df_step2.columns[8]
        lookup_key_col = BulkRTO.columns[0]
        
        filtered_df_step2 = filtered_df_step2.merge(
            BulkRTO[[lookup_key_col]].drop_duplicates(),
            how="left",
            left_on=lookup_value_col,
            right_on=lookup_key_col
        )
        filtered_df_step2["Door Step Return"] = filtered_df_step2[lookup_key_col]
        filtered_df_step2.drop(columns=[lookup_key_col], inplace=True, errors="ignore")
        
        # Filter 3: No Door Step Return
        filtered_df_step3 = filtered_df_step2[
            (filtered_df_step2["Door Step Return"].isna()) |
            (filtered_df_step2["Door Step Return"].astype(str).str.strip().str.upper().eq("NA"))
        ].copy()
        
        return {
            'main': Replace,
            'damaged_returns': filtered_df_final,
            'refund_without_return': filtered_df_step3,
            'damaged_count': len(filtered_df_final),
            'refund_count': len(filtered_df_step3)
        }
        
    except Exception as e:
        st.error(f"Error processing files: {str(e)}")
        return None

# Main App
render_header("Amazon Replacement Without Reimbursement Data Analyzer", "Upload your files to analyze replacement and return data")

# File Upload Section
st.markdown("### 📁 Upload Required Files")

col1, col2 = st.columns(2)

with col1:
    replace_file = st.file_uploader("Replace File", type=['csv','xlsx'], key="replace")
    return_file = st.file_uploader("Return File", type=['csv','xlsx'], key="return")
    refund_file = st.file_uploader("Refund Only File", type=['xlsx','csv'], key="refund")

with col2:
    bulk_rto_file = st.file_uploader("Bulk RTO Returns File", type=['xlsx','csv'], key="bulk")
    reim_file = st.file_uploader("Reimbursement File", type=['xlsx','csv'], key="reim")

# ⏱️ Days slicer / input
st.markdown("### ⏱️ Days Filter")
days_threshold = st.number_input(
    "Consider records older than (days):",
    min_value=0,
    max_value=365,
    value=40,       # default 40 days
    step=1,
    help="Example: 10, 30, 40, 45, 60..."
)

# Process Button
all_files = [replace_file, return_file, refund_file, bulk_rto_file, reim_file]
if all(all_files):
    if st.button("🔍 Analyze Replacement Data", type="primary", use_container_width=True):
        with st.spinner("Processing data... This may take a moment."):
            results = process_replacement_data(*all_files, days_threshold)
            
            if results:
                st.success("✅ Analysis completed successfully!")
                
                # Display Statistics
                st.markdown("### 📈 Analysis Results")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Total Replacements", f"{len(results['main']):,}")
                
                with col2:
                    st.metric(
                        f"Damaged Returns (≥{int(days_threshold)} days)",
                        f"{results['damaged_count']:,}", 
                        help=f"Replacements with CARRIER_DAMAGED or CUSTOMER_DAMAGED status and age ≥ {int(days_threshold)} days"
                    )
                
                with col3:
                    st.metric(
                        f"Refund without Return (≥{int(days_threshold)} days)",
                        f"{results['refund_count']:,}",
                        help=f"Refunds processed but no return record found, age ≥ {int(days_threshold)} days"
                    )
                
                # Data Preview
                st.markdown("### 📊 Data Preview")
                
                tab1, tab2, tab3 = st.tabs(["Damaged Returns", "Refund Without Return", "Full Data"])
                
                with tab1:
                    st.markdown(f"**Replacements with damaged items (≥{int(days_threshold)} days old)**")
                    st.dataframe(results['damaged_returns'], use_container_width=True)
                
                with tab2:
                    st.markdown(f"**Replacements with refund but no return record (≥{int(days_threshold)} days old)**")
                    st.dataframe(results['refund_without_return'], use_container_width=True)
                
                with tab3:
                    st.markdown("**All processed replacement data**")
                    st.dataframe(results['main'], use_container_width=True)
                
                # Download Buttons - Each report saved to MongoDB individually when downloaded
                st.markdown("### 💾 Download Reports")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    from ui_utils import download_report
                    download_report(
                        df=results['damaged_returns'],
                        base_filename="damaged_returns_report",
                        button_label="⬇️ Download Damaged Returns",
                        module_name="leakagereconciliation",
                        report_name=f"Damaged Returns (≥{int(days_threshold)} days)",
                        key="replacement_damaged"
                    )
                
                with col2:
                    download_report(
                        df=results['refund_without_return'],
                        base_filename="refund_without_return_report",
                        button_label="⬇️ Download Refund Without Return",
                        module_name="leakagereconciliation",
                        report_name=f"Refund Without Return (≥{int(days_threshold)} days)",
                        key="replacement_refund"
                    )
                
                with col3:
                    download_report(
                        df=results['main'],
                        base_filename="full_replacement_report",
                        button_label="⬇️ Download Full Report",
                        module_name="leakagereconciliation",
                        report_name="Full Replacement Report",
                        key="replacement_full"
                    )
else:
    st.info("👆 Please upload all required files to begin analysis")

# Footer
st.markdown("---")
st.markdown("*Amazon Seller Replacement & Return Analysis Tool*")
