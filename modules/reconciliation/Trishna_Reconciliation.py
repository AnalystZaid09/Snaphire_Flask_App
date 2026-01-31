import streamlit as st
import pandas as pd
import re
from io import BytesIO
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from dotenv import load_dotenv
import os
from fuzzywuzzy import fuzz
from common.mongo import save_reconciliation_report
from common.ui_utils import apply_professional_style, get_download_filename, render_header, download_module_report
import warnings

# Suppress warnings
warnings.filterwarnings("ignore", module="fuzzywuzzy")

MODULE_NAME = "reconciliation"

# Load environment variables
load_dotenv()

# Page Configuration
st.set_page_config(
    page_title="Trishna Invoice Reconciliation",
    page_icon="🔍",
    layout="wide"
)

# Title and Description
# Apply Professional UI
apply_professional_style()
render_header("Trishna Invoice Reconciliation Tool", "Advanced fuzzy matching • Powered by IBI")

# Load Azure credentials from .env
endpoint = os.getenv("AZURE_ENDPOINT")
api_key = os.getenv("AZURE_KEY")

# Sidebar for Azure Credentials Status
with st.sidebar:
    st.header("About")
    st.info("This tool uses fuzzy matching to compare item descriptions, making it more flexible for items with slight variations in naming.")
    
    st.markdown("---")
    st.header("⚙️ Settings")
    fuzzy_threshold = st.slider(
        "Fuzzy Match Threshold (%)",
        min_value=50,
        max_value=100,
        value=70,
        step=5,
        help="Minimum similarity score to consider descriptions as matching"
    )
    qty_tolerance = st.number_input(
        "Quantity Tolerance",
        min_value=0.0,
        max_value=10.0,
        value=0.0,
        step=0.5,
        help="Acceptable difference in quantities (e.g., 0.5 allows ±0.5 difference)"
    )
    amount_tolerance = st.number_input(
        "Amount Tolerance (₹)",
        min_value=0.0,
        max_value=100.0,
        value=1.0,
        step=0.5,
        help="Acceptable difference in tax and total amounts"
    )

