import streamlit as st
import pandas as pd
import re
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
import io
from dotenv import load_dotenv
from dotenv import load_dotenv
import os
from mongo_utils import save_reconciliation_report
from ui_utils import apply_professional_style, get_download_filename, render_header

# Load environment variables
load_dotenv()

# Apply Professional UI
apply_professional_style()

def main():
    st.set_page_config(page_title="Crompton Reconciliation", layout="wide", page_icon="🔍")
    render_header("Crompton Reconciliation Tool", "Fuzzy matching enabled for description comparison")

# Load Azure credentials from environment variables
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY")

st.set_page_config(page_title="Crompton Invoice Reconciliation Tool", layout="wide")

st.title("Crompton Invoice Reconciliation Tool")
st.markdown("Compare PDF invoices with Excel PO data for accurate reconciliation")

# Load Azure credentials from environment variables
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY")

# Sidebar for settings only
with st.sidebar:
    st.header("⚙️ Configuration")
    st.subheader("Reconciliation Settings")
    tolerance = st.slider(
        "Amount Tolerance (₹)", 
        min_value=10, 
        max_value=20, 
        value=15,
        help="Acceptable difference in amounts for matching"
    )

# Helper Functions
def clean_num(field):
    """Extract numeric value from Azure field"""
    if not field: return 0.0
    if hasattr(field, 'value_number') and field.value_number is not None:
        return float(field.value_number)
    if hasattr(field, 'value_currency') and field.value_currency:
        return float(field.value_currency.amount)
    content = getattr(field, 'content', '0')
    cleaned = re.sub(r'[^0-9.]', '', str(content))
    try: return float(cleaned)
    except: return 0.0

def load_and_clean_excel(file_bytes):
    """Load and clean Excel file"""
    raw_df = pd.read_excel(io.BytesIO(file_bytes), header=None)
    header_row_idx = raw_df[raw_df.apply(lambda r: r.astype(str).str.contains('SKU').any(), axis=1)].index[0]
    
    df = pd.read_excel(io.BytesIO(file_bytes), header=header_row_idx)
    df.columns = df.columns.astype(str).str.strip()

    cleaned_items = pd.DataFrame()
    
    # Material Code extraction with better handling
    material_codes = df.iloc[:, 0].astype(str).str.replace('CR-', '', regex=False).str.replace('WO-', '', regex=False).str.strip()
    # Ensure proper case - material codes are typically uppercase
    cleaned_items['Material Code'] = material_codes.str.upper()
    
    cleaned_items['Description'] = df.iloc[:, 1].astype(str).str.strip()
    
    if 'PO Ref No.' in df.columns:
        cleaned_items['PO Ref No.'] = df['PO Ref No.'].astype(str).str.strip()
    else:
        cleaned_items['PO Ref No.'] = df.iloc[:, 3].astype(str).str.strip()
    
    def clean_currency(value):
        if pd.isna(value): return 0.0
        cleaned = re.sub(r'[^0-9.]', '', str(value))
        try: return float(cleaned)
        except ValueError: return 0.0

    cleaned_items['Qty_EXCEL'] = df.iloc[:, 4].apply(clean_currency)
    cleaned_items['Tax_EXCEL'] = df.iloc[:, 10].apply(clean_currency)
    cleaned_items['Total_EXCEL'] = df.iloc[:, 11].apply(clean_currency)
    
    cleaned_items = cleaned_items[cleaned_items['Material Code'] != 'NAN'].reset_index(drop=True)
    return cleaned_items

