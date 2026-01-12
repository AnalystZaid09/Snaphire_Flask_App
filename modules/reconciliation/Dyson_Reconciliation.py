import os
import io
import ast
import json
import re
import logging

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from openpyxl import Workbook
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "reconciliation"

# ======================================================================
# INITIAL SETUP
# ======================================================================

load_dotenv()

# These come from your .env file
DEFAULT_AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT", "")
DEFAULT_AZURE_KEY = os.getenv("AZURE_KEY", "")

# Config thresholds
NAME_THRESHOLD = 90
AMOUNT_TOL_PCT = 0.005   # 0.5%
SKU_STRICT = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ======================================================================
# UTILITY FUNCTIONS
# ======================================================================

def norm_text(s):
    if s is None:
        return ""
    s = str(s).replace("\r", "\n").replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def fuzzy_score(a, b):
    return int(
        fuzz.token_sort_ratio(
            str(a) if a is not None else "",
            str(b) if b is not None else ""
        )
    )


def parse_number(x):
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return None
    s = s.replace("₹", "").replace("inr", "").replace(",", "").strip()
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except Exception:
            return None
    m = re.match(r'^\((.+)\)$', s)
    if m:
        try:
            return -float(m.group(1).replace(",", ""))
        except Exception:
            pass
    try:
        return float(s)
    except Exception:
        return None


