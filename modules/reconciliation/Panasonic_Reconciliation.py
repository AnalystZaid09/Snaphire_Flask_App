# streamlit_pdf_excel_reconcile.py
# Streamlit app (Azure-only). Loads AZURE_ENDPOINT and AZURE_KEY from environment or .env (python-dotenv).
# Uses Azure Document Analysis to extract invoices, extracts model-prefix (e.g. SR-WA18H) from PDF descriptions,
# compares to Excel SKUs (strips PA-), compares Qty/Tax/Total and provides in-memory Excel download.

import streamlit as st
import pandas as pd
import re
import io
import os
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style,
    get_download_filename,
    render_header,
    download_module_report
)

MODULE_NAME = "reconciliation"
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Optional .env loader (keeps secrets outside app)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Azure SDK (required)
try:
    from azure.ai.documentanalysis import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    AZURE_AVAILABLE = True
except Exception:
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
        AZURE_AVAILABLE = True
    except Exception:
        AZURE_AVAILABLE = False

# -------------------- utilities --------------------

def _parse_amount(text) -> Decimal | None:
    if text is None:
        return None
    s = str(text).replace("\u00A0", " ").strip()
    s = re.sub(r"[^\d\.\-\(\),%]", "", s)
    is_negative = "(" in s and ")" in s
    s = s.replace("(", "").replace(")", "").replace(",", "").replace("%", "").strip()
    if s == "":
        return None
    try:
        d = Decimal(s)
        if is_negative:
            d = -d
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None

def _to_float(d):
    return float(d) if d is not None else 0.0

def parse_decimal_token(s):
    if not s:
        return None
    s = str(s).replace(",", "").strip()
    try:
        return float(Decimal(s))
    except Exception:
        try:
            return float(s)
        except Exception:
            return None

# -------------------- Excel reader --------------------

def read_excel_row1_as_header_bytes(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)
    except Exception:
        df = pd.read_csv(io.StringIO(file_bytes.decode('utf-8')), dtype=str)
    # take first row as header
    new_header = df.iloc[0]
    df = df[1:]
    df.columns = new_header
    # basic cleaning for numeric-ish cells
    def to_float_safe(val):
        if pd.isna(val):
            return val
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        # keep strings with letters
        if re.search(r"[A-Za-z]", s):
            return s
        s = re.sub(r"[^\d\.\-,\(\)]", "", s)
        is_neg = "(" in s and ")" in s
        s = s.replace("(", "").replace(")", "").replace(",", "").strip()
        if s in ("", "-", ".", None):
            return val
        try:
            num = float(Decimal(s))
        except Exception:
            try:
                num = float(s)
            except Exception:
                return val
        return -num if is_neg else num
    df = df.applymap(lambda x: to_float_safe(x))
    return df

# -------------------- PDF text parsing helpers --------------------

def extract_gst_amounts(full_text):
    lines = [ln.strip() for ln in (full_text or "").splitlines()]
    def find_amount_after_label(label):
        for i, ln in enumerate(lines):
            if re.search(rf"\b{label}\b", ln, re.I):
                decimals_same = re.findall(r"[0-9,]+\.\d{2}", ln)
                decimals_same = [d for d in decimals_same if parse_decimal_token(d) is not None and parse_decimal_token(d) > 100]
                if decimals_same:
                    return parse_decimal_token(decimals_same[0])
                for j in range(1, 4):
                    if i + j < len(lines):
                        nxt = lines[i + j]
                        decimals = re.findall(r"[0-9,]+\.\d{2}", nxt)
                        decimals = [d for d in decimals if parse_decimal_token(d) is not None and parse_decimal_token(d) > 100]
                        if decimals:
                            return parse_decimal_token(decimals[0])
        return 0.0
    cgst = find_amount_after_label("CGST")
    sgst = find_amount_after_label("SGST")
    igst = find_amount_after_label("IGST")
    # percent fallback
    if cgst == 0.0:
        m = re.search(r"CGST[^\n%]{0,60}\d{1,2}(?:\.\d+)?\s*%[^\d\n]{0,20}([0-9,]+\.\d{2})", full_text, re.I)
        if m: cgst = parse_decimal_token(m.group(1))
    if sgst == 0.0:
        m = re.search(r"SGST[^\n%]{0,60}\d{1,2}(?:\.\d+)?\s*%[^\d\n]{0,20}([0-9,]+\.\d{2})", full_text, re.I)
        if m: sgst = parse_decimal_token(m.group(1))
    if igst == 0.0:
        m = re.search(r"IGST[^\n%]{0,60}\d{1,2}(?:\.\d+)?\s*%[^\d\n]{0,20}([0-9,]+\.\d{2})", full_text, re.I)
        if m: igst = parse_decimal_token(m.group(1))
    return cgst or 0.0, sgst or 0.0, igst or 0.0

