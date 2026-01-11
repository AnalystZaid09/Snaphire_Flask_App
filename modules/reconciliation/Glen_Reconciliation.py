import streamlit as st
import pandas as pd
import re
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from dotenv import load_dotenv
import os
from io import BytesIO
from mongo_utils import save_reconciliation_report
from ui_utils import apply_professional_style, get_download_filename, render_header

# Load environment variables
load_dotenv()

# Azure credentials from .env file
ENDPOINT = os.getenv("AZURE_ENDPOINT")
KEY = os.getenv("AZURE_KEY")

# Helper functions
def clean_num(field):
    """Helper to clean and extract numeric values."""
    if not field:
        return 0.0
    if hasattr(field, 'value_number') and field.value_number is not None:
        return float(field.value_number)
    if hasattr(field, 'value_currency') and field.value_currency:
        return float(field.value_currency.amount)
    content = getattr(field, 'content', '0')
    cleaned = re.sub(r'[^0-9.]', '', str(content))
    try:
        return float(cleaned)
    except:
        return 0.0

def parse_description_and_qty(content):
    """Split content '10 | G.CT1054 UTSS' into Qty and Description."""
    if not content:
        return 0.0, "N/A"
    parts = content.split('|')
    if len(parts) >= 2:
        qty_str = re.sub(r'[^0-9.]', '', parts[0].strip())
        qty = float(qty_str) if qty_str else 0.0
        desc = " ".join(parts[1:]).strip()
        return qty, desc
    else:
        match = re.match(r'^(\d+)\s+(.*)', content.strip())
        if match:
            return float(match.group(1)), match.group(2)
        return 0.0, content.strip()

def load_and_clean_excel(file_path):
    """Load and clean Excel data."""
    raw_df = pd.read_excel(file_path, header=None)
    header_row_idx = raw_df[raw_df.apply(lambda r: r.astype(str).str.contains('SKU').any(), axis=1)].index[0]
    
    df = pd.read_excel(file_path, header=header_row_idx)
    df.columns = df.columns.astype(str).str.strip()

    cleaned_items = pd.DataFrame()
    
    cleaned_items['Material Code'] = df.iloc[:, 0].astype(str).str.replace('TR-', '', regex=False).str.replace('WO-', '', regex=False).str.strip()
    cleaned_items['Description'] = df.iloc[:, 1].astype(str).str.strip()
    
    if 'PO Ref No.' in df.columns:
        cleaned_items['PO Ref No.'] = df['PO Ref No.'].astype(str).str.strip()
    else:
        cleaned_items['PO Ref No.'] = df.iloc[:, 3].astype(str).str.strip()
    
    def clean_currency(value):
        if pd.isna(value):
            return 0.0
        cleaned = re.sub(r'[^0-9.]', '', str(value))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    cleaned_items['Qty_EXCEL'] = df.iloc[:, 4].apply(clean_currency)
    cleaned_items['Tax_EXCEL'] = df.iloc[:, 10].apply(clean_currency)
    cleaned_items['Total_EXCEL'] = df.iloc[:, 11].apply(clean_currency)
    
    cleaned_items = cleaned_items[cleaned_items['Material Code'] != 'nan'].reset_index(drop=True)
    
    return cleaned_items