def get_val_conf(field):
    if field is None:
        return None, None
    if isinstance(field, (str, int, float)):
        return field, None
    if isinstance(field, dict):
        conf = field.get("confidence")
        if isinstance(field.get("valueCurrency"), dict):
            return field["valueCurrency"].get("amount"), conf
        if "valueNumber" in field:
            return field.get("valueNumber"), conf
        if "valueString" in field:
            return field.get("valueString"), conf
        if "content" in field:
            return field.get("content"), conf
        return str(field), conf

    val = getattr(field, "value", None)
    conf = getattr(field, "confidence", None)
    cont = getattr(field, "content", None)
    if val is not None:
        return val, conf
    if cont is not None:
        return cont, conf
    to_dict = getattr(field, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            if isinstance(d, dict):
                if "valueCurrency" in d and isinstance(d["valueCurrency"], dict):
                    return d["valueCurrency"].get("amount"), d.get("confidence")
                if "valueNumber" in d:
                    return d.get("valueNumber"), d.get("confidence")
                if "content" in d:
                    return d.get("content"), d.get("confidence")
            return d, None
        except Exception:
            pass
    return str(field), None


def safe_eval_maybe(s):
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return s
    try:
        return ast.literal_eval(s)
    except Exception:
        try:
            return json.loads(s.replace("'", '"'))
        except Exception:
            return s


def parse_items_field(items_field):
    parsed = safe_eval_maybe(items_field)
    rows = []
    if isinstance(parsed, dict) and parsed.get("type") == "array" and "valueArray" in parsed:
        for ent in parsed["valueArray"]:
            vo = ent.get("valueObject") if isinstance(ent, dict) else ent
            if isinstance(vo, dict):
                if isinstance(ent, dict) and "content" in ent:
                    vo["content"] = ent["content"]
                rows.append(vo)
            else:
                row_dict = {"value": vo}
                if isinstance(ent, dict) and "content" in ent:
                    row_dict["content"] = ent["content"]
                rows.append(row_dict)
        return rows
    if isinstance(parsed, list):
        for it in parsed:
            if isinstance(it, dict) and "valueObject" in it:
                vo = it["valueObject"]
                if "content" in it:
                    vo["content"] = it["content"]
                rows.append(vo)
            elif isinstance(it, dict):
                rows.append(it)
            else:
                rows.append({"value": it})
        return rows
    if isinstance(parsed, dict) and parsed.get("type") == "object" and "valueObject" in parsed:
        vo = parsed["valueObject"]
        if "content" in parsed:
            vo["content"] = parsed["content"]
        rows.append(vo)
        return rows
    return [{"content": parsed}] if parsed is not None else []


def extract_cgst_sgst_from_content(item_content, tax_amount):
    logger.info(
        f"Extracting CGST/SGST: item_content type={type(item_content)}, tax_amount={tax_amount}"
    )
    if not item_content or tax_amount is None:
        return None, None

    content_str = str(item_content)
    rate_pattern = re.findall(r'(\d+(?:\.\d+)?)%', content_str)

    if len(rate_pattern) >= 2 and rate_pattern[0] == rate_pattern[1]:
        return tax_amount, tax_amount

    return None, None


def normalize_ocr_item(item):
    def pick(*keys):
        for k in keys:
            if k in item:
                return get_val_conf(item[k])
            if k.lower() in item:
                return get_val_conf(item[k.lower()])
        return None, None

    sku, sku_conf = pick("ProductCode", "Material", "MaterialNo", "SKU")
    name, name_conf = pick("Description", "DescriptionText", "Name")
    qty_raw, qty_conf = pick("Quantity", "Qty")
    unit_raw, unit_conf = pick("UnitPrice", "Unit Price")
    amt_raw, amt_conf = pick("Amount", "LineTotal", "Total")
    tax_raw, tax_conf = pick("Tax", "TaxAmount")
    taxrate_raw, taxrate_conf = pick("TaxRate")
    cgst_raw, cgst_conf = pick("CGST")
    sgst_raw, sgst_conf = pick("SGST")

    qty = parse_number(qty_raw)
    unit = parse_number(unit_raw)
    amt = parse_number(amt_raw)
    tax = parse_number(tax_raw)
    cgst = parse_number(cgst_raw)
    sgst = parse_number(sgst_raw)
    taxrate = parse_number(taxrate_raw)

    item_content = item.get("content") if "content" in item else None
    if (cgst is None or sgst is None) and tax is not None:
        extracted_cgst, extracted_sgst = extract_cgst_sgst_from_content(
            item_content, tax
        )
        if extracted_cgst is not None:
            cgst = extracted_cgst
        if extracted_sgst is not None:
            sgst = extracted_sgst

    total_tax = 0.0
    if cgst is not None and sgst is not None:
        total_tax = cgst + sgst
    elif cgst is not None or sgst is not None:
        total_tax = (cgst or 0.0) + (sgst or 0.0)
    elif tax is not None:
        total_tax = tax

    line_total_with_tax = None
    if amt is not None:
        line_total_with_tax = amt + total_tax

    confs = [c for c in (sku_conf, name_conf, qty_conf, unit_conf, amt_conf, tax_conf) if c is not None]
    avg_conf = sum(confs) / len(confs) if confs else None

    return {
        "SKU_raw": sku,
        "SKU": str(sku).strip() if sku is not None else None,
        "SKU_conf": sku_conf,
        "Name_raw": name,
        "Name": norm_text(name) if name else None,
        "Name_conf": name_conf,
        "Quantity_raw": qty_raw,
        "Quantity": qty,
        "UnitPrice_raw": unit_raw,
        "UnitPrice": unit,
        "Amount_raw": amt_raw,
        "Amount": amt,
        "Tax_raw": tax_raw,
        "Tax": tax,
        "TaxRate_raw": taxrate_raw,
        "TaxRate": taxrate,
        "CGST": cgst,
        "SGST": sgst,
        "TotalTax": total_tax,
        "LineTotalWithTax": line_total_with_tax,
        "avg_conf": avg_conf,
        "raw_content": item.get("content") if "content" in item else None,
    }


def find_your_reference(headers, ocr_items, raw_content=None, prefer_prefixes=None):
    if prefer_prefixes is None:
        prefer_prefixes = ["FBA", "PO", "SO", "REF"]

    def scan_text_for_candidate(text):
        if text is None:
            return None
        txt = str(text)
        candidates = re.findall(r"\b[A-Z]{2,}[0-9A-Z\-_/]{3,}\b", txt)
        if not candidates:
            candidates = re.findall(r"\b[A-Za-z0-9]{6,}\b", txt)
        candidates = [c for c in candidates if not re.fullmatch(r"\d{6,}", c)]
        if not candidates:
            return None
        for p in prefer_prefixes:
            for c in candidates:
                if c.upper().startswith(p.upper()):
                    return c
        return candidates[0]

    fallback = None
    for k, v in headers.items():
        txt = v.get("value") if isinstance(v, dict) and "value" in v else v
        cand = scan_text_for_candidate(txt)
        if cand:
            if any(t in k.lower() for t in ["reference", "your", "ref", "po"]):
                return cand
            fallback = cand

    for k, v in headers.items():
        if any(t in k.lower() for t in ["reference", "your", "ref"]):
            txt = v.get("value") if isinstance(v, dict) and "value" in v else v
            cand = scan_text_for_candidate(txt)
            if cand:
                return cand

    if raw_content:
        match = re.search(
            r"Your\s+Reference[:\s]+([A-Z0-9]{6,})",
            raw_content,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        cand = scan_text_for_candidate(raw_content)
        if cand:
            return cand

    for it in ocr_items:
        raw = it.get("raw_content") or it.get("content") or ""
        cand = scan_text_for_candidate(raw)
        if cand:
            return cand

    return fallback


def sum_invoice_tax(ocr_items):
    total_cgst = 0.0
    total_sgst = 0.0
    total_tax = 0.0
    saw_gst = False
    saw_tax = False

    for it in ocr_items:
        cgst = it.get("CGST")
        sgst = it.get("SGST")
        tax = it.get("Tax")

        if cgst is not None:
            try:
                total_cgst += float(cgst)
                saw_gst = True
            except Exception:
                pass
        if sgst is not None:
            try:
                total_sgst += float(sgst)
                saw_gst = True
            except Exception:
                pass
        if tax is not None:
            try:
                total_tax += float(tax)
                saw_tax = True
            except Exception:
                pass

    if saw_gst:
        return total_cgst + total_sgst
    elif saw_tax:
        return total_tax
    return None


def detect_header_row(df_no_header, header_keywords=None, max_scan=12):
    if header_keywords is None:
        header_keywords = [
            "sku",
            "name",
            "po ref",
            "po ref no",
            "ordered quantity",
            "item price",
            "base price",
        ]
    for r in range(min(max_scan, df_no_header.shape[0])):
        row = [
            str(x).lower() if pd.notna(x) else ""
            for x in df_no_header.iloc[r].astype(str).tolist()
        ]
        hits = sum(any(k in cell for cell in row) for k in header_keywords)
        if hits >= 1:
            if (
                any("sku" in c for c in row)
                or any("name" in c for c in row)
                or any("po ref" in c for c in row)
            ):
                return r
            if hits >= 2:
                return r
    for r in range(min(max_scan, df_no_header.shape[0])):
        row = df_no_header.iloc[r].astype(str).tolist()
        nonnum = sum(
            1
            for c in row
            if not re.match(
                r"^\s*$|^\d+(\.\d+)?$", str(c).replace(",", "").strip()
            )
        )
        if nonnum >= max(1, len(row) // 3):
            return r
    return 0


def canonical_col(c):
    s = str(c).strip().lower()
    s = s.replace("ean/upc", "ean_upc")
    s = s.replace("po ref no", "po_ref_no").replace("po ref", "po_ref_no")
    s = s.replace("ordered quantity", "ordered_quantity").replace(
        "pending quantity", "pending_quantity"
    )
    s = s.replace("base price", "base_price").replace("item price", "item_price")
    s = s.replace("tax rate", "tax_rate").replace("included tax", "included_tax").replace(
        "total value", "total_value"
    )
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9a-z_]", "", s)
    return s


def clean_excel_file_from_upload(upload_file):
    raw = pd.read_excel(upload_file, header=None, dtype=str)
    header_row = detect_header_row(raw)
    header_labels = raw.iloc[header_row].fillna("").astype(str).tolist()
    header_labels = [
        lbl if lbl.strip() != "" else f"col_{i}"
        for i, lbl in enumerate(header_labels)
    ]
    df = raw.iloc[header_row + 1:].copy().reset_index(drop=True)
    df.columns = header_labels
    for c in df.columns:
        df[c] = df[c].apply(lambda x: x.strip() if isinstance(x, str) else x)

    df.columns = [canonical_col(c) for c in df.columns]

    po_candidates = [c for c in df.columns if "purchase" in c and "order" in c]
    if po_candidates:
        df = df.rename(columns={po_candidates[0]: "purchase_order_no"})
    elif "po_ref_no" in df.columns:
        df = df.rename(columns={"po_ref_no": "purchase_order_no"})
    else:
        df.insert(0, "purchase_order_no", None)

    return df


def map_excel_to_ocr(excel_rows, ocr_lines):
    mapping = {}
    used = set()

    for ei, ex in enumerate(excel_rows):
        ex_sku = (
            ex.get("sku")
            or ex.get("SKU")
            or ex.get("material")
            or ex.get("material_no")
            or ex.get("sku")
        )
        if ex_sku:
            ex_sku_n = str(ex_sku).strip().lower()
            found = None
            for oi, ol in enumerate(ocr_lines):
                if oi in used:
                    continue
                o_sku = ol.get("SKU") or ol.get("SKU_raw")
                if o_sku:
                    osku_n = str(o_sku).strip().lower()
                    if SKU_STRICT:
                        if ex_sku_n == osku_n:
                            found = oi
                            break
                    else:
                        if (
                            ex_sku_n == osku_n
                            or ex_sku_n in osku_n
                            or osku_n in ex_sku_n
                        ):
                            found = oi
                            break
            if found is not None:
                mapping[ei] = found
                used.add(found)

    for ei, ex in enumerate(excel_rows):
        if ei in mapping:
            continue
        ex_name = ex.get("name") or ex.get("Name") or ex.get("description") or ""
        best_score = -1
        best_oi = None
        for oi, ol in enumerate(ocr_lines):
            if oi in used:
                continue
            s = fuzzy_score(ol.get("Name", ""), ex_name)
            if s > best_score:
                best_score = s
                best_oi = oi
        if best_score >= NAME_THRESHOLD:
            mapping[ei] = best_oi
            used.add(best_oi)

    for ei in range(len(excel_rows)):
        if ei not in mapping:
            if ei < len(ocr_lines) and ei not in used:
                mapping[ei] = ei
                used.add(ei)
            else:
                mapping[ei] = None
    return mapping


def compare_mapped_row(ex_row, ocr_line):
    ex_sku = ex_row.get("sku") or ex_row.get("SKU") or ""
    o_sku = ocr_line.get("SKU") or ""
    sku_match = False
    if ex_sku and o_sku:
        es = str(ex_sku).strip().lower()
        osk = str(o_sku).strip().lower()
        sku_match = (es == osk) or (not SKU_STRICT and (es in osk or osk in es))

    ex_qty_raw = (
        ex_row.get("ordered_quantity")
        or ex_row.get("ordered quantity")
        or ex_row.get("ordered_quantity")
    )
    ex_qty_num = parse_number(ex_qty_raw)
    o_qty_num = ocr_line.get("Quantity")
    qty_match = False
    if ex_qty_num is not None and o_qty_num is not None:
        qty_match = float(ex_qty_num) == float(o_qty_num)

    ex_amt_raw = (
        ex_row.get("item_price")
        or ex_row.get("item price")
        or ex_row.get("total_value")
        or ex_row.get("base_price")
    )
    ex_amt_num = parse_number(ex_amt_raw)
    o_amt_num = ocr_line.get("Amount") or ocr_line.get("UnitPrice")
    amt_match = False
    amt_diff_pct = None
    if ex_amt_num is not None and o_amt_num is not None:
        if ex_amt_num != 0:
            amt_diff_pct = abs(o_amt_num - ex_amt_num) / abs(ex_amt_num)
            amt_match = amt_diff_pct <= AMOUNT_TOL_PCT
        else:
            amt_match = (o_amt_num == 0)

    name_ref = ex_row.get("name") or ex_row.get("Name")
    name_ocr = ocr_line.get("Name")
    nm_score = fuzzy_score(name_ocr or "", name_ref or "")

    return {
        "SKU_ref": ex_sku,
        "SKU_ocr": o_sku,
        "SKU_match": bool(sku_match),
        "Name_ref": name_ref,
        "Name_ocr": name_ocr,
        "Name_score": nm_score,
        "Name_match": nm_score >= NAME_THRESHOLD,
        "Qty_ref": ex_qty_num,
        "Qty_ocr": o_qty_num,
        "Qty_match": bool(qty_match),
        "Amt_ref": ex_amt_num,
        "Amt_ocr": o_amt_num,
        "Amt_diff_pct": float(amt_diff_pct) if amt_diff_pct is not None else None,
        "Amt_match": bool(amt_match),
        "ocr_avg_conf": ocr_line.get("avg_conf"),
        "Tax_ocr": (ocr_line.get("Tax") or 0.0)
        + (ocr_line.get("CGST") or 0.0)
        + (ocr_line.get("SGST") or 0.0),
    }


# ======================================================================
# SAVE SUMMARY TO EXCEL
# ======================================================================

def save_summary_to_excel_bytes(summary_row: dict, cols: list):
    wb = Workbook()
    ws = wb.active
    ws.title = "summary"

    ws.append(cols)
    ws.append([summary_row.get(c) for c in cols])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


# ======================================================================
# AZURE OCR
# ======================================================================

@st.cache_resource(show_spinner=False)
def get_azure_client(endpoint: str, key: str):
    return DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))