def is_product_candidate(line):
    if not line:
        return False
    s = line.strip()
    if len(s) < 3 or len(s) > 300:
        return False
    low = s.lower()
    reject = ["gstin","invoice","date","total","tax","grand","rupees","eway","lr","irn"]
    if any(r in low for r in reject):
        return False
    if re.search(r"\b[A-Z]{1,4}-[A-Z0-9\(\)\-/]{2,20}\b", s):
        return True
    if len(re.findall(r"[A-Za-z]{2,}", s)) >= 3:
        return True
    return False

def extract_items_from_text(full_text):
    lines = [ln.rstrip() for ln in (full_text or "").splitlines()]
    items = []
    hsn_re = re.compile(r"\b([0-9]{6,8})\b")
    hsn_positions = []
    for i, ln in enumerate(lines):
        for m in hsn_re.finditer(ln):
            hsn_positions.append((i, m.group(1), ln))
    seen = set()
    for idx, hsn, hsn_line in hsn_positions:
        desc_candidates = []
        for back in range(1, 9):
            i_prev = idx - back
            if i_prev < 0: break
            cand = lines[i_prev].strip()
            if is_product_candidate(cand):
                if not re.fullmatch(r"^\d+$", cand):
                    desc_candidates.insert(0, cand)
        if not desc_candidates:
            left = hsn_line.split(hsn)[0].strip()
            if is_product_candidate(left):
                desc_candidates = [left]
        if not desc_candidates:
            for back in range(9, 16):
                i_prev = idx - back
                if i_prev < 0: break
                cand = lines[i_prev].strip()
                if is_product_candidate(cand):
                    desc_candidates = [cand]; break
        description = " ".join(desc_candidates).strip() if desc_candidates else None
        if not description:
            continue
        window_lines = lines[idx: idx+9]
        window = " ".join(window_lines)
        tokens = re.split(r"\s+", window)
        try:
            hpos = tokens.index(hsn)
        except ValueError:
            hpos = 0
        qty = None
        for t in tokens[hpos+1: hpos+12]:
            if re.fullmatch(r"\d{1,6}", t):
                val = int(t)
                if 1 <= val <= 100000:
                    qty = val; break
        rate = None
        for t in tokens[hpos+1: hpos+20]:
            if re.fullmatch(r"[0-9,]+\.\d{2}", t):
                v = parse_decimal_token(t)
                if v is not None and v > 0:
                    rate = v; break
        decimals = re.findall(r"[0-9,]+\.\d{2}", window)
        dec_vals = [parse_decimal_token(d) for d in decimals if parse_decimal_token(d) is not None]
        amount = None
        if dec_vals:
            if qty and rate:
                target = qty * rate
                nearest = min(dec_vals, key=lambda x: abs(x - target))
                amount = nearest
            else:
                amount = max(dec_vals)
        if not ((qty and rate) or amount):
            continue
        key = (hsn, qty, amount)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "Description": description,
            "HSN": hsn,
            "Qty": qty,
            "Rate": rate,
            "Amount": amount,
            "Qty_x_Rate": float(qty * rate) if (qty and rate) else None
        })
    return items

# -------------------- Azure parsing --------------------