def extract_pdf_data(pdf_bytes, endpoint, key):
    """Extract data from PDF invoice with enhanced parsing and fallback methods"""
    client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))
    
    # First attempt: Use prebuilt-invoice model
    poller = client.begin_analyze_document(
        "prebuilt-invoice", AnalyzeDocumentRequest(bytes_source=pdf_bytes)
    )
    result = poller.result()
    
    all_line_items = []
    invoice_summary = {"Invoice_No": "N/A", "Sub_Total": 0.0, "Grand_Total": 0.0, "Calculated_Tax": 0.0}

    for invoice in result.documents:
        fields = invoice.fields
        
        # Extract invoice header information
        invoice_summary['Invoice_No'] = fields.get("InvoiceId").content if fields.get("InvoiceId") else "N/A"
        sub_total = clean_num(fields.get("SubTotal"))
        grand_total = clean_num(fields.get("InvoiceTotal"))
        total_tax_field = clean_num(fields.get("TotalTax"))

        calc_tax = total_tax_field if total_tax_field > 0 else (grand_total - sub_total)
        
        invoice_summary.update({
            "Sub_Total": sub_total,
            "Grand_Total": grand_total,
            "Calculated_Tax": round(calc_tax, 2)
        })

        # Extract line items with enhanced logic
        items_field = fields.get("Items")
        if items_field and items_field.value_array:
            for item in items_field.value_array:
                val = item.value_object
                
                # Get description
                desc = val.get("Description").content if val.get("Description") else "N/A"
                
                # Get product code (try multiple fields)
                product_code = ""
                if val.get("ProductCode"):
                    product_code = val.get("ProductCode").content
                
                # Extract material code from description if present
                # Look for patterns like "Cat Ref : CFHSGIN48TAP1S" or "Code: XXX"
                material_code_match = re.search(r'(?:Cat Ref|Code|Ref|SKU|Item)\s*:?\s*([A-Z0-9]+)', desc, re.IGNORECASE)
                if material_code_match:
                    product_code = material_code_match.group(1)
                
                # Get quantity
                qty = clean_num(val.get("Quantity"))
                
                # Try to extract quantity from description if not found
                if qty == 0.0 and desc != "N/A":
                    qty_match = re.search(r'^(\d+)\s*(?:NOS|PCS|UNITS?)?', desc.strip(), re.IGNORECASE)
                    if qty_match:
                        qty = float(qty_match.group(1))
                
                # Get amount
                amount = clean_num(val.get("Amount"))
                
                # Get unit price if available
                unit_price = clean_num(val.get("UnitPrice"))
                
                # Skip invalid or summary rows
                if "hsn" in desc.lower() or "summary" in desc.lower() or "total" in desc.lower().strip():
                    continue
                
                # Skip if no description or amount
                if desc == "N/A" or (amount == 0.0 and qty == 0.0):
                    continue

                all_line_items.append({
                    "Description": desc,
                    "Material_Code": product_code.strip() if product_code else "",
                    "Quantity_PDF": qty if qty > 0 else 1.0,
                    "Amount_Base": amount,
                    "Unit_Price": unit_price
                })

    # Fallback: If no line items found, try layout-based extraction
    if len(all_line_items) == 0:
        st.warning("⚠️ Prebuilt invoice model found no items. Attempting layout-based extraction...")
        
        # Use layout model as fallback
        poller_layout = client.begin_analyze_document(
            "prebuilt-layout", AnalyzeDocumentRequest(bytes_source=pdf_bytes)
        )
        layout_result = poller_layout.result()
        
        # Extract all text and look for material codes and amounts
        full_text = ""
        if layout_result.pages:
            for page in layout_result.pages:
                if page.lines:
                    for line in page.lines:
                        full_text += line.content + "\n"
        
        # Parse line items from raw text
        lines = full_text.split('\n')
        for i, line in enumerate(lines):
            # Look for material code patterns (alphanumeric codes)
            code_match = re.search(r'\b([A-Z]{2}[A-Z0-9]{8,})\b', line)
            if code_match:
                material_code = code_match.group(1)
                
                # Look for quantity pattern (number followed by NOS/PCS/UNITS)
                qty_match = re.search(r'(\d+)\s*(?:NOS|PCS|UNITS?)', line, re.IGNORECASE)
                qty = float(qty_match.group(1)) if qty_match else 1.0
                
                # Look for amount (currency pattern)
                amount_match = re.search(r'₹?\s*([\d,]+\.?\d*)', line)
                amount = 0.0
                if amount_match:
                    amount_str = amount_match.group(1).replace(',', '')
                    try:
                        amount = float(amount_str)
                    except:
                        pass
                
                # Get description (text before or after code)
                desc = line.strip()
                
                all_line_items.append({
                    "Description": desc,
                    "Material_Code": material_code,
                    "Quantity_PDF": qty,
                    "Amount_Base": amount,
                    "Unit_Price": 0.0
                })

    df_items = pd.DataFrame(all_line_items).drop_duplicates().reset_index(drop=True)
    
    # Clean description for better matching
    if not df_items.empty:
        df_items['Clean_Desc'] = df_items['Description'].str.lower().str.strip()
    
    return df_items, invoice_summary