def analyze_pdf_file_streamlit(pdf_file, client: DocumentIntelligenceClient):
    file_name = pdf_file.name
    logger.info(f"Analyzing PDF: {file_name}")
    b = pdf_file.read()
    poller = client.begin_analyze_document(
        model_id="prebuilt-invoice", body=io.BytesIO(b)
    )
    res = poller.result()

    raw_content = getattr(res, "content", "")

    if not hasattr(res, "documents") or not res.documents:
        raise RuntimeError("No document parsed from Azure for " + file_name)

    doc = res.documents[0]
    headers = {}
    for k, v in doc.fields.items():
        val, conf = get_val_conf(v)
        headers[k] = {"value": val, "confidence": conf} if not isinstance(val, dict) else val

    items_raw = []
    if "Items" in doc.fields:
        raw_items, _ = get_val_conf(doc.fields["Items"])
        items_raw = parse_items_field(raw_items)
    else:
        for k in doc.fields:
            if "item" in k.lower() or "line" in k.lower():
                raw_items, _ = get_val_conf(doc.fields[k])
                items_raw = parse_items_field(raw_items)
                break

    normalized_items = [normalize_ocr_item(it) for it in items_raw]

    raw_doc_dict = res.as_dict() if hasattr(res, "as_dict") else {}

    return headers, normalized_items, raw_content, raw_doc_dict