def parse_pdf_with_azure(file_bytes, endpoint, key):
    client = DocumentAnalysisClient(endpoint, AzureKeyCredential(key))
    try:
        poller = client.begin_analyze_document("prebuilt-invoice", file_bytes)
    except TypeError:
        poller = client.begin_analyze_document("prebuilt-invoice", body=file_bytes)
    result = poller.result()
    full_text = getattr(result, "content", "") or ""
    if not full_text and getattr(result, "pages", None):
        parts = []
        for p in result.pages:
            for line in getattr(p, "lines", []) or []:
                parts.append(getattr(line, "content", "") or "")
        full_text = "\n".join(parts)
    cgst, sgst, igst = extract_gst_amounts(full_text)
    items = []
    if getattr(result, "documents", None):
        docs = result.documents
        if docs:
            doc0 = docs[0]
            if getattr(doc0, "fields", None):
                 inv_id_field = doc0.fields.get("InvoiceId")
                 if inv_id_field:
                     header["InvoiceId"] = inv_id_field.value_string or inv_id_field.content

            items_field = doc0.fields.get("Items") if getattr(doc0, "fields", None) else None
            if items_field and getattr(items_field, "value_array", None):
                for item in items_field.value_array:
                    obj = item.value_object or {}
                    def rv(k):
                        v = obj.get(k)
                        if not v:
                            return None
                        try:
                            if getattr(v, "value_currency", None) and getattr(v.value_currency, "amount", None) is not None:
                                return v.value_currency.amount
                        except Exception:
                            pass
                        for attr in ("value_string", "value_number"):
                            try:
                                val = getattr(v, attr, None)
                                if val is not None:
                                    return val
                            except Exception:
                                pass
                        return None
                    desc = rv("Description") or rv("ItemDescription") or rv("Name")
                    qty = rv("Quantity")
                    amt = rv("Amount") or rv("TotalPrice")
                    items.append({
                        "Description": str(desc) if desc else None,
                        "Qty": float(qty) if qty else None,
                        "Amount": _to_float(_parse_amount(amt)) if amt else None
                    })
    if not items:
        items = extract_items_from_text(full_text)
    header = {
        "CGST_total": cgst,
        "SGST_total": sgst,
        "IGST_total": igst,
        "Tax_Total": round((cgst or 0.0) + (sgst or 0.0) + (igst or 0.0), 2)
    }
    m = re.search(r"Grand\s*Total[^\d]*([0-9,]+\.\d{2})", full_text, re.I)
    grand_total = parse_decimal_token(m.group(1)) if m else None
    header["GrandTotal"] = grand_total
    header["raw_text"] = full_text
    return header, items

# -------------------- SKU extraction & matching (new rule: starting model prefix) --------------------

def clean_sku(s):
    if s is None:
        return None
    s = str(s).strip()
    # remove leading PA- or PA_ etc.
    s = re.sub(r'^(PA[-_]?)', '', s, flags=re.I)
    return s

def extract_pdf_model_prefix(description):
    """
    Extract model prefix from the start of a description.
    Examples:
      - "SR-WA18H(FK)PMB ..." -> "SR-WA18H"
      - "SR-WA10(E)BLK Some text" -> "SR-WA10"
    Rules:
      - take first token up to space or slash
      - cut at first '(' if present
      - strip trailing non-alnum/- characters
    """
    if not description:
        return None
    desc = str(description).strip()
    token = re.split(r"[ \\/]", desc)[0]
    token = token.split("(")[0]
    token = re.sub(r"[^A-Za-z0-9-]+$", "", token)
    token = token.strip()
    return token or None

def find_sku_in_description(description, excel_skus_cleaned):
    model_prefix = extract_pdf_model_prefix(description)
    if not model_prefix:
        return None
    model_norm = model_prefix.strip().lower()
    # 1) exact match
    for sku in excel_skus_cleaned:
        if str(sku).strip().lower() == model_norm:
            return sku
    # 2) excel sku contains model_prefix (or vice versa)
    for sku in excel_skus_cleaned:
        s = str(sku).strip().lower()
        if model_norm in s or s in model_norm:
            return sku
    # 3) fallback to substring anywhere in description
    dlow = str(description).lower()
    for sku in excel_skus_cleaned:
        if str(sku).lower() in dlow:
            return sku
    return None

