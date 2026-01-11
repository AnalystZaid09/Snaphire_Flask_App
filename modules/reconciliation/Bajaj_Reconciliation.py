import streamlit as st
import pandas as pd
import re
from io import BytesIO
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from dotenv import load_dotenv
import os
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

# Apply Professional UI
apply_professional_style()

# Render header
render_header("Bajaj Invoice Reconciliation System", "Automated Reconciliation for Bajaj Invoices vs Excel PO")

# Load Azure credentials from .env
endpoint = os.getenv("AZURE_ENDPOINT")
api_key = os.getenv("AZURE_KEY")

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
        file.seek(0)  # Reset file pointer
        df = pd.read_excel(file, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        
        # Create cleaned DataFrame
        cleaned_items = pd.DataFrame()
        
        # Material Code
        cleaned_items['Material Code'] = df.iloc[:, 0].astype(str).str.replace('BA-', '', regex=False).str.replace('WO-', '', regex=False).str.strip()
        
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

def perform_reconciliation(pdf_df, excel_df, pdf_details, pdf_filename, excel_filename):
    """Perform reconciliation and return results"""
    # Line Item Comparison
    pdf_df['Match_Key'] = pdf_df['Description'].str.strip().str.lower().str[:10]
    excel_df['Match_Key'] = excel_df['Description'].str.strip().str.lower().str[:10]
    
    comparison_df = pd.merge(
        pdf_df,
        excel_df[['Match_Key', 'Description', 'Qty_EXCEL', 'Tax_EXCEL', 'Total_EXCEL']],
        on='Match_Key',
        how='outer',
        suffixes=('_PDF', '_EXCEL')
    )
    
    comparison_df = comparison_df.fillna(0)
    comparison_df['Qty_Match'] = comparison_df['Qty_PDF'] == comparison_df['Qty_EXCEL']
    comparison_df['Tax_Match'] = abs(comparison_df['Tax_PDF'] - comparison_df['Tax_EXCEL']) < 1.0
    comparison_df['Total_Match'] = abs(comparison_df['Total_PDF'] - comparison_df['Total_EXCEL']) < 1.0
    
    # Summary calculations
    excel_total_items = len(excel_df)
    excel_tax_sum = excel_df['Tax_EXCEL'].sum()
    excel_grand_total = excel_df['Total_EXCEL'].sum()
    po_ref = excel_df['PO Ref No.'].iloc[0] if not excel_df.empty else "N/A"
    
    header_match = str(pdf_details['Invoice_No']).strip() == str(po_ref).strip()
    
    summary_results = {
        "Metric": [
            "Invoice No vs PO Ref No",
            "Total Items Count",
            "Total Tax (Sum)",
            "Grand Total (Sum)"
        ],
        "PDF Value": [
            str(pdf_details['Invoice_No']),
            str(len(pdf_df)),
            str(round(pdf_details['Total_Tax'], 2)),
            str(round(pdf_details['Grand_Total'], 2))
        ],
        "Excel Value": [
            str(po_ref),
            str(excel_total_items),
            str(round(excel_tax_sum, 2)),
            str(round(excel_grand_total, 2))
        ],
        "Match": [
            "Yes" if header_match else "No",
            "Yes" if len(pdf_df) == excel_total_items else "No",
            "Yes" if abs(pdf_details['Total_Tax'] - excel_tax_sum) < 1.0 else "No",
            "Yes" if abs(pdf_details['Grand_Total'] - excel_grand_total) < 1.0 else "No"
        ]
    }
    
    summary_df = pd.DataFrame(summary_results)
    accuracy = (comparison_df['Qty_Match'].sum() + comparison_df['Tax_Match'].sum() + comparison_df['Total_Match'].sum()) / (len(comparison_df) * 3) * 100 if len(comparison_df) > 0 else 0
    
    st.subheader("Reconciliation Summary")
    st.dataframe(summary_df, use_container_width=True)
    
    st.subheader("Line Items Comparison")
    st.dataframe(comparison_df, use_container_width=True)
    
    st.metric("Match Accuracy", f"{accuracy:.1f}%")
    
    # Create download report with both summary and line items
    st.subheader("📥 Download Report")
    
    # Create Excel file with multiple sheets
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        comparison_df.to_excel(writer, sheet_name='Line Items', index=False)
    
    excel_data = output.getvalue()
    
    download_module_report(
        df=comparison_df,
        module_name=MODULE_NAME,
        report_name=f"Bajaj Reconciliation {pdf_details['Invoice_No']}",
        button_label="📥 Download Reconciliation Report",
        key="dl_bajaj_recon"
    )
    
    # Save to MongoDB
    with st.spinner("Saving report to Database..."):
        save_reconciliation_report(
            collection_name="bajaj_reconciliation",
            invoice_no=pdf_details['Invoice_No'],
            summary_data=summary_df,
            line_items_data=comparison_df,
            metadata={
                "accuracy": accuracy,
                "pdf_items_count": len(pdf_df),
                "excel_items_count": len(excel_df),
                "file_name_pdf": pdf_filename,
                "file_name_excel": excel_filename
            }
        )

# File Upload Section
st.subheader("Upload Files")
col1, col2 = st.columns(2)

with col1:
    pdf_file = st.file_uploader("Upload Invoice PDF", type=["pdf"], key="bajaj_pdf")

with col2:
    excel_file = st.file_uploader("Upload Excel PO", type=["xlsx", "xls"], key="bajaj_excel")

# Process files when both are uploaded
if pdf_file and excel_file:
    if st.button("Run Reconciliation", type="primary", use_container_width=True):
        with st.spinner("Processing files..."):
            # Load Excel
            excel_df, excel_error = load_and_clean_excel(excel_file)
            if excel_error:
                st.error(f"Error loading Excel: {excel_error}")
                st.stop()
            
            # Extract PDF data
            pdf_df, pdf_details, pdf_error = extract_pdf_data(pdf_file, endpoint, api_key)
            if pdf_error:
                st.error(f"Error processing PDF: {pdf_error}")
                st.stop()
            
            if pdf_df is not None and excel_df is not None:
                # Perform reconciliation
                perform_reconciliation(pdf_df, excel_df, pdf_details, pdf_file.name, excel_file.name)
                st.success("Reconciliation Complete!")
else:
    st.info("Please upload both PDF invoice and Excel PO file to begin reconciliation.")

st.markdown("---")
st.markdown("**Invoice Reconciliation Tool** | Powered by Azure Document Intelligence")
