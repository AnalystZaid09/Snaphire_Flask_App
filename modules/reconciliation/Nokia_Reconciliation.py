import streamlit as st
import pandas as pd
import re
import os
import io
import warnings
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "reconciliation"

# Load environment variables
load_dotenv()
ENDPOINT = os.getenv("AZURE_ENDPOINT")
KEY = os.getenv("AZURE_KEY")

# Suppress fuzzywuzzy warnings
warnings.filterwarnings("ignore", module="fuzzywuzzy")
# Apply Professional UI
apply_professional_style()

# Streamlit App
st.set_page_config(page_title="Nokia Reconciliation", layout="wide")
render_header("Nokia Invoice Reconciliation", None)

# --- Configuration ---
THRESHOLD = st.sidebar.slider("Numerical Tolerance (Threshold)", 0.0, 5.0, 1.0, 0.1)
st.sidebar.info(f"Differences within {THRESHOLD} will be marked as a Match.")

# --- Helper Functions ---
def clean_num(field):
    if not field: return 0.0
    if hasattr(field, 'value_number') and field.value_number is not None:
        return float(field.value_number)
    if hasattr(field, 'value_currency') and field.value_currency:
        return float(field.value_currency.amount)
    content = getattr(field, 'content', '0')
    cleaned = re.sub(r'[^0-9.]', '', str(content))
    try: return float(cleaned)
    except: return 0.0

def is_within_tolerance(v1, v2, limit=THRESHOLD):
    return abs(float(v1) - float(v2)) <= limit

def load_excel(file):
    raw_df = pd.read_excel(file, header=None)
    header_idx = raw_df[raw_df.apply(lambda r: r.astype(str).str.contains('SKU').any(), axis=1)].index[0]
    df = pd.read_excel(file, header=header_idx)
    df.columns = df.columns.astype(str).str.strip()
    
    clean_df = pd.DataFrame()
    clean_df['Description'] = df.iloc[:, 1].astype(str).str.strip()
    clean_df['Qty_EXCEL'] = df.iloc[:, 4].apply(lambda x: clean_num(type('obj', (object,), {'content': x})()))
    clean_df['Tax_EXCEL'] = df.iloc[:, 10].apply(lambda x: clean_num(type('obj', (object,), {'content': x})()))
    clean_df['Total_EXCEL'] = df.iloc[:, 11].apply(lambda x: clean_num(type('obj', (object,), {'content': x})()))
    
    # --- Find these lines in your load_excel function ---
    if 'PO Ref No.' in df.columns:
        # Update this line to strip the symbols
        clean_df['PO_Ref'] = df['PO Ref No.'].astype(str).str.strip("['").str.strip("']").str.strip()
    else:
        # Update this line as well for the index-based fallback
        clean_df['PO_Ref'] = df.iloc[:, 3].astype(str).str.strip("['").str.strip("']").str.strip()
    return clean_df.dropna(subset=['Description'])

def extract_pdf(file):
    client = DocumentIntelligenceClient(ENDPOINT, AzureKeyCredential(KEY))
    poller = client.begin_analyze_document("prebuilt-invoice", AnalyzeDocumentRequest(bytes_source=file.read()))
    result = poller.result()
    
    summary = {"Inv_No": "N/A", "Tax": 0.0, "Total": 0.0}
    items = []
    for inv in result.documents:
        summary["Inv_No"] = inv.fields.get("InvoiceId").content if inv.fields.get("InvoiceId") else "N/A"
        summary["Tax"] = clean_num(inv.fields.get("TotalTax"))
        summary["Total"] = clean_num(inv.fields.get("InvoiceTotal"))
        
        for item in inv.fields.get("Items").value_array:
            val = item.value_object
            desc = val.get("Description").content if val.get("Description") else ""
            if any(x in desc.lower() for x in ["hsn", "gst", "total", "summary"]): continue
            items.append({
                "Desc": desc.split('\n')[0],
                "Qty": clean_num(val.get("Quantity"))
            })
    return pd.DataFrame(items), summary

# --- File Upload Section ---
up_pdf = st.file_uploader("Upload Invoice PDF", type="pdf")
up_xlsx = st.file_uploader("Upload Excel SKU File", type="xlsx")

