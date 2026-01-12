import streamlit as st
import pandas as pd
from datetime import datetime
import io
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    auto_log_reports
)

MODULE_NAME = "leakagereconciliation"

st.set_page_config(page_title="Amazon Refund Cross-Check Analyzer", page_icon="🔍", layout="wide")
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
    .stat-card {
        padding: 1.5rem;
        border-radius: 0.5rem;
        border: 2px solid #e5e7eb;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

def read_any_file(file, sheet_name=None):
    """Read CSV or Excel safely, with optional sheet_name for Excel"""
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    else:
        if sheet_name:
            return pd.read_excel(file, sheet_name=sheet_name)
        return pd.read_excel(file)

def process_refund_data(refund_file, qwt_file, returns_file, bulk_rto_file, safe_t_file, reim_file,
                        door_tat_min, door_tat_max, fba_tat_min):
    """Process all uploaded files and perform the analysis"""
    try:
        # Load Refund Data
        Refund_data = read_any_file(refund_file)
        
        # Filter only Refund type
        TYPE_COL = [c for c in Refund_data.columns if c.strip().lower() == "type"][0]
        Refund_data = Refund_data[Refund_data[TYPE_COL].astype(str).str.lower() == "refund"].copy()
        
        # Remove Product Sales = 0
        product_sales_col = "product sales"
        Refund_data[product_sales_col] = pd.to_numeric(Refund_data[product_sales_col], errors="coerce")
        Refund_data = Refund_data[Refund_data[product_sales_col] != 0].copy()
        
        # Convert date and calculate Date_Diff
        Refund_data['Date1'] = pd.to_datetime(
            Refund_data['date/time'],
            errors="coerce",
            dayfirst=True,
            format="mixed"
        ).dt.date

        Refund_data['Today'] = datetime.today().date()
        Refund_data['Date_Diff'] = (pd.to_datetime(Refund_data['Today']) - pd.to_datetime(Refund_data['Date1'])).dt.days
        
        # Load QWT and perform Door Ship lookup
        qwt = read_any_file(qwt_file)
        Refund_data["__key"] = Refund_data["order id"].astype(str).str.strip().str.upper()
        qwt_map = (
            qwt.assign(__key = qwt["Customer Order ID"].astype(str).str.strip().str.upper())
               .drop_duplicates("__key", keep="first")
               .set_index("__key")["Customer Order ID"]
        )
        Refund_data["Door Ship (Seller Flex)"] = Refund_data["__key"].map(qwt_map)
        Refund_data.drop(columns="__key", inplace=True)
        
        # Load Returns and perform FBA Return lookup
        returns = read_any_file(returns_file)
        Refund_data.loc[:, "__key"] = Refund_data["order id"].astype(str).str.strip().str.upper()
        returns.loc[:, "__key"] = returns["order-id"].astype(str).str.strip().str.upper()
        ret_map = (
            returns[["__key", "order-id"]]
              .drop_duplicates("__key", keep="first")
              .set_index("__key")["order-id"]
        )
        Refund_data["FBA Return"] = Refund_data["__key"].map(ret_map)
        Refund_data.drop(columns="__key", inplace=True)
        
        # Load Bulk RTO and perform Seller Flex Return lookup
        bulk_rto = read_any_file(bulk_rto_file, sheet_name="All" if not bulk_rto_file.name.lower().endswith(".csv") else None)
        Refund_data["__key"] = Refund_data["Door Ship (Seller Flex)"].astype(str).str.strip().str.upper()
        bulk_rto["__key"] = bulk_rto["Order Id"].astype(str).str.strip().str.upper()
        right_key = bulk_rto[["__key", "Order Id"]].drop_duplicates()
        Refund_data = Refund_data.merge(right_key, on="__key", how="left")
        Refund_data.rename(columns={"Order Id": "Seller Flex Return"}, inplace=True)
        Refund_data.drop(columns="__key", inplace=True)
        
        # Load Safe-T Claim and perform lookup
        safeT = read_any_file(safe_t_file, sheet_name="Sheet1" if not safe_t_file.name.lower().endswith(".csv") else None)
        lookup_col = safeT.columns[3]
        Refund_data.loc[:, "__key"] = Refund_data["Door Ship (Seller Flex)"].astype(str).str.strip().str.upper()
        safeT.loc[:, "__key"] = safeT[lookup_col].astype(str).str.strip().str.upper()
        safeT_small = safeT[["__key", lookup_col]].drop_duplicates()
        Refund_data = Refund_data.merge(safeT_small, on="__key", how="left")
        Refund_data.rename(columns={"order id_y": "Safe T Claim"}, inplace=True)
        Refund_data.drop(columns="__key", inplace=True)
        
        # Load Reimbursement and perform FBA Reimbursement lookup
        reim = read_any_file(reim_file)
        filtered_reim = reim[reim["reason"].isin(["CustomerReturn", "CustomerServiceIssue"])].copy()
        Refund_data.loc[:, "__key"] = Refund_data["order id_x"].astype(str).str.strip().str.upper()
        filtered_reim.loc[:, "__key"] = filtered_reim["amazon-order-id"].astype(str).str.strip().str.upper()
        filtered_reim_small = filtered_reim[["__key","amazon-order-id"]].drop_duplicates()
        Refund_data = Refund_data.merge(filtered_reim_small, on="__key", how="left")
        Refund_data.rename(columns={"amazon-order-id": "FBA Reimbursement"}, inplace=True)
        Refund_data.drop(columns="__key", inplace=True)
        
        # Create filtered dataframes
        filtered_doorship = Refund_data[
            Refund_data["Door Ship (Seller Flex)"].notna() &
            Refund_data["FBA Return"].isna() &
            Refund_data["Seller Flex Return"].isna() &
            Refund_data["Safe T Claim"].isna()
        ].copy()
        
        fba_return_df = Refund_data[
            (Refund_data["Door Ship (Seller Flex)"].isna()) &
            (Refund_data["FBA Return"].isna()) &
            (Refund_data["Seller Flex Return"].isna()) &
            (
                Refund_data["FBA Reimbursement"].isna() |
                (Refund_data["FBA Reimbursement"].astype(str).str.strip() == "")
            )
        ].copy()
        
        # 🔹 Use dynamic TAT filters instead of fixed values
        filtered_df_TAT = filtered_doorship[
            filtered_doorship["Date_Diff"].between(door_tat_min, door_tat_max, inclusive="both")
        ].copy()
        
        fba_return_TAT = fba_return_df[fba_return_df["Date_Diff"] >= fba_tat_min].copy()
        
        return {
            'main': Refund_data,
            'filtered_doorship': filtered_doorship,
            'fba_return': fba_return_df,
            'doorship_tat': filtered_df_TAT,
            'fba_return_tat': fba_return_TAT
        }
        
    except Exception as e:
        st.error(f"Error processing files: {str(e)}")
        return None

# Main App
render_header("Amazon Refund Cross Check", "Upload your files to analyze refund and return data")

# File Upload Section
st.markdown("### 📁 Upload Required Files")

col1, col2 = st.columns(2)

with col1:
    refund_file = st.file_uploader("Refund Data (Excel/CSV)", type=['xlsx', 'xls','csv'], key="refund")
    qwt_file = st.file_uploader("QWT Customer Shipments (Excel/CSV)", type=['xlsx','csv'], key="qwt")
    returns_file = st.file_uploader("Returns (Excel/CSV)", type=['xlsx','csv'], key="returns")

with col2:
    bulk_rto_file = st.file_uploader("Bulk RTO Returns (Excel/CSV)", type=['xlsx', 'xls','csv'], key="bulk")
    safe_t_file = st.file_uploader("Safe-T Claim (Excel/CSV)", type=['xlsx', 'xls','csv'], key="safe")
    reim_file = st.file_uploader("FBA Reimbursement (Excel/CSV)", type=['xlsx','csv'], key="reim")

# 🔹 TAT inputs for days
st.markdown("### ⏱️ TAT Day Filters")

tat_col1, tat_col2 = st.columns(2)

with tat_col1:
    door_tat_min = st.number_input(
        "Door Ship TAT start (days):",
        min_value=0,
        max_value=365,
        value=50,
        step=1,
        help="Starting day value for Door Ship TAT range."
    )
    door_tat_max = st.number_input(
        "Door Ship TAT end (days):",
        min_value=door_tat_min,
        max_value=365,
        value=75,
        step=1,
        help="Ending day value for Door Ship TAT range."
    )

with tat_col2:
    fba_tat_min = st.number_input(
        "FBA Return TAT minimum days:",
        min_value=0,
        max_value=365,
        value=40,
        step=1,
        help="Filter FBA Return records with Date_Diff ≥ this number of days."
    )

# Initialize session state for results
if 'refund_results' not in st.session_state:
    st.session_state.refund_results = None

# Process Button
all_files = [refund_file, qwt_file, returns_file, bulk_rto_file, safe_t_file, reim_file]
if all(all_files):
    if st.button("🔍 Analyze Refund Data", type="primary", use_container_width=True):
        with st.spinner("Processing data..."):
            results = process_refund_data(*all_files, door_tat_min, door_tat_max, fba_tat_min)
            
            if results:
                st.session_state.refund_results = results
                st.success("✅ Analysis completed successfully!")
                
                # Auto-log all reports to MongoDB as they are generated
                auto_log_reports(results, MODULE_NAME)

    # Display results if they exist in session state
    if st.session_state.refund_results:
        results = st.session_state.refund_results
        
        # Display Statistics
        st.markdown("### 📈 Analysis Results")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Refunds", f"{len(results['main']):,}")
            st.metric("Door Ship Returns", f"{len(results['filtered_doorship']):,}")
        
        with col2:
            st.metric("FBA Returns (Missing)", f"{len(results['fba_return']):,}")
            st.metric(
                f"Door Ship ({door_tat_min}-{door_tat_max} days TAT)",
                f"{len(results['doorship_tat']):,}"
            )
        
        with col3:
            st.metric("Safe-T Claims", f"{results['main']['Safe T Claim'].notna().sum():,}")
            st.metric(
                f"FBA Return (≥{int(fba_tat_min)} days TAT)",
                f"{len(results['fba_return_tat']):,}"
            )
        
        # Download Buttons - Each report saved to MongoDB individually when downloaded
        st.markdown("### 💾 Download Reports")
        
        col1, col2, col3 = st.columns(3)
        
        # Use centralized ui_utils
        
        with col1:
            download_module_report(
                df=results['filtered_doorship'],
                module_name=MODULE_NAME,
                report_name="Door Ship Returns",
                button_label="⬇️ Download Door Step",
                key="refund_door_step"
            )
        
        with col2:
            download_module_report(
                df=results['doorship_tat'],
                module_name=MODULE_NAME,
                report_name=f"Door Ship TAT ({door_tat_min}-{door_tat_max} days)",
                key="refund_doorship"
            )
        
        with col3:
            download_module_report(
                df=results['fba_return_tat'],
                module_name=MODULE_NAME,
                report_name=f"FBA Return TAT (≥{int(fba_tat_min)} days)",
                button_label=f"⬇️ Download FBA Return TAT (≥{int(fba_tat_min)}d)",
                key="refund_fba"
            )
else:
    st.info("👆 Please upload all required files to begin analysis")

# Footer
st.markdown("---")
st.markdown("*Developed for Amazon Seller Refund Analysis By IBI*")