# ======================================================================
# MAIN PROCESSOR FOR ONE PAIR
# ======================================================================

def process_invoice_pair(pdf_file, excel_file, client: DocumentIntelligenceClient):
    headers, ocr_items, raw_content, raw_doc_dict = analyze_pdf_file_streamlit(
        pdf_file, client
    )

    ocr_ref = find_your_reference(
        headers, ocr_items, raw_content, prefer_prefixes=["FBA", "PO"]
    )

    # Totals from OCR
    ocr_invoice_total = None
    if "InvoiceTotal" in headers:
        vt = headers["InvoiceTotal"]
        ocr_invoice_total = vt.get("value") if isinstance(vt, dict) else vt
    ocr_invoice_total_num = parse_number(ocr_invoice_total)

    ocr_invoice_tax_total = sum_invoice_tax(ocr_items)

    ocr_subtotal = None
    if "SubTotal" in headers:
        stf = headers["SubTotal"]
        ocr_subtotal = stf.get("value") if isinstance(stf, dict) else stf
    ocr_subtotal_num = parse_number(ocr_subtotal)

    total_cgst = sum(it.get("CGST") or 0.0 for it in ocr_items)
    total_sgst = sum(it.get("SGST") or 0.0 for it in ocr_items)

    calculated_total = None
    if ocr_subtotal_num is not None:
        calculated_total = ocr_subtotal_num + total_cgst + total_sgst

    # Total quantity from OCR
    ocr_total_qty = sum((it.get("Quantity") or 0.0) for it in ocr_items)

    cleaned = clean_excel_file_from_upload(excel_file)
    excel_rows = cleaned.to_dict("records")

    # total quantity from Excel (ordered_quantity)
    excel_total_qty = None
    if "ordered_quantity" in cleaned.columns:
        col = cleaned["ordered_quantity"].dropna()
        if not col.empty:
            excel_total_qty = col.apply(parse_number).dropna().sum()

    # PO ref from Excel
    excel_po_ref = None
    if "purchase_order_no" in cleaned.columns:
        col = cleaned["purchase_order_no"].dropna()
        if not col.empty:
            excel_po_ref = str(col.iloc[0]).strip()
    elif "po_ref_no" in cleaned.columns:
        col = cleaned["po_ref_no"].dropna()
        if not col.empty:
            excel_po_ref = str(col.iloc[0]).strip()

    # we still map / compare (not displayed but could be useful)
    mapping = map_excel_to_ocr(excel_rows, ocr_items)
    comparisons = []
    for ei, ex in enumerate(excel_rows):
        oi = mapping.get(ei)
        oline = ocr_items[oi] if (oi is not None and oi < len(ocr_items)) else {}
        cmp = compare_mapped_row(ex, oline)
        cmp.update(
            {
                "excel_index": ei,
                "ocr_index": oi,
                "invoice_file": pdf_file.name,
                "excel_file": excel_file.name,
                "PO_ref_excel": ex.get("po_ref_no")
                or ex.get("po_ref")
                or ex.get("purchase_order_no"),
            }
        )
        comparisons.append(cmp)

    df_comp = pd.DataFrame(comparisons)

    excel_included_tax_sum = None
    if "included_tax" in cleaned.columns:
        col = cleaned["included_tax"].dropna()
        if not col.empty:
            excel_included_tax_sum = col.apply(parse_number).dropna().sum()

    excel_total_value_sum = None
    if "total_value" in cleaned.columns:
        col = cleaned["total_value"].dropna()
        if not col.empty:
            excel_total_value_sum = col.apply(parse_number).dropna().sum()

    invoice_summary = {
        "ocr_invoice_ref": ocr_ref,
        "ocr_invoice_total_num": ocr_invoice_total_num,
        "ocr_subtotal": ocr_subtotal_num,
        "ocr_cgst_total": total_cgst,
        "ocr_sgst_total": total_sgst,
        "ocr_invoice_tax_total": ocr_invoice_tax_total,
        "ocr_calculated_total": calculated_total,
        "ocr_total_qty": ocr_total_qty,
        "excel_included_tax_sum": excel_included_tax_sum,
        "excel_total_value_sum": excel_total_value_sum,
        "excel_total_qty": excel_total_qty,
        "excel_po_ref": excel_po_ref,
    }

    return df_comp, invoice_summary, raw_doc_dict