def extract_pdf_complete_data(pdf_file):
    """Extract complete data from PDF using Azure Document Intelligence."""
    client = DocumentIntelligenceClient(ENDPOINT, AzureKeyCredential(KEY))
    
    pdf_bytes = pdf_file.read()
    poller = client.begin_analyze_document(
        "prebuilt-invoice", AnalyzeDocumentRequest(bytes_source=pdf_bytes)
    )
    result = poller.result()
    
    all_line_items = []
    invoice_summary = {
        "Invoice_No": "N/A",
        "Sub_Total": 0.0,
        "Grand_Total": 0.0,
        "Total_Tax_Azure": 0.0,
        "Calculated_Tax": 0.0
    }

    for invoice in result.documents:
        fields = invoice.fields
        
        invoice_summary['Invoice_No'] = fields.get("InvoiceId").content if fields.get("InvoiceId") else "N/A"
        sub_total = clean_num(fields.get("SubTotal"))
        grand_total = clean_num(fields.get("InvoiceTotal"))
        total_tax_field = clean_num(fields.get("TotalTax"))

        calculated_tax = total_tax_field if total_tax_field > 0 else (grand_total - sub_total)
        
        invoice_summary.update({
            "Sub_Total": sub_total,
            "Grand_Total": grand_total,
            "Total_Tax_Azure": total_tax_field,
            "Calculated_Tax": round(calculated_tax, 2)
        })

        items_field = fields.get("Items")
        if items_field and items_field.value_array:
            for item in items_field.value_array:
                val = item.value_object
                
                raw_desc = val.get("Description").content if val.get("Description") else ""
                qty_extracted, desc_extracted = parse_description_and_qty(raw_desc)
                
                if val.get("Quantity"):
                    qty_extracted = clean_num(val.get("Quantity"))

                cgst = clean_num(val.get("CGST"))
                sgst = clean_num(val.get("SGST"))
                item_tax = cgst + sgst if (cgst + sgst) > 0 else clean_num(val.get("Tax"))

                if "hsn" in desc_extracted.lower() or "summary" in desc_extracted.lower() or desc_extracted == "":
                    continue

                all_line_items.append({
                    "Description": desc_extracted,
                    "Qty_PDF": qty_extracted,
                    "Amount_Base": clean_num(val.get("Amount")),
                    "CGST": cgst,
                    "SGST": sgst,
                    "Total_Tax_Item": item_tax
                })

    df = pd.DataFrame(all_line_items).drop_duplicates().reset_index(drop=True)
    return df, invoice_summary

def extract_numbers(text):
    """Extract all digits from string and join them."""
    if not text:
        return ""
    nums = re.findall(r'\d+', str(text))
    return "".join(nums)

def reconcile_with_numeric_logic(excel_df, pdf_df, summary, tolerance=7.0):
    """Perform reconciliation between Excel and PDF data."""
    reconciliation_results = []
    
    excel_total_tax = excel_df['Tax_EXCEL'].sum()
    excel_grand_total = excel_df['Total_EXCEL'].sum()
    
    tax_match = abs(excel_total_tax - summary['Calculated_Tax']) <= tolerance
    total_match = abs(excel_grand_total - summary['Grand_Total']) <= tolerance

    # Count matches for accuracy calculation
    match_count = 0
    total_items = len(excel_df)

    global_validation = {
        "Invoice_No": summary['Invoice_No'],
        "Excel_Total_Tax": excel_total_tax,
        "PDF_Total_Tax": summary['Calculated_Tax'],
        "Tax_Match": tax_match,
        "Excel_Grand_Total": excel_grand_total,
        "PDF_Grand_Total": summary['Grand_Total'],
        "Total_Match": total_match
    }
    
    for _, ex_row in excel_df.iterrows():
        mat_code_raw = str(ex_row['Material Code']).strip()
        ex_digits = extract_numbers(mat_code_raw)
        
        match_found = False
        for _, pdf_row in pdf_df.iterrows():
            pdf_digits = extract_numbers(pdf_row['Description'])
            
            if ex_digits and (ex_digits in pdf_digits):
                match_found = True
                
                qty_match = ex_row['Qty_EXCEL'] == pdf_row['Qty_PDF']
                pdf_item_total = pdf_row['Amount_Base'] + pdf_row['Total_Tax_Item']
                amt_match = abs(ex_row['Total_EXCEL'] - pdf_item_total) <= tolerance
                
                is_match = qty_match and amt_match
                if is_match:
                    match_count += 1
                
                reconciliation_results.append({
                    'Material Code': mat_code_raw,
                    'Qty_Excel': ex_row['Qty_EXCEL'],
                    'Qty_PDF': pdf_row['Qty_PDF'],
                    'Amount_Excel': round(ex_row['Total_EXCEL'], 2),
                    'Amount_PDF': round(pdf_item_total, 2),
                    'Status': "✅ MATCH" if is_match else "⚠️ DIFF"
                })
                break
        
        if not match_found:
            reconciliation_results.append({
                'Material Code': mat_code_raw,
                'Qty_Excel': ex_row['Qty_EXCEL'],
                'Qty_PDF': 0,
                'Amount_Excel': round(ex_row['Total_EXCEL'], 2),
                'Amount_PDF': 0,
                'Status': "❌ NOT_FOUND"
            })

    # Calculate accuracy
    accuracy = (match_count / total_items * 100) if total_items > 0 else 0
    global_validation['Accuracy'] = round(accuracy, 2)
    global_validation['Matched_Items'] = match_count
    global_validation['Total_Items'] = total_items

    return pd.DataFrame(reconciliation_results), global_validation

