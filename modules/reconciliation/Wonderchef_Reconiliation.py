import streamlit as st
import pandas as pd
import re
import os
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
import io
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from common.ui_utils import apply_professional_style, render_header, download_module_report
from common.mongo import save_and_track_report

MODULE_NAME = "reconciliation"

# Page configuration
st.set_page_config(
    page_title="Wonderchef Invoice Reconciliation Tool",
    page_icon="📊",
    layout="wide"
)
apply_professional_style()

# Azure credentials from environment variables
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
AZURE_API_KEY = os.getenv("AZURE_KEY", "")

render_header("Wonderchef Invoice Reconciliation Tool", "Compare PDF invoices with Excel data to identify discrepancies")

# Sidebar for configuration
st.sidebar.header("⚙️ Configuration")
tolerance = st.sidebar.number_input(
    "Tolerance for Matching (₹)",
    min_value=0.0,
    max_value=100.0,
    value=7.0,
    step=0.1,
    help="Acceptable difference for tax and total amount matching"
)

def clean_currency(value):
    """Remove currency symbols and convert to float"""
    if pd.isna(value):
        return 0.0
    cleaned = re.sub(r'[^0-9.]', '', str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def clean_extracted_num(field):
    """Extract numbers from Azure Document Intelligence fields"""
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
        raw_df = pd.read_excel(file, header=None)
        header_row_idx = raw_df[raw_df.apply(lambda r: r.astype(str).str.contains('SKU').any(), axis=1)].index[0]
        
        df = pd.read_excel(file, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        
        cleaned_items = pd.DataFrame()
        cleaned_items['Material Code'] = df.iloc[:, 0].astype(str).str.replace('WO-', '', regex=False).str.strip()
        cleaned_items['Description'] = df.iloc[:, 1].astype(str).str.strip()
        cleaned_items['Qty_EXCEL'] = df.iloc[:, 4].apply(clean_currency)
        cleaned_items['Tax_EXCEL'] = df.iloc[:, 10].apply(clean_currency)
        cleaned_items['Total_EXCEL'] = df.iloc[:, 11].apply(clean_currency)
        
        cleaned_items = cleaned_items[cleaned_items['Material Code'] != 'nan'].reset_index(drop=True)
        return cleaned_items, None
    except Exception as e:
        return None, str(e)

def extract_pdf_data(file_bytes, endpoint, api_key):
    """Extract data from PDF using Azure Document Intelligence"""
    try:
        client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(api_key))
        
        poller = client.begin_analyze_document(
            "prebuilt-invoice", 
            AnalyzeDocumentRequest(bytes_source=file_bytes)
        )
        result = poller.result()
        
        all_line_items = []
        summary_data = {"Grand_Total": 0.0, "Total_Tax": 0.0}
        
        for invoice in result.documents:
            items_field = invoice.fields.get("Items")
            if items_field and items_field.value_array:
                for item in items_field.value_array:
                    val = item.value_object
                    
                    p_code_obj = val.get("ProductCode")
                    desc_obj = val.get("Description")
                    
                    if not p_code_obj or not p_code_obj.content.strip():
                        continue
                    
                    p_code = p_code_obj.content.strip()
                    desc = desc_obj.content.strip() if desc_obj else "N/A"
                    
                    if desc == "N/A" or desc == "":
                        continue
                    
                    all_line_items.append({
                        "Material Code": p_code,
                        "Description": desc,
                        "Qty_PDF": clean_extracted_num(val.get("Quantity")),
                        "Tax_PDF": clean_extracted_num(val.get("Tax")),
                        "Total_PDF": clean_extracted_num(val.get("Amount"))
                    })
            
            summary_data["Grand_Total"] = clean_extracted_num(invoice.fields.get("InvoiceTotal"))
            summary_data["Total_Tax"] = clean_extracted_num(invoice.fields.get("TotalTax"))
        
        df = pd.DataFrame(all_line_items)
        df = df.drop_duplicates().reset_index(drop=True)
        return df, summary_data, None
    except Exception as e:
        return None, None, str(e)

def reconcile_data(pdf_df, excel_df, pdf_totals, tolerance=7.0):
    """Reconcile PDF and Excel data"""
    comparison = pd.merge(
        pdf_df, 
        excel_df, 
        on="Material Code", 
        how="outer", 
        suffixes=('_PDF', '_EXCEL')
    )
    
    comparison['Description_PDF'] = comparison['Description_PDF'].fillna("MISSING").astype(str).str.strip()
    comparison['Description_EXCEL'] = comparison['Description_EXCEL'].fillna("MISSING").astype(str).str.strip()
    
    numeric_cols = ['Qty_PDF', 'Tax_PDF', 'Total_PDF', 'Qty_EXCEL', 'Tax_EXCEL', 'Total_EXCEL']
    comparison[numeric_cols] = comparison[numeric_cols].fillna(0)
    
    comparison['Qty_Match'] = comparison['Qty_PDF'] == comparison['Qty_EXCEL']
    comparison['Tax_Diff'] = (comparison['Tax_PDF'] - comparison['Tax_EXCEL']).abs()
    comparison['Tax_Status'] = comparison['Tax_Diff'] <= tolerance
    comparison['Amount_Diff'] = (comparison['Total_PDF'] - comparison['Total_EXCEL']).abs()
    comparison['Total_Match'] = comparison['Amount_Diff'] <= tolerance
    
    total_check_points = len(comparison) * 3
    successful_points = (
        comparison['Qty_Match'].sum() + 
        comparison['Tax_Status'].sum() + 
        comparison['Total_Match'].sum()
    )
    accuracy_score = (successful_points / total_check_points) * 100 if total_check_points > 0 else 0
    
    return comparison, accuracy_score

# File upload section
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Upload PDF Invoice")
    pdf_file = st.file_uploader("Choose PDF file", type=['pdf'], key="pdf")

with col2:
    st.subheader("📊 Upload Excel File")
    excel_file = st.file_uploader("Choose Excel file", type=['xlsx', 'xls'], key="excel")

# Process button
if st.button("🔍 Start Reconciliation", type="primary", disabled=not (pdf_file and excel_file)):
    with st.spinner("Processing files..."):
        excel_df, excel_error = load_and_clean_excel(excel_file)
        if excel_error:
            st.error(f"Error processing Excel: {excel_error}")
            st.stop()
        
        pdf_bytes = pdf_file.read()
        pdf_df, pdf_totals, pdf_error = extract_pdf_data(pdf_bytes, AZURE_ENDPOINT, AZURE_API_KEY)
        if pdf_error:
            st.error(f"Error processing PDF: {pdf_error}")
            st.stop()
        
        comparison_df, accuracy = reconcile_data(pdf_df, excel_df, pdf_totals, tolerance)
        
        st.success("✅ Reconciliation completed!")
        
        # Save to MongoDB
        try:
            save_reconciliation_report(
                collection_name="wonderchef_reconciliation",
                invoice_no=f"WONDERCHEF_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                summary_data={
                    "accuracy": float(accuracy),
                    "total_items": len(comparison_df),
                    "pdf_grand_total": float(pdf_totals['Grand_Total']),
                    "excel_grand_total": float(excel_df['Total_EXCEL'].sum())
                },
                line_items_data=comparison_df,
                metadata={"report_type": "wonderchef_reconciliation"}
            )
        except Exception:
            pass
        
        st.metric("Overall Accuracy", f"{accuracy:.2f}%", 
                 delta=f"{accuracy - 100:.2f}%" if accuracy < 100 else "Perfect Match!")
        
        st.subheader("📈 Summary Statistics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Items", len(comparison_df))
            st.metric("Matched Items", 
                     len(comparison_df[(comparison_df['Qty_Match']) & 
                                      (comparison_df['Tax_Status']) & 
                                      (comparison_df['Total_Match'])]))
        
        with col2:
            st.metric("PDF Total Qty", f"{pdf_df['Qty_PDF'].sum():.0f}")
            st.metric("Excel Total Qty", f"{excel_df['Qty_EXCEL'].sum():.0f}")
        
        with col3:
            st.metric("PDF Total Tax", f"₹{pdf_df['Tax_PDF'].sum():,.2f}")
            st.metric("Excel Total Tax", f"₹{excel_df['Tax_EXCEL'].sum():,.2f}")
        
        # Add another row for Grand Totals
        st.write("")  # Add some spacing
        col4, col5, col6 = st.columns(3)
        
        with col4:
            pdf_grand = pdf_totals['Grand_Total']
            excel_grand = excel_df['Total_EXCEL'].sum()
            variance = pdf_grand - excel_grand
            st.metric("PDF Grand Total", f"₹{pdf_grand:,.2f}")
        
        with col5:
            st.metric("Excel Grand Total", f"₹{excel_grand:,.2f}")
        
        with col6:
            st.metric("Grand Total Variance", f"₹{variance:,.2f}",
                     delta=f"₹{variance:,.2f}" if variance != 0 else "Perfect Match!")
        
        st.subheader("🔍 Detailed Item Comparison")
        
        display_df = comparison_df.copy()
        display_df['Status'] = display_df.apply(
            lambda row: '✅ Match' if (row['Qty_Match'] and row['Tax_Status'] and row['Total_Match']) 
            else '❌ Mismatch', axis=1
        )
        
        display_columns = {
            'Material Code': 'Material Code',
            'Description_PDF': 'Description',
            'Qty_PDF': 'Qty (PDF)',
            'Qty_EXCEL': 'Qty (Excel)',
            'Tax_PDF': 'Tax (PDF)',
            'Tax_EXCEL': 'Tax (Excel)',
            'Total_PDF': 'Total (PDF)',
            'Total_EXCEL': 'Total (Excel)',
            'Amount_Diff': 'Difference',
            'Status': 'Status'
        }
        
        display_table = display_df[list(display_columns.keys())].rename(columns=display_columns)
        
        def highlight_mismatch(row):
            if '❌' in row['Status']:
                return ['background-color: #ffebee'] * len(row)
            else:
                return ['background-color: #e8f5e9'] * len(row)
        
        styled_df = display_table.style.apply(highlight_mismatch, axis=1).format({
            'Qty (PDF)': '{:.0f}',
            'Qty (Excel)': '{:.0f}',
            'Tax (PDF)': '₹{:,.2f}',
            'Tax (Excel)': '₹{:,.2f}',
            'Total (PDF)': '₹{:,.2f}',
            'Total (Excel)': '₹{:,.2f}',
            'Difference': '₹{:,.2f}'
        })
        
        st.dataframe(styled_df, use_container_width=True, height=400)
        
        st.subheader("💾 Download Report")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            display_table.to_excel(writer, sheet_name='Reconciliation', index=False)
            
            summary_data = pd.DataFrame({
                'Metric': [
                    'Total Items', 
                    'Matched Items', 
                    'Accuracy',
                    'PDF Total Quantity',
                    'Excel Total Quantity',
                    'Quantity Variance',
                    'PDF Total Tax',
                    'Excel Total Tax',
                    'Tax Variance',
                    'PDF Grand Total', 
                    'Excel Grand Total', 
                    'Grand Total Variance'
                ],
                'Value': [
                    len(comparison_df),
                    len(comparison_df[(comparison_df['Qty_Match']) & (comparison_df['Tax_Status']) & (comparison_df['Total_Match'])]),
                    f"{accuracy:.2f}%",
                    f"{pdf_df['Qty_PDF'].sum():.0f}",
                    f"{excel_df['Qty_EXCEL'].sum():.0f}",
                    f"{pdf_df['Qty_PDF'].sum() - excel_df['Qty_EXCEL'].sum():.0f}",
                    f"₹{pdf_df['Tax_PDF'].sum():,.2f}",
                    f"₹{excel_df['Tax_EXCEL'].sum():,.2f}",
                    f"₹{pdf_df['Tax_PDF'].sum() - excel_df['Tax_EXCEL'].sum():,.2f}",
                    f"₹{pdf_totals['Grand_Total']:,.2f}",
                    f"₹{excel_df['Total_EXCEL'].sum():,.2f}",
                    f"₹{pdf_totals['Grand_Total'] - excel_df['Total_EXCEL'].sum():,.2f}"
                ]
            })
            summary_data.to_excel(writer, sheet_name='Summary', index=False)
        
        st.download_button(
            label="📥 Download Excel Report",
            data=output.getvalue(),
            file_name="reconciliation_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

st.markdown("---")
st.markdown("Built with Streamlit | Powered by Azure Document Intelligence")