# -------------------- Comparison logic --------------------

def compare(parsed_header, parsed_items, df_excel):
    # detect excel columns heuristically
    sku_col = None
    qty_col = None
    included_tax_col = None
    total_value_col = None
    for c in df_excel.columns:
        lc = str(c).lower()
        if ('sku' in lc or 'item code' in lc or 'product' in lc or lc.strip()=='item') and sku_col is None:
            sku_col = c
        if (('ordered' in lc and 'qty' in lc) or 'ordered quantity' in lc or ('quantity' in lc and 'ordered' in lc)) and qty_col is None:
            qty_col = c
        if ('included' in lc and 'tax' in lc) and included_tax_col is None:
            included_tax_col = c
        if ('total value' in lc or lc.strip()=='total' or 'amount' in lc or 'value' in lc) and total_value_col is None:
            total_value_col = c
    # fallbacks
    if sku_col is None:
        for c in df_excel.columns:
            if df_excel[c].astype(str).str.contains(r'PA-?|[A-Z0-9\-]{4,}', na=False).any():
                sku_col = c; break
    if qty_col is None:
        for c in df_excel.columns:
            if 'qty' in str(c).lower() or 'quantity' in str(c).lower():
                qty_col = c; break
    if included_tax_col is None:
        for c in df_excel.columns:
            if 'tax' in str(c).lower() and 'include' in str(c).lower():
                included_tax_col = c; break
    if total_value_col is None:
        for c in df_excel.columns:
            if 'total' in str(c).lower() or 'value' in str(c).lower() or 'amount' in str(c).lower():
                total_value_col = c; break

    excel_skus_cleaned = df_excel[sku_col].astype(str).apply(clean_sku).unique().tolist() if sku_col else []

    results = []
    matched_excel_indices = set()

    for it in parsed_items:
        desc = it.get('Description') or ''
        pdf_sku = find_sku_in_description(desc, excel_skus_cleaned)
        matched_rows = pd.DataFrame()
        if pdf_sku and sku_col:
            cond = df_excel[sku_col].astype(str).apply(lambda x: clean_sku(x)).astype(str).str.lower() == str(pdf_sku).lower()
            matched_rows = df_excel[cond]
        if matched_rows.empty and sku_col:
            cond = df_excel[sku_col].astype(str).apply(lambda x: clean_sku(x)).astype(str).str.lower().apply(lambda s: str(s) in str(desc).lower())
            matched_rows = df_excel[cond]
        if matched_rows is None or matched_rows.empty:
            results.append({
                'pdf_description': desc,
                'pdf_sku': pdf_sku,
                'matched': False,
                'matched_excel_rows': None,
                'pdf_qty': it.get('Qty'),
                'excel_ordered_qty': None,
                'qty_match': False,
                'pdf_item_tax': it.get('Tax') or None,
                'excel_included_tax_sum': None,
                'tax_match': False,
                'pdf_amount': it.get('Amount'),
                'excel_total_value_sum': None
            })
        else:
            excel_indices = matched_rows.index.tolist()
            for idx in excel_indices:
                matched_excel_indices.add(idx)
            excel_included_tax_sum = pd.to_numeric(matched_rows[included_tax_col], errors='coerce').sum(min_count=1) if included_tax_col else None
            excel_total_value_sum = pd.to_numeric(matched_rows[total_value_col], errors='coerce').sum(min_count=1) if total_value_col else None
            excel_ordered_qty = pd.to_numeric(matched_rows[qty_col], errors='coerce').sum(min_count=1) if qty_col else None

            qty_match = False
            if excel_ordered_qty is not None and it.get('Qty') is not None:
                try:
                    qty_match = abs(float(excel_ordered_qty) - float(it.get('Qty'))) < 1e-6
                except Exception:
                    qty_match = False

            tax_match = False
            if excel_included_tax_sum is not None:
                try:
                    tax_match = abs(float(excel_included_tax_sum) - float(it.get('Tax') or 0.0)) < 0.5
                except Exception:
                    tax_match = False

            results.append({
                'pdf_description': desc,
                'pdf_sku': pdf_sku,
                'matched': True,
                'matched_excel_rows': matched_rows.to_dict(orient='records'),
                'pdf_qty': it.get('Qty'),
                'excel_ordered_qty': excel_ordered_qty,
                'qty_match': qty_match,
                'pdf_item_tax': it.get('Tax') or 0.0,
                'excel_included_tax_sum': excel_included_tax_sum,
                'tax_match': tax_match,
                'pdf_amount': it.get('Amount'),
                'excel_total_value_sum': excel_total_value_sum
            })

    overall = {}
    overall['excel_total_included_tax'] = pd.to_numeric(df_excel[included_tax_col], errors='coerce').sum(min_count=1) if included_tax_col else None
    overall['excel_total_value'] = pd.to_numeric(df_excel[total_value_col], errors='coerce').sum(min_count=1) if total_value_col else None
    overall['pdf_tax_total'] = parsed_header.get('Tax_Total')
    overall['pdf_grand_total'] = parsed_header.get('GrandTotal')

    n_items = len(parsed_items)
    n_matched = sum(1 for r in results if r['matched'])
    n_qty_matched = sum(1 for r in results if r['qty_match'])
    n_tax_matched = sum(1 for r in results if r['tax_match'])
    acc = {
        'n_items': n_items,
        'n_matched': n_matched,
        'pct_items_matched': (n_matched / n_items * 100) if n_items else 0,
        'n_qty_matched': n_qty_matched,
        'pct_qty_matched': (n_qty_matched / n_items * 100) if n_items else 0,
        'n_tax_matched': n_tax_matched,
        'pct_tax_matched': (n_tax_matched / n_items * 100) if n_items else 0
    }

    return results, overall, acc