def normalize_code_for_matching(code):
    """Normalize material codes for fuzzy matching by handling confusing characters"""
    if not code:
        return ""
    code = str(code).upper().strip()
    # Create variations for ambiguous characters
    # I/1, O/0, S/5 are commonly confused
    return code

def codes_are_similar(code1, code2, tolerance=1):
    """Check if two codes are similar allowing for character confusion"""
    if code1 == code2:
        return True
    
    # Normalize both codes
    c1 = str(code1).upper().strip()
    c2 = str(code2).upper().strip()
    
    if c1 == c2:
        return True
    
    # Check with I<->1 substitution
    c1_sub = c1.replace('I', '1').replace('1', 'I')
    if c1_sub == c2 or c1 == c2.replace('I', '1').replace('1', 'I'):
        return True
    
    # Check with O<->0 substitution
    c1_sub = c1.replace('O', '0').replace('0', 'O')
    if c1_sub == c2 or c1 == c2.replace('O', '0').replace('0', 'O'):
        return True
    
    # Check Levenshtein distance (allow 1 character difference)
    if len(c1) == len(c2):
        differences = sum(1 for a, b in zip(c1, c2) if a != b)
        return differences <= tolerance
    
    return False

def perform_reconciliation(pdf_items, pdf_summary, excel_df, tolerance_val):
    """Perform reconciliation between PDF and Excel data with improved matching"""
    comparison_rows = []
    total_checks = 0
    passed_checks = 0
    
    # Prepare PDF items for matching
    if 'Clean_Desc' not in pdf_items.columns and not pdf_items.empty:
        pdf_items['Clean_Desc'] = pdf_items['Description'].str.lower().str.strip()
    
    # Create a normalized Material_Code column in PDF items if it doesn't exist
    if not pdf_items.empty and 'Material_Code' in pdf_items.columns:
        pdf_items['Material_Code_Upper'] = pdf_items['Material_Code'].str.strip().str.upper()

    for _, ex_row in excel_df.iterrows():
        m_code = str(ex_row['Material Code']).strip().upper()
        ex_qty = float(ex_row['Qty_EXCEL'])
        ex_total = float(ex_row['Total_EXCEL'])
        ex_tax = float(ex_row['Tax_EXCEL']) if 'Tax_EXCEL' in ex_row else 0
        ex_base = ex_total - ex_tax  # Calculate base amount (without tax)
        
        # Try multiple matching strategies
        matched_pdf = pd.DataFrame()
        
        if not pdf_items.empty:
            # Strategy 1: Direct match by Material Code field (case-insensitive)
            if 'Material_Code_Upper' in pdf_items.columns:
                matched_pdf = pdf_items[pdf_items['Material_Code_Upper'] == m_code]
            
            # Strategy 2: Fuzzy match with similar codes (handles I/1, O/0 confusion)
            if matched_pdf.empty and 'Material_Code_Upper' in pdf_items.columns:
                for idx, row in pdf_items.iterrows():
                    if codes_are_similar(row['Material_Code_Upper'], m_code):
                        matched_pdf = pdf_items.iloc[[idx]]
                        break
            
            # Strategy 3: Match by Material Code in description
            if matched_pdf.empty and 'Clean_Desc' in pdf_items.columns:
                matched_pdf = pdf_items[pdf_items['Clean_Desc'].str.contains(m_code.lower(), regex=False, na=False)]
            
            # Strategy 4: Fuzzy match by removing special characters
            if matched_pdf.empty and 'Clean_Desc' in pdf_items.columns:
                clean_code = re.sub(r'[^A-Z0-9]', '', m_code)
                matched_pdf = pdf_items[pdf_items['Clean_Desc'].str.replace(r'[^a-z0-9]', '', regex=True).str.contains(clean_code.lower(), regex=False, na=False)]
        
        total_checks += 1
        
        if not matched_pdf.empty:
            passed_checks += 1
            pdf_row = matched_pdf.iloc[0]
            qty_pdf = float(pdf_row['Quantity_PDF'])
            amt_pdf = float(pdf_row['Amount_Base'])
            
            # Quantity check
            total_checks += 1
            qty_match = (ex_qty == qty_pdf)
            if qty_match: passed_checks += 1
            
            # Amount check - compare base amounts (without tax) with tolerance
            total_checks += 1
            # Try matching with both total and base amount
            amt_match_total = abs(ex_total - amt_pdf) < tolerance_val
            amt_match_base = abs(ex_base - amt_pdf) < tolerance_val
            amt_match = amt_match_total or amt_match_base
            if amt_match: passed_checks += 1
            
            comparison_rows.append({
                "Material_Code": m_code,
                "Description_PDF": pdf_row['Description'][:50],
                "Qty_Excel": ex_qty,
                "Qty_PDF": qty_pdf,
                "Qty_Status": "✅" if qty_match else "❌",
                "Total_Excel": ex_total,
                "Amount_PDF": amt_pdf,
                "Amount_Status": "✅" if amt_match else "❌",
                "Match": "✅"
            })
        else:
            comparison_rows.append({
                "Material_Code": m_code, 
                "Description_PDF": "NOT FOUND",
                "Qty_Excel": ex_qty, 
                "Qty_PDF": 0, 
                "Qty_Status": "❌",
                "Total_Excel": ex_total, 
                "Amount_PDF": 0, 
                "Amount_Status": "❌",
                "Match": "❌"
            })

    # Summary calculations
    excel_tax_sum = excel_df['Tax_EXCEL'].sum()
    excel_grand_total = excel_df['Total_EXCEL'].sum()
    
    total_checks += 3
    
    po_match = (str(excel_df['PO Ref No.'].iloc[0]).strip() in pdf_summary['Invoice_No'])
    tax_match = abs(excel_tax_sum - pdf_summary['Calculated_Tax']) < tolerance_val
    grand_total_match = abs(excel_grand_total - pdf_summary['Grand_Total']) < tolerance_val
    
    if po_match: passed_checks += 1
    if tax_match: passed_checks += 1
    if grand_total_match: passed_checks += 1

    report_df = pd.DataFrame(comparison_rows)
    
    summary_results = [
        {"Metric": "PO Ref vs Invoice", "Excel": excel_df['PO Ref No.'].iloc[0], "PDF": pdf_summary['Invoice_No'], "Status": "✅" if po_match else "❌"},
        {"Metric": "Total Tax Comparison", "Excel": round(excel_tax_sum, 2), "PDF": pdf_summary['Calculated_Tax'], "Status": "✅" if tax_match else "❌"},
        {"Metric": "Grand Total Comparison", "Excel": round(excel_grand_total, 2), "PDF": pdf_summary['Grand_Total'], "Status": "✅" if grand_total_match else "❌"}
    ]
    
    overall_accuracy = (passed_checks / total_checks) * 100 if total_checks > 0 else 0
    
    return report_df, summary_results, round(overall_accuracy, 2)