# Main app layout
col1, col2 = st.columns(2)

with col1:
    st.subheader("📁 Upload Excel File")
    excel_file = st.file_uploader("Choose Excel file", type=['xlsx', 'xls'], key="excel")

with col2:
    st.subheader("📄 Upload PDF Invoice")
    pdf_file = st.file_uploader("Choose PDF file", type=['pdf'], key="pdf")

tolerance = st.sidebar.slider("Tolerance Level (₹)", 0.0, 20.0, 7.0, 0.5)

if st.button("🔍 Run Reconciliation", type="primary", use_container_width=True):
    if excel_file is None or pdf_file is None:
        st.error("⚠️ Please upload both Excel and PDF files.")
    else:
        try:
            with st.spinner("Processing files..."):
                # Save uploaded files temporarily
                with open("temp_excel.xlsx", "wb") as f:
                    f.write(excel_file.getbuffer())
                
                # Load and process data
                excel_df = load_and_clean_excel("temp_excel.xlsx")
                pdf_df, summary = extract_pdf_complete_data(pdf_file)
                final_report, global_val = reconcile_with_numeric_logic(excel_df, pdf_df, summary, tolerance)
            
            st.success("✅ Reconciliation completed successfully!")
            
            # Display overall accuracy
            st.header("🎯 Overall Accuracy")
            accuracy_col1, accuracy_col2, accuracy_col3 = st.columns(3)
            
            with accuracy_col1:
                st.metric("Accuracy Score", f"{global_val['Accuracy']}%", 
                         help="Percentage of items that matched between Excel and PDF")
            
            with accuracy_col2:
                st.metric("Matched Items", f"{global_val['Matched_Items']}/{global_val['Total_Items']}")
            
            with accuracy_col3:
                if global_val['Accuracy'] >= 90:
                    st.success("🟢 Excellent Match")
                elif global_val['Accuracy'] >= 70:
                    st.warning("🟡 Good Match")
                else:
                    st.error("🔴 Poor Match")
            
            # Display global validation
            st.header("📊 Global Validation Summary")
            st.subheader(f"Invoice: {global_val['Invoice_No']}")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Excel Total Tax", f"₹{global_val['Excel_Total_Tax']:,.2f}")
                st.metric("PDF Total Tax", f"₹{global_val['PDF_Total_Tax']:,.2f}")
                if global_val['Tax_Match']:
                    st.success("✅ Tax Match")
                else:
                    st.error("❌ Tax Mismatch")
            
            with col2:
                st.metric("Excel Grand Total", f"₹{global_val['Excel_Grand_Total']:,.2f}")
                st.metric("PDF Grand Total", f"₹{global_val['PDF_Grand_Total']:,.2f}")
                if global_val['Total_Match']:
                    st.success("✅ Total Match")
                else:
                    st.error("❌ Total Mismatch")
            
            with col3:
                st.metric("Sub Total", f"₹{summary['Sub_Total']:,.2f}")
                st.metric("Calculated Tax", f"₹{summary['Calculated_Tax']:,.2f}")
            
            # Display line item reconciliation
            st.header("📋 Line Item Reconciliation")
            
            # Color code the status
            def highlight_status(row):
                if row['Status'] == "✅ MATCH":
                    return ['background-color: #d4edda'] * len(row)
                elif row['Status'] == "⚠️ DIFF":
                    return ['background-color: #fff3cd'] * len(row)
                else:
                    return ['background-color: #f8d7da'] * len(row)
            
            styled_df = final_report.style.apply(highlight_status, axis=1)
            st.dataframe(styled_df, use_container_width=True)
            
            # Create comprehensive Excel file
            st.header("💾 Download Comprehensive Report")
            
            # Create Excel writer object
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Sheet 1: Summary
                summary_data = {
                    'Metric': [
                        'Invoice Number',
                        'Overall Accuracy (%)',
                        'Matched Items',
                        'Total Items',
                        'Excel Total Tax (₹)',
                        'PDF Total Tax (₹)',
                        'Tax Match Status',
                        'Excel Grand Total (₹)',
                        'PDF Grand Total (₹)',
                        'Grand Total Match Status',
                        'Sub Total (₹)',
                        'Calculated Tax (₹)',
                        'Tolerance Level (₹)'
                    ],
                    'Value': [
                        global_val['Invoice_No'],
                        global_val['Accuracy'],
                        global_val['Matched_Items'],
                        global_val['Total_Items'],
                        round(global_val['Excel_Total_Tax'], 2),
                        round(global_val['PDF_Total_Tax'], 2),
                        '✅ Match' if global_val['Tax_Match'] else '❌ Mismatch',
                        round(global_val['Excel_Grand_Total'], 2),
                        round(global_val['PDF_Grand_Total'], 2),
                        '✅ Match' if global_val['Total_Match'] else '❌ Mismatch',
                        round(summary['Sub_Total'], 2),
                        round(summary['Calculated_Tax'], 2),
                        tolerance
                    ]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                # Sheet 2: Line Item Reconciliation
                final_report.to_excel(writer, sheet_name='Line Items', index=False)
                
                # Sheet 3: Excel Data
                excel_df.to_excel(writer, sheet_name='Excel Data', index=False)
                
                # Sheet 4: PDF Data
                pdf_df.to_excel(writer, sheet_name='PDF Data', index=False)
            
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Download Complete Reconciliation Report (Excel)",
                data=output.getvalue(),
                file_name=get_download_filename(f"Glen_Reconciliation_{global_val['Invoice_No']}"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # Also provide CSV option
            csv = final_report.to_csv(index=False)
            st.download_button(
                label="Download Line Items Only (CSV)",
                data=csv,
                file_name=get_download_filename(f"line_items_{global_val['Invoice_No']}", "csv"),
                mime="text/csv"
            )
            
            # Cleanup
            os.remove("temp_excel.xlsx")
            
            # Save to MongoDB
            try:
                 save_reconciliation_report(
                    collection_name="glen_reconciliation",
                    invoice_no=global_val['Invoice_No'],
                    summary_data=pd.DataFrame([global_val]),
                    line_items_data=final_report,
                    metadata={
                        "accuracy": global_val['Accuracy'],
                        "file_name_pdf": pdf_file.name,
                        "file_name_excel": excel_file.name,
                        "timestamp": str(pd.Timestamp.now())
                    }
                )
            except Exception as e:
                st.error(f"Failed to auto-save to MongoDB: {e}")

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)

# Sidebar information
st.sidebar.title("ℹ️ About")
st.sidebar.info(
    """
    This tool reconciles invoice data between Excel and PDF files using Azure Document Intelligence.
    
    **Features:**
    - Automatic data extraction from PDF invoices
    - Excel data cleaning and processing
    - Line-by-line reconciliation
    - Global totals validation
    - Downloadable reports
    """
)

st.sidebar.title("📖 Instructions")
st.sidebar.markdown(
    """
    1. Upload your Excel file containing invoice data
    2. Upload the corresponding PDF invoice
    3. Adjust tolerance level if needed
    4. Click 'Run Reconciliation'
    5. Review results and download the report
    """
)