# -------------------- Streamlit UI --------------------

# Apply Professional UI
apply_professional_style()

def main():
    st.set_page_config(page_title='PDF vs Excel Reconciliation (Azure only)', layout='wide')
    render_header('PDF ⇄ Excel Reconciliation (Azure Document Intelligence required)', 'Upload invoice PDF(s) and reference Excel. SKU matching prefers model prefix at start of description (e.g. SR-WA18H).')


    endpoint_env = os.getenv('AZURE_ENDPOINT')
    key_env = os.getenv('AZURE_KEY')

    with st.sidebar:
        st.header('Azure credentials')
        if endpoint_env and key_env:
            st.success('Azure credentials loaded from environment (hidden).')
            st.caption('Endpoint/key read from environment or .env — not displayed here.')
            endpoint = endpoint_env
            key = key_env
        else:
            st.warning('No AZURE_ENDPOINT/AZURE_KEY found in environment. Paste them here (session-only).')
            endpoint = st.text_input('Azure Endpoint', value='')
            key = st.text_input('Azure Key (masked)', value='', type='password')

    uploaded_pdf = st.file_uploader('Upload one or more invoice PDFs', type=['pdf'], accept_multiple_files=True)
    uploaded_excel = st.file_uploader('Upload reference Excel/CSV', type=['xlsx','xls','csv'])

    if st.button('Run Reconciliation'):
        if not uploaded_pdf:
            st.error('Please upload at least one PDF.')
            return
        if not uploaded_excel:
            st.error('Please upload reference Excel/CSV.')
            return

        try:
            excel_bytes = uploaded_excel.read()
            df_excel = read_excel_row1_as_header_bytes(excel_bytes)
        except Exception as e:
            st.error(f'Failed to read Excel: {e}')
            return

        for pdf_file in uploaded_pdf:
            st.write('Processing', pdf_file.name)
            pdf_bytes = pdf_file.read()
            try:
                if not AZURE_AVAILABLE:
                    st.error('Azure SDK not available. Install azure-ai-documentanalysis.')
                    continue
                if not endpoint or not key:
                    st.error('Azure endpoint/key not provided. Set them in environment or sidebar.')
                    continue
                parsed_header, parsed_items = parse_pdf_with_azure(pdf_bytes, endpoint, key)
            except Exception as e:
                st.error(f'Failed to parse {pdf_file.name}: {e}')
                continue

            # normalize per-item tax field
            for it in parsed_items:
                tax = 0.0
                if it.get('CGST'): tax += float(it.get('CGST') or 0.0)
                if it.get('SGST'): tax += float(it.get('SGST') or 0.0)
                if it.get('IGST'): tax += float(it.get('IGST') or 0.0)
                it['Tax'] = it.get('Tax') or tax or None

            results, overall, acc = compare(parsed_header, parsed_items, df_excel)

            st.subheader(f'Results for {pdf_file.name}')
            st.write('Invoice header (extracted):')
            st.json(parsed_header)

            st.write('Per-item comparisons:')
            df_res = pd.DataFrame([{
                'pdf_description': r['pdf_description'],
                'pdf_sku': r['pdf_sku'],
                'matched': r['matched'],
                'pdf_qty': r['pdf_qty'],
                'excel_ordered_qty': r['excel_ordered_qty'],
                'qty_match': r['qty_match'],
                'pdf_item_tax': r.get('pdf_item_tax'),
                'excel_included_tax_sum': r.get('excel_included_tax_sum'),
                'tax_match': r.get('tax_match'),
                'pdf_amount': r.get('pdf_amount'),
                'excel_total_value_sum': r.get('excel_total_value_sum')
            } for r in results])
            st.dataframe(df_res)

            st.write('Overall invoice-level comparison:')
            overall_display = {
                'excel_total_included_tax': overall.get('excel_total_included_tax'),
                'excel_total_value': overall.get('excel_total_value'),
                'pdf_tax_total': overall.get('pdf_tax_total'),
                'pdf_grand_total': overall.get('pdf_grand_total')
            }
            st.table(pd.DataFrame(list(overall_display.items()), columns=['Metric','Value']))

            st.write('Accuracy metrics:')
            st.table(pd.DataFrame(list(acc.items()), columns=['Metric','Value']))

            # in-memory Excel download
            try:
                towrite = io.BytesIO()
                with pd.ExcelWriter(towrite, engine='openpyxl') as writer:
                    df_res.to_excel(writer, sheet_name='PerItem', index=False)
                    pd.DataFrame([overall]).to_excel(writer, sheet_name='Overall', index=False)
                    pd.DataFrame([acc]).to_excel(writer, sheet_name='Metrics', index=False)
                towrite.seek(0)
                # Save to MongoDB
                try:
                     # This uses the fixed common.mongo utility
                     save_reconciliation_report(
                        collection_name="panasonic_reconciliation",
                        invoice_no=parsed_header.get("InvoiceId"),
                        summary_data=pd.DataFrame([overall]),
                        line_items_data=df_res,
                        metadata={
                            "accuracy": acc,
                            "file_name_pdf": pdf_file.name,
                             "file_name_excel": uploaded_excel.name
                        }
                    )
                except Exception as e:
                    logger.warning(f"Auto-save error: {e}")

                # Standardized download section
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    download_module_report(
                        df=df_res,
                        module_name="reconciliation",
                        report_name=f"Panasonic_Detailed_{os.path.splitext(pdf_file.name)[0]}",
                        button_label="📥 Download Detailed Report",
                        key=f"dl_panasonic_detailed_{pdf_file.name}"
                    )
                with col_dl2:
                    download_module_report(
                        df=pd.DataFrame([overall]),
                        module_name="reconciliation",
                        report_name=f"Panasonic_Summary_{os.path.splitext(pdf_file.name)[0]}",
                        button_label="📥 Download Summary",
                        key=f"dl_panasonic_summary_{pdf_file.name}"
                    )

            except Exception as e:
                st.warning('Could not prepare Excel download: ' + str(e))

    st.markdown('---')
    st.caption('Keep your .env file on the server and do not commit it to source control. When loaded from environment, credentials are not displayed in the UI.')

if __name__ == '__main__':
    main()