# Main App
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Upload PDF Invoice")
    pdf_file = st.file_uploader("Choose PDF file", type=['pdf'])

with col2:
    st.subheader("📊 Upload Excel PO")
    excel_file = st.file_uploader("Choose Excel file", type=['xlsx', 'xls'])

# Check if credentials are available
credentials_available = AZURE_ENDPOINT and AZURE_KEY

if st.button("🔍 Run Reconciliation", type="primary", disabled=not (pdf_file and excel_file and credentials_available)):
    if not credentials_available:
        st.error("⚠️ Azure credentials not found. Please check your .env file")
    else:
        with st.spinner("Processing files..."):
            try:
                # Load Excel data
                excel_bytes = excel_file.read()
                excel_df = load_and_clean_excel(excel_bytes)
                
                # Extract PDF data
                pdf_bytes = pdf_file.read()
                pdf_items, pdf_summary = extract_pdf_data(pdf_bytes, AZURE_ENDPOINT, AZURE_KEY)
                
                # Perform reconciliation
                report_df, summary_results, accuracy = perform_reconciliation(
                    pdf_items, pdf_summary, excel_df, tolerance
                )
                
                # Display results
                st.success(f"✅ Reconciliation Complete!")
                
                # Debug information (expandable)
                with st.expander("🔍 Debug: PDF Extracted Data"):
                    st.write("**Extracted Line Items from PDF:**")
                    if pdf_items.empty:
                        st.error("No line items extracted from PDF!")
                    else:
                        st.dataframe(pdf_items, use_container_width=True)
                    
                    st.write("**Excel Data:**")
                    st.dataframe(excel_df[['Material Code', 'Description', 'Qty_EXCEL', 'Total_EXCEL']], use_container_width=True)
                    
                    # Show matching diagnostics
                    st.write("**Matching Diagnostics:**")
                    for _, ex_row in excel_df.iterrows():
                        m_code = str(ex_row['Material Code']).strip().upper()
                        st.write(f"- Looking for: `{m_code}`")
                        
                        if not pdf_items.empty:
                            # Try all matching strategies
                            found = False
                            
                            # Strategy 1: Direct material code match
                            if 'Material_Code' in pdf_items.columns:
                                matches = pdf_items[pdf_items['Material_Code'].str.strip().str.upper() == m_code]
                                if not matches.empty:
                                    st.success(f"  ✅ Strategy 1 (Exact Match): Found in PDF")
                                    st.write(f"     Description: {matches.iloc[0]['Description'][:60]}")
                                    st.write(f"     Quantity: {matches.iloc[0]['Quantity_PDF']}, Amount: {matches.iloc[0]['Amount_Base']}")
                                    found = True
                            
                            # Strategy 2: Fuzzy match (I/1, O/0)
                            if not found and 'Material_Code' in pdf_items.columns:
                                for idx, row in pdf_items.iterrows():
                                    pdf_code = str(row['Material_Code']).strip().upper()
                                    if codes_are_similar(pdf_code, m_code):
                                        st.success(f"  ✅ Strategy 2 (Fuzzy Match): Found similar code")
                                        st.write(f"     Excel Code: `{m_code}` → PDF Code: `{pdf_code}`")
                                        st.write(f"     Description: {row['Description'][:60]}")
                                        st.write(f"     Quantity: {row['Quantity_PDF']}, Amount: {row['Amount_Base']}")
                                        found = True
                                        break
                            
                            # Strategy 3: Code in description
                            if not found and 'Clean_Desc' in pdf_items.columns:
                                matches = pdf_items[pdf_items['Clean_Desc'].str.contains(m_code.lower(), regex=False, na=False)]
                                if not matches.empty:
                                    st.success(f"  ✅ Strategy 3 (Code in Desc): Found in PDF")
                                    st.write(f"     Description: {matches.iloc[0]['Description'][:60]}")
                                    found = True
                            
                            if not found:
                                st.error(f"  ❌ Not found with any strategy")
                                st.write(f"  **Available Material Codes in PDF:**")
                                if 'Material_Code' in pdf_items.columns:
                                    codes = pdf_items['Material_Code'].tolist()
                                    st.write(f"  {codes}")
                                    # Show similarity check
                                    st.write(f"  **Similarity Check:**")
                                    for pdf_code in codes:
                                        if codes_are_similar(str(pdf_code).upper(), m_code):
                                            st.warning(f"    `{pdf_code}` is similar to `{m_code}`")
                                st.write(f"  **Sample Descriptions from PDF:**")
                                st.write(pdf_items['Description'].head(3).tolist())
                        else:
                            st.error("  ❌ PDF items list is empty!")
                
                # Accuracy metric
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Overall Accuracy", f"{accuracy}%")
                with col2:
                    st.metric("Invoice Number", pdf_summary['Invoice_No'])
                with col3:
                    st.metric("Grand Total", f"₹{pdf_summary['Grand_Total']:,.2f}")
                
                # Summary comparison
                st.subheader("📋 Summary Totals")
                summary_df = pd.DataFrame(summary_results)
                st.dataframe(summary_df, use_container_width=True, hide_index=True)
                
                # Item-wise validation
                st.subheader("🔎 Item-wise Validation")
                st.dataframe(report_df, use_container_width=True, hide_index=True)
                
                # Download buttons with comprehensive reports
                st.divider()
                col_dl1, col_dl2 = st.columns(2)
                
                with col_dl1:
                    # Create comprehensive CSV report with summary
                    csv_buffer = io.StringIO()
                    
                    # Header information
                    csv_buffer.write("INVOICE RECONCILIATION REPORT\n")
                    csv_buffer.write(f"Generated on: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    csv_buffer.write(f"Overall Accuracy: {accuracy}%\n")
                    csv_buffer.write("\n")
                    
                    # Invoice Summary
                    csv_buffer.write("INVOICE SUMMARY\n")
                    csv_buffer.write(f"Invoice Number,{pdf_summary['Invoice_No']}\n")
                    csv_buffer.write(f"Sub Total,{pdf_summary['Sub_Total']:.2f}\n")
                    csv_buffer.write(f"Tax Amount,{pdf_summary['Calculated_Tax']:.2f}\n")
                    csv_buffer.write(f"Grand Total,{pdf_summary['Grand_Total']:.2f}\n")
                    csv_buffer.write("\n")
                    
                    # Summary Totals Comparison
                    csv_buffer.write("SUMMARY TOTALS COMPARISON\n")
                    summary_df = pd.DataFrame(summary_results)
                    csv_buffer.write(summary_df.to_csv(index=False))
                    csv_buffer.write("\n")
                    
                    # Item-wise Validation
                    csv_buffer.write("ITEM-WISE VALIDATION\n")
                    csv_buffer.write(report_df.to_csv(index=False))
                    
                    csv_content = csv_buffer.getvalue()
                    
                    st.download_button(
                        label="📥 Download Complete Report (CSV)",
                        data=csv_content,
                        file_name=get_download_filename(f"reconciliation_report_{pdf_summary['Invoice_No']}", "csv"),
                        mime="text/csv",
                        use_container_width=True
                    )
                
                with col_dl2:
                    # Create Excel report with multiple sheets
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        # Summary sheet
                        summary_info = pd.DataFrame({
                            'Metric': ['Invoice Number', 'Overall Accuracy', 'Sub Total (PDF)', 
                                      'Tax Amount (PDF)', 'Grand Total (PDF)'],
                            'Value': [pdf_summary['Invoice_No'], f"{accuracy}%", 
                                     f"₹{pdf_summary['Sub_Total']:.2f}",
                                     f"₹{pdf_summary['Calculated_Tax']:.2f}",
                                     f"₹{pdf_summary['Grand_Total']:.2f}"]
                        })
                        summary_info.to_excel(writer, sheet_name='Summary', index=False)
                        
                        # Comparison sheet
                        summary_df = pd.DataFrame(summary_results)
                        summary_df.to_excel(writer, sheet_name='Totals Comparison', index=False)
                        
                        # Item-wise validation sheet
                        report_df.to_excel(writer, sheet_name='Item Validation', index=False)
                        
                        # PDF Data sheet
                        if not pdf_items.empty:
                            pdf_items_export = pdf_items[['Material_Code', 'Description', 'Quantity_PDF', 'Amount_Base']].copy()
                            pdf_items_export.to_excel(writer, sheet_name='PDF Extracted Data', index=False)
                        
                        # Excel Data sheet
                        excel_export = excel_df[['Material Code', 'Description', 'Qty_EXCEL', 'Tax_EXCEL', 'Total_EXCEL']].copy()
                        excel_export.to_excel(writer, sheet_name='Excel PO Data', index=False)
                    
                    excel_content = excel_buffer.getvalue()
                    
                    st.download_button(
                    label="📥 Download Excel Report",
                    data=excel_content,
                    file_name=get_download_filename(f"Crompton_Reconciliation_{pdf_summary['Invoice_No']}"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
                # Save to MongoDB
                try:
                     save_reconciliation_report(
                        collection_name="crompton_reconciliation",
                        invoice_no=pdf_summary['Invoice_No'],
                        summary_data=pd.DataFrame(summary_results),
                        line_items_data=report_df,
                        metadata={
                            "accuracy": accuracy,
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

# Instructions
with st.expander("ℹ️ How to use this tool"):
    st.markdown("""
    1. **Setup** (One-time):
        - Create a `.env` file in the same directory as this app
        - Add your Azure credentials:
        ```
        AZURE_ENDPOINT=your_endpoint_url_here
        AZURE_KEY=your_api_key_here
        ```
    2. **Set Tolerance**: Adjust the amount tolerance (₹10-20) for matching validation
    3. **Upload Files**: 
        - Upload your PDF invoice
        - Upload your Excel PO file
    4. **Run Reconciliation**: Click the button to process and compare
    5. **Review Results**: Check item-wise validation and summary totals
    6. **Download Report**: Export the reconciliation report as CSV
    """)

# Footer
st.markdown("---")

st.caption("🔒 Your Azure credentials are securely loaded from .env file and never displayed to users")