# Helper Functions
def clean_currency(value):
    """Clean currency values from Excel"""
    if pd.isna(value):
        return 0.0
    cleaned = re.sub(r'[^0-9.]', '', str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def clean_extracted_num(field):
    """Clean extracted numbers from PDF"""
    if not field:
        return 0.0
    if hasattr(field, 'value_number') and field.value_number is not None:
        return float(field.value_number)
    if hasattr(field, 'value_currency') and field.value_currency:
        return float(field.value_currency.amount)
    content = getattr(field, 'content', '0')
    cleaned = re.sub(r'[^0-9.]', '', str(content))
    try:
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

def load_and_clean_excel(file):
    """Load and clean Excel file"""
    try:
        # Load raw file to find SKU header
        raw_df = pd.read_excel(file, header=None)
        header_row_idx = raw_df[raw_df.apply(lambda r: r.astype(str).str.contains('SKU').any(), axis=1)].index[0]
        
        # Reload with correct header
        file.seek(0)
        df = pd.read_excel(file, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        
        # Create cleaned DataFrame
        cleaned_items = pd.DataFrame()
        
        # Material Code
        cleaned_items['Material Code'] = df.iloc[:, 0].astype(str).str.replace('TR-', '', regex=False).str.replace('WO-', '', regex=False).str.strip()
        
        # Description
        cleaned_items['Description'] = df.iloc[:, 1].astype(str).str.strip()
        
        # PO Ref No
        if 'PO Ref No.' in df.columns:
            cleaned_items['PO Ref No.'] = df['PO Ref No.'].astype(str).str.strip()
        else:
            cleaned_items['PO Ref No.'] = df.iloc[:, 3].astype(str).str.strip()
        
        # Quantities and amounts
        cleaned_items['Qty_EXCEL'] = df.iloc[:, 4].apply(clean_currency)
        cleaned_items['Tax_EXCEL'] = df.iloc[:, 10].apply(clean_currency)
        cleaned_items['Total_EXCEL'] = df.iloc[:, 11].apply(clean_currency)
        
        # Remove metadata rows
        cleaned_items = cleaned_items[cleaned_items['Material Code'] != 'nan'].reset_index(drop=True)
        
        return cleaned_items, None
    except Exception as e:
        return None, str(e)

def extract_pdf_data(pdf_file, endpoint, api_key):
    """Extract data from PDF using Azure Document Intelligence"""
    try:
        client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(api_key))
        
        pdf_bytes = pdf_file.read()
        poller = client.begin_analyze_document(
            "prebuilt-invoice", 
            AnalyzeDocumentRequest(bytes_source=pdf_bytes)
        )
        result = poller.result()
        
        all_line_items = []
        invoice_details = {
            "Invoice_No": "N/A",
            "Grand_Total": 0.0,
            "Total_Tax": 0.0
        }
        
        for invoice in result.documents:
            # Extract Invoice Number
            inv_id_obj = invoice.fields.get("InvoiceId")
            if inv_id_obj:
                invoice_details["Invoice_No"] = inv_id_obj.content.strip()
            
            # Extract line items
            items_field = invoice.fields.get("Items")
            if items_field and items_field.value_array:
                for item in items_field.value_array:
                    val = item.value_object
                    
                    desc_obj = val.get("Description")
                    desc = desc_obj.content.strip() if desc_obj else "N/A"
                    
                    # Filter out HSN/summary rows
                    if desc == "N/A" or desc == "" or "hsn" in desc.lower() or "summary" in desc.lower():
                        continue
                    
                    all_line_items.append({
                        "Description": desc,
                        "Qty_PDF": clean_extracted_num(val.get("Quantity")),
                        "Tax_PDF": clean_extracted_num(val.get("Tax")),
                        "Total_PDF": clean_extracted_num(val.get("Amount"))
                    })
            
            # Extract totals
            invoice_details["Grand_Total"] = clean_extracted_num(invoice.fields.get("InvoiceTotal"))
            invoice_details["Total_Tax"] = clean_extracted_num(invoice.fields.get("TotalTax"))
        
        df = pd.DataFrame(all_line_items)
        df = df.drop_duplicates().reset_index(drop=True)
        return df, invoice_details, None
    except Exception as e:
        return None, None, str(e)

def reconcile_data(excel_df, pdf_df, pdf_details, fuzzy_threshold=70, qty_tolerance=0.0, amount_tolerance=1.0):
    """Perform reconciliation with fuzzy matching and tolerance"""
    # Preprocessing Excel Descriptions - remove 'Trishna' prefix
    excel_df['Clean_Desc_Excel'] = excel_df['Description'].str.replace(r'^Trishna\s*', '', regex=True, flags=re.IGNORECASE).str.strip()
    
    # Summary Level Validations
    excel_total_qty = excel_df['Qty_EXCEL'].sum()
    excel_total_tax = excel_df['Tax_EXCEL'].sum()
    excel_total_amt = excel_df['Total_EXCEL'].sum()
    excel_item_count = len(excel_df)
    
    pdf_item_count = len(pdf_df)
    pdf_total_qty = pdf_df['Qty_PDF'].sum()
    
    results_summary = [
        ("Item Count", excel_item_count, pdf_item_count, excel_item_count == pdf_item_count),
        ("Total Quantity Sum", excel_total_qty, pdf_total_qty, abs(excel_total_qty - pdf_total_qty) <= qty_tolerance),
        ("Total Tax (Footer)", excel_total_tax, pdf_details['Total_Tax'], abs(excel_total_tax - pdf_details['Total_Tax']) <= amount_tolerance),
        ("Grand Total (Footer)", excel_total_amt, pdf_details['Grand_Total'], abs(excel_total_amt - pdf_details['Grand_Total']) <= amount_tolerance)
    ]
    
    summary_df = pd.DataFrame(results_summary, columns=['Metric', 'Excel_Value', 'PDF_Value', 'Match'])
    
    # Convert values to strings for display
    summary_df['Excel_Value'] = summary_df['Excel_Value'].astype(str)
    summary_df['PDF_Value'] = summary_df['PDF_Value'].astype(str)
    summary_df['Match'] = summary_df['Match'].apply(lambda x: "✅" if x else "❌")
    
    # Line Item Comparison with Fuzzy Matching
    comparison_results = []
    
    for _, pdf_row in pdf_df.iterrows():
        best_match = None
        highest_score = 0
        pdf_desc = str(pdf_row['Description'])
        
        for _, ex_row in excel_df.iterrows():
            score = fuzz.token_set_ratio(pdf_desc.lower(), ex_row['Clean_Desc_Excel'].lower())
            if score > highest_score:
                highest_score = score
                best_match = ex_row
        
        # Threshold check for the match
        if best_match is not None and highest_score >= fuzzy_threshold:
            qty_match = abs(pdf_row['Qty_PDF'] - best_match['Qty_EXCEL']) <= qty_tolerance
            comparison_results.append({
                'PDF_Description': pdf_desc,
                'Excel_Match': best_match['Clean_Desc_Excel'],
                'PDF_Qty': pdf_row['Qty_PDF'],
                'Excel_Qty': best_match['Qty_EXCEL'],
                'Qty_Match': "✅" if qty_match else "❌"
            })
        else:
            comparison_results.append({
                'PDF_Description': pdf_desc,
                'Excel_Match': "NOT FOUND",
                'PDF_Qty': pdf_row['Qty_PDF'],
                'Excel_Qty': 0,
                'Qty_Match': "❌"
            })
    
    line_item_df = pd.DataFrame(comparison_results)
    
    return summary_df, line_item_df

def calculate_accuracy(summary_df, line_item_df):
    """Calculate accuracy metrics"""
    # Summary Accuracy
    summary_matches = (summary_df['Match'] == "✅").sum()
    summary_total = len(summary_df)
    summary_acc = (summary_matches / summary_total) * 100
    
    # Line Item Accuracy
    line_matches = (line_item_df['Qty_Match'] == "✅").sum()
    line_total = len(line_item_df)
    line_acc = (line_matches / line_total) * 100 if line_total > 0 else 0
    
    # Overall Weighted Accuracy
    overall_matches = summary_matches + line_matches
    overall_total = summary_total + line_total
    overall_acc = (overall_matches / overall_total) * 100
    
    return summary_acc, line_acc, overall_acc

def create_excel_report(summary_df, line_item_df, accuracy_metrics, pdf_details):
    """Create downloadable Excel report"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Summary sheet
        summary_info = pd.DataFrame({
            'Report': ['Trishna Invoice Reconciliation Report'],
            'Invoice Number': [pdf_details['Invoice_No']],
            'Summary Accuracy': [f"{accuracy_metrics[0]:.2f}%"],
            'Line Item Accuracy': [f"{accuracy_metrics[1]:.2f}%"],
            'Overall Accuracy': [f"{accuracy_metrics[2]:.2f}%"]
        })
        summary_info.to_excel(writer, sheet_name='Summary', index=False)
        
        # Line Items comparison
        line_item_df.to_excel(writer, sheet_name='Line Items Comparison', index=False)
        
        # Summary comparison
        summary_df.to_excel(writer, sheet_name='Totals Verification', index=False)
    
    output.seek(0)
    return output

# Main Application
col1, col2 = st.columns(2)

with col1:
    pdf_file = st.file_uploader("📄 Upload PDF Invoice", type=['pdf'])

with col2:
    excel_file = st.file_uploader("📊 Upload Excel File", type=['xlsx', 'xls'])

if st.button("🔍 Start Reconciliation", type="primary", disabled=not (pdf_file and excel_file and endpoint and api_key)):
    with st.spinner("Processing files with fuzzy matching..."):
        # Process Excel
        excel_df, excel_error = load_and_clean_excel(excel_file)
        
        if excel_error:
            st.error(f"Excel Processing Error: {excel_error}")
        else:
            st.success(f"✅ Excel loaded: {len(excel_df)} items found")
            
            # Process PDF
            pdf_df, pdf_details, pdf_error = extract_pdf_data(pdf_file, endpoint, api_key)
            
            if pdf_error:
                st.error(f"PDF Processing Error: {pdf_error}")
            else:
                st.success(f"✅ PDF processed: Invoice #{pdf_details['Invoice_No']}")
                
                # Perform Reconciliation with tolerance settings
                summary_df, line_item_df = reconcile_data(
                    excel_df, 
                    pdf_df, 
                    pdf_details,
                    fuzzy_threshold=fuzzy_threshold,
                    qty_tolerance=qty_tolerance,
                    amount_tolerance=amount_tolerance
                )
                
                # Calculate Accuracy
                summary_acc, line_acc, overall_acc = calculate_accuracy(summary_df, line_item_df)
                
                # Display Results
                st.markdown("---")
                st.header(f"📊 Reconciliation Results: Invoice #{pdf_details['Invoice_No']}")
                
                # Accuracy metrics
                col_acc1, col_acc2, col_acc3, col_acc4 = st.columns(4)
                col_acc1.metric("Overall Accuracy", f"{overall_acc:.1f}%")
                col_acc2.metric("Summary Accuracy", f"{summary_acc:.1f}%")
                col_acc3.metric("Line Item Accuracy", f"{line_acc:.1f}%")
                col_acc4.metric("Total Items", f"{len(pdf_df)}")
                
                # Summary comparison
                st.subheader("📋 Summary & Totals Verification")
                st.dataframe(summary_df, use_container_width=True)
                
                # Line items comparison
                st.subheader("📝 Line Items Comparison (Fuzzy Matched)")
                st.dataframe(line_item_df, use_container_width=True)
                
                # Download button
                excel_data = create_excel_report(
                    summary_df, 
                    line_item_df, 
                    (summary_acc, line_acc, overall_acc),
                    pdf_details
                )
                download_module_report(
                    df=line_item_df,
                    module_name=MODULE_NAME,
                    report_name=f"Comparison_Report_Trishna_{pdf_details['Invoice_No']}",
                    button_label="📥 Download Detailed Excel Report",
                    key="dl_trishna_recon"
                )

                # Save to MongoDB
                try:
                     save_reconciliation_report(
                        collection_name="trishna_reconciliation",
                        invoice_no=pdf_details['Invoice_No'],
                        summary_data=summary_df,
                        line_items_data=line_item_df,
                        metadata={
                            "overall_accuracy_pct": overall_acc,
                            "summary_accuracy_pct": summary_acc,
                            "line_item_accuracy_pct": line_acc,
                            "file_name_pdf": pdf_file.name,
                            "file_name_excel": excel_file.name,
                            "timestamp": str(pd.Timestamp.now())
                        }
                    )
                except Exception as e:
                    st.error(f"Failed to auto-save to MongoDB: {e}")

# Footer
st.markdown("---")
st.markdown("**Trishna Invoice Reconciliation Tool** | Advanced fuzzy matching • Powered by IBI")