# --- Process Button ---
if up_pdf and up_xlsx:
    if st.button("🚀 Process Files", use_container_width=True):
        with st.spinner("🔄 Reconciling Data... Please wait."):
            try:
                # Load and Extract
                ex_df = load_excel(up_xlsx)
                pdf_df, pdf_sum = extract_pdf(up_pdf)
                
                # Preprocessing
                ex_df['Clean_Desc'] = ex_df['Description'].str.replace(r'^ACD\s*', '', regex=True, flags=re.IGNORECASE)
                
                # Aggregations
                ex_total_qty = ex_df['Qty_EXCEL'].sum()
                ex_total_tax = ex_df['Tax_EXCEL'].sum()
                ex_total_amt = ex_df['Total_EXCEL'].sum()
                pdf_total_qty = pdf_df['Qty'].sum()

                # Summary Checks
                po_refs = ex_df['PO_Ref'].unique().tolist()
                id_match = any(ref in pdf_sum['Inv_No'] or pdf_sum['Inv_No'] in ref for ref in po_refs)
                
                summary_results = [
                    {"Metric": "PO Ref / Invoice ID", "Excel": str(po_refs), "PDF": pdf_sum['Inv_No'], "Match": id_match},
                    {"Metric": "Total Quantity Sum", "Excel": ex_total_qty, "PDF": pdf_total_qty, "Match": is_within_tolerance(ex_total_qty, pdf_total_qty)},
                    {"Metric": "Total Tax Amount", "Excel": f"₹{ex_total_tax:,.2f}", "PDF": f"₹{pdf_sum['Tax']:,.2f}", "Match": is_within_tolerance(ex_total_tax, pdf_sum['Tax'])},
                    {"Metric": "Grand Total", "Excel": f"₹{ex_total_amt:,.2f}", "PDF": f"₹{pdf_sum['Total']:,.2f}", "Match": is_within_tolerance(ex_total_amt, pdf_sum['Total'])}
                ]

                # Line Item Comparison
                recon_details = []
                match_count = 0
                for _, p_row in pdf_df.iterrows():
                    best_score, best_match = 0, None
                    for _, e_row in ex_df.iterrows():
                        score = fuzz.token_set_ratio(p_row['Desc'].lower(), e_row['Clean_Desc'].lower())
                        if score > best_score:
                            best_score, best_match = score, e_row
                    
                    qty_match = is_within_tolerance(p_row['Qty'], best_match['Qty_EXCEL']) if best_score > 60 else False
                    if qty_match: match_count += 1
                    
                    recon_details.append({
                        "PDF Description": p_row['Desc'],
                        "Excel Match": best_match['Description'] if best_match is not None else "N/A",
                        "PDF Qty": p_row['Qty'],
                        "Excel Qty": best_match['Qty_EXCEL'] if best_match is not None else 0,
                        "Match Status": "✅ Match" if qty_match else "❌ Mismatch"
                    })
                
                # --- Result Display ---
                st.subheader("SUMMARY VALIDATION")
                st.table(pd.DataFrame(summary_results))

                st.subheader("LINE ITEM QUANTITY CHECK")
                detailed_df = pd.DataFrame(recon_details)
                st.dataframe(detailed_df, use_container_width=True)

                # Accuracy Calculation
                total_pts = len(summary_results) + len(pdf_df)
                matched_pts = sum(1 for x in summary_results if x['Match']) + match_count
                accuracy = (matched_pts / total_pts) * 100
                st.success(f"### Overall Accuracy: {accuracy:.2f}%")

                # --- Excel Export ---
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    detailed_df.to_excel(writer, index=False, sheet_name='Line_Items')
                    pd.DataFrame(summary_results).to_excel(writer, index=False, sheet_name='Summary_Validation')
                
                # Save to MongoDB
                try:
                     # This uses the fixed common.mongo utility
                     save_reconciliation_report(
                        collection_name="nokia_reconciliation",
                        invoice_no=pdf_sum['Inv_No'],
                        summary_data=pd.DataFrame(summary_results),
                        line_items_data=detailed_df,
                        metadata={
                            "accuracy": accuracy,
                            "file_name_pdf": up_pdf.name if up_pdf else "unknown",
                             "file_name_excel": up_xlsx.name if up_xlsx else "unknown"
                        }
                    )
                except Exception as e:
                    logger.warning(f"Auto-save error: {e}")

                # Standardized download section
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    download_module_report(
                        df=detailed_df,
                        module_name="reconciliation",
                        report_name=f"Nokia_Detailed_{pdf_sum['Inv_No']}",
                        button_label="📥 Download Detailed Report",
                        key="dl_nokia_detailed"
                    )
                with col_dl2:
                    download_module_report(
                        df=pd.DataFrame(summary_results),
                        module_name="reconciliation",
                        report_name=f"Nokia_Summary_{pdf_sum['Inv_No']}",
                        button_label="📥 Download Summary",
                        key="dl_nokia_summary"
                    )

            except Exception as e:
                st.error(f"Error during processing: {e}")
else:
    st.info("Please upload both the PDF and Excel files to continue.")