# ======================================================================
# STREAMLIT UI
# ======================================================================

def main():
    global NAME_THRESHOLD, AMOUNT_TOL_PCT, SKU_STRICT

    st.set_page_config(
        page_title="Invoice Reconciliation Tool",
        layout="wide",
    )

    st.title("🧾 Invoice Reconciliation Tool")


    apply_professional_style()
    render_header("Dyson Invoice Reconciliation", "Compare Dyson Invoice PDFs with Excel PO/Records")
    
    st.sidebar.header("Azure Configuration")

    NAME_THRESHOLD = st.sidebar.slider(
        "Name fuzzy match threshold",
        min_value=70,
        max_value=100,
        value=90,
        step=1,
    )

    AMOUNT_TOL_PCT = st.sidebar.slider(
        "Amount tolerance (%)",
        min_value=0.0,
        max_value=5.0,
        value=0.5,
        step=0.1,
    ) / 100.0

    SKU_STRICT = st.sidebar.checkbox(
        "Strict SKU matching (exact only)", value=False
    )

    st.sidebar.markdown("---")
    show_raw_json = st.sidebar.checkbox(
        "Show raw Azure JSON output (debug)", value=False
    )

    # Use values ONLY from .env
    endpoint = DEFAULT_AZURE_ENDPOINT
    key = DEFAULT_AZURE_KEY

    # Uploads
    st.subheader("1️⃣ Upload files")
    col1, col2 = st.columns(2)

    with col1:
        pdf_file = st.file_uploader(
            "Invoice PDF",
            type=["pdf"],
            accept_multiple_files=False,
        )
    with col2:
        excel_file = st.file_uploader(
            "Reference Excel",
            type=["xlsx", "xlsm", "xls"],
            accept_multiple_files=False,
        )

    run_button = st.button("🚀 Run Reconciliation")

    if run_button:
        if not endpoint or not key:
            st.error(
                "Azure endpoint or key is not configured.\n\n"
                "Please set AZURE_ENDPOINT and AZURE_KEY in your `.env` file."
            )
            return
        if not pdf_file or not excel_file:
            st.error("Please upload both an invoice PDF and a reference Excel file.")
            return

        client = get_azure_client(endpoint, key)

        with st.spinner("Analyzing invoice and reconciling with Excel..."):
            try:
                df_comp, invoice_summary, raw_doc_dict = process_invoice_pair(
                    pdf_file, excel_file, client
                )
            except Exception as e:
                st.error(f"Error during processing: {e}")
                return

        # ==============================================================
        # 2️⃣ Invoice Summary (with quantities, refs, accuracy)
        # ==============================================================
        st.subheader("2️⃣ Invoice Summary")

        cgst = invoice_summary.get("ocr_cgst_total") or 0
        sgst = invoice_summary.get("ocr_sgst_total") or 0
        cgst_sgst_total = cgst + sgst

        ocr_qty = invoice_summary.get("ocr_total_qty")
        excel_qty = invoice_summary.get("excel_total_qty")
        ocr_total = invoice_summary.get("ocr_invoice_total_num")
        excel_total_val = invoice_summary.get("excel_total_value_sum")

        qty_accuracy = None
        if excel_qty not in (None, 0):
            qty_accuracy = max(
                0.0,
                1.0 - abs((ocr_qty or 0.0) - excel_qty) / abs(excel_qty),
            ) * 100.0

        amt_accuracy = None
        if excel_total_val not in (None, 0):
            amt_accuracy = max(
                0.0,
                1.0 - abs((ocr_total or 0.0) - excel_total_val) / abs(excel_total_val),
            ) * 100.0

        summary_row = {
            "Your Reference (PDF)": invoice_summary.get("ocr_invoice_ref"),
            "PO Ref No (Excel)": invoice_summary.get("excel_po_ref"),
            "Quantity (PDF)": ocr_qty,
            "Quantity (Excel)": excel_qty,
            "CGST + SGST (OCR)": cgst_sgst_total,
            "OCR Invoice Total": ocr_total,
            "Calculated Total (Subtotal + CGST + SGST)": invoice_summary.get(
                "ocr_calculated_total"
            ),
            "Excel Included Tax Sum": invoice_summary.get("excel_included_tax_sum"),
            "Excel Total Value Sum": excel_total_val,
            "Quantity Accuracy (%)": qty_accuracy,
            "Amount Accuracy (%)": amt_accuracy,
        }

        cols_order = list(summary_row.keys())
        summary_df = pd.DataFrame([summary_row])

        # Pretty formatting
        summary_display = summary_df.copy()
        for col in [
            "Quantity (PDF)",
            "Quantity (Excel)",
            "CGST + SGST (OCR)",
            "OCR Invoice Total",
            "Calculated Total (Subtotal + CGST + SGST)",
            "Excel Included Tax Sum",
            "Excel Total Value Sum",
        ]:
            if col in summary_display.columns:
                summary_display[col] = summary_display[col].apply(
                    lambda x: f"{x:,.2f}" if pd.notna(x) else ""
                )

        for col in ["Quantity Accuracy (%)", "Amount Accuracy (%)"]:
            if col in summary_display.columns:
                summary_display[col] = summary_display[col].apply(
                    lambda x: f"{x:.2f}%" if pd.notna(x) else ""
                )

        st.table(summary_display[cols_order])

        # ==============================================================
        # 3️⃣ Downloads – summary only
        # ==============================================================
        st.markdown("---")
        st.subheader("3️⃣ Downloads")

        excel_report_bytes = save_summary_to_excel_bytes(summary_row, cols_order)

        # Save to MongoDB
        try:
             # This uses the fixed common.mongo utility
             save_reconciliation_report(
                collection_name="dyson_reconciliation",
                invoice_no=summary_row.get("Your Reference (PDF)", "Unknown"),
                summary_data=summary_df,
                line_items_data=df_comp,
                metadata={
                    "invoice_file": pdf_file.name,
                    "excel_file": excel_file.name,
                    "accuracy": accuracy
                }
            )
        except Exception as e:
            logger.warning(f"Auto-save error: {e}")

        # Standardized download section
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            download_module_report(
                df=df_comp,
                module_name="reconciliation",
                report_name=f"Dyson_Detailed_{invoice_summary.get('ocr_invoice_ref')}",
                button_label="📥 Download Detailed Report",
                key="dl_dyson_detailed"
            )
        with col_dl2:
            download_module_report(
                df=summary_df,
                module_name="reconciliation",
                report_name=f"Dyson_Summary_{invoice_summary.get('ocr_invoice_ref')}",
                button_label="📥 Download Summary",
                key="dl_dyson_summary"
            )

        if show_raw_json:
            st.markdown("---")
            st.subheader("🔍 Raw Azure Invoice JSON (debug)")
            st.json(raw_doc_dict)


if __name__ == "__main__":
    main()
