import os
import re
import json
import tempfile
from io import BytesIO
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any
from pprint import pprint
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "reconciliation"

import streamlit as st
import pandas as pd
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

# ---------------------------
# Load .env (hidden credentials)
# ---------------------------
load_dotenv()  # loads .env in current dir
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT") or os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY") or os.getenv("AZURE_DOC_KEY")

# ---------------------------
# Streamlit page config
# ---------------------------# Apply Professional UI
apply_professional_style()

def main():
    st.set_page_config(page_title="Sujata Reconciliation", layout="wide")
    render_header("Sujata Reconciliation Tool", "PDF Invoice vs Excel (With Fuzzy Matching for Descriptions)")

    # session state
    if "report" not in st.session_state:
        st.session_state.report = None
    if "pdf_data" not in st.session_state:
        st.session_state.pdf_data = None
    if "excel_rows" not in st.session_state:
        st.session_state.excel_rows = None

    NUMERIC_TOLERANCE = 0.5

    # ---------------------------
    # Helpers: numerics, normalization
    # ---------------------------
    def parse_decimal_token(s):
        if s is None:
            return None
        s = str(s).strip()
        if s == "":
            return None
        # parentheses -> negative
        is_neg = "(" in s and ")" in s
        s = s.replace("(", "").replace(")", "")
        # remove non digits/dot/minus
        s = re.sub(r"[^\d\.\-]", "", s)
        if s in ("", "-", "."):
            return None
        try:
            v = float(Decimal(s))
        except Exception:
            try:
                v = float(s)
            except Exception:
                return None
        return -v if is_neg else v

    def to_float_safe(val):
        # For converting Excel-like cells: preserve text if it contains letters.
        if pd.isna(val):
            return None
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        s = str(val).strip()
        if s == "":
            return None
        if re.search(r"[A-Za-z]", s):
            return s
        # parentheses means negative
        is_neg = "(" in s and ")" in s
        s_clean = s.replace("(", "").replace(")", "")
        s_clean = re.sub(r"[^\d\.\-]", "", s_clean)
        if s_clean in ("", "-", "."):
            return s
        try:
            v = float(Decimal(s_clean))
        except Exception:
            try:
                v = float(s_clean)
            except Exception:
                return s
        return -v if is_neg else v

    def normalize_words(s: str) -> List[str]:
        if s is None:
            return []
        s = str(s).upper()
        # remove punctuation except spaces
        s = re.sub(r"[^A-Z0-9\s]", " ", s)
        words = [w.strip() for w in s.split() if w.strip()]
        return words

    def start_word(s: str) -> str:
        words = normalize_words(s)
        return words[0].lower() if words else None

    def description_matches(pdf_desc: str, excel_name: str) -> bool:
        """
        Consider match if:
        - First significant word matches; OR
        - At least two overlapping normalized words (ignoring common stopwords)
        """
        if not pdf_desc or not excel_name:
            return False
        pdf_words = normalize_words(pdf_desc)
        excel_words = normalize_words(excel_name)
        if not pdf_words or not excel_words:
            return False
        # quick check: first word match
        if pdf_words[0] == excel_words[0]:
            return True
        # remove short stop words (1-2 char) and some common words
        stop = {"THE","AND","WITH","NOS","NO","SET","KG","PCS","PER","IN","OF","W"}
        pdf_set = [w for w in pdf_words if w not in stop and len(w)>1]
        excel_set = [w for w in excel_words if w not in stop and len(w)>1]
        # compute overlap
        overlap = set(pdf_set) & set(excel_set)
        if len(overlap) >= 2:
            return True
        # fallback: if first two words of excel name appear in pdf (sequence)
        seq = " ".join(excel_words[:2])
        if seq and seq in " ".join(pdf_words):
            return True
        # another fallback: check approximate substring match (one of top words from excel in pdf)
        for w in excel_set[:3]:
            if w in pdf_words:
                return True
        return False

    def is_close(a, b, tol=NUMERIC_TOLERANCE):
        if a is None or b is None:
            return False
        try:
            return abs(float(a) - float(b)) <= tol
        except Exception:
            return False

    # ---------------------------
    # Azure PDF extraction (prebuilt-invoice)
    # ---------------------------
    def build_full_text(result) -> str:
        parts = []
        if hasattr(result, "content") and result.content:
            parts.append(result.content)
        if getattr(result, "pages", None):
            for p in result.pages:
                for ln in getattr(p, "lines", []) or []:
                    if getattr(ln, "content", None):
                        parts.append(ln.content)
        if getattr(result, "documents", None):
            for d in getattr(result, "documents") or []:
                if getattr(d, "content", None):
                    parts.append(d.content)
        return "\n".join([p for p in parts if p])

    # Strict line regex tailored to your screenshots (HSN + qty + rates + amount)
    item_line_re = re.compile(
        r"""
        (?P<description>.+?)\s+
        (?P<hsn>\b[0-9]{6,8}\b)
        [^\d\n\r]*
        (?P<qty>\d{1,6})\s*(?:NOS|No|PCS|NOS\.)?
        [^\d\n\r]*
        (?P<rate_incl>[0-9,]+\.\d{2})
        [^\d\n\r]*
        (?P<rate_excl>[0-9,]+\.\d{2})
        [^\d\n\r]*
        (?P<amount>[0-9,]+\.\d{2})
        """,
        flags=re.I | re.X
    )

    def extract_items_strict(full_text: str) -> List[Dict[str,Any]]:
        items = []
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        for idx, ln in enumerate(lines):
            m = item_line_re.search(ln)
            if not m:
                window = " ".join(lines[idx: idx+4])
                m = item_line_re.search(window)
            if not m:
                continue
            desc = re.sub(r"\s+", " ", m.group("description")).strip()
            hsn = m.group("hsn").strip()
            qty = int(m.group("qty")) if m.group("qty") else None
            rate_incl = parse_decimal_token(m.group("rate_incl"))
            rate_excl = parse_decimal_token(m.group("rate_excl"))
            amount = parse_decimal_token(m.group("amount"))
            qty_x_rate = round(qty * rate_excl, 2) if (qty is not None and rate_excl is not None) else None
            items.append({
                "Description": desc,
                "HSN": hsn,
                "Qty": qty,
                "RateInclTax": rate_incl,
                "RateExclTax": rate_excl,
                "Amount": amount,
                "Qty_x_Rate": qty_x_rate
            })
        return items

    def extract_items_hsn_window(full_text: str) -> List[Dict[str,Any]]:
        lines = [ln.rstrip() for ln in full_text.splitlines()]
        items = []
        hsn_re = re.compile(r"\b([0-9]{6,8})\b")
        seen = set()
        for i, ln in enumerate(lines):
            for m in hsn_re.finditer(ln):
                hsn = m.group(1)
                # description candidates above
                desc_candidates = []
                for back in range(1,9):
                    j = i - back
                    if j < 0: break
                    cand = lines[j].strip()
                    if cand and not re.search(r"(invoice|gstin|total|tax|round|signature|buyer|consignee)", cand, re.I):
                        desc_candidates.insert(0, cand)
                description = " ".join(desc_candidates).strip() if desc_candidates else None
                window = " ".join(lines[i:i+9])
                qty = None
                q = re.search(r"\b(\d{1,6})\s*(NOS|No|PCS)?\b", window, re.I)
                if q:
                    try:
                        qty_v = int(q.group(1))
                        if 1 <= qty_v <= 100000:
                            qty = qty_v
                    except:
                        qty = None
                decimals = re.findall(r"[0-9,]+\.\d{2}", window)
                dec_vals = [parse_decimal_token(d) for d in decimals if parse_decimal_token(d) is not None]
                amount = None
                rate = None
                if dec_vals:
                    if qty:
                        amount = max(dec_vals)
                        candidate_rate = round(amount/qty, 2) if qty else None
                        if candidate_rate:
                            nearest = min(dec_vals, key=lambda x: abs(x - candidate_rate))
                            rate = nearest
                    else:
                        dec_sorted = sorted(dec_vals, reverse=True)
                        amount = dec_sorted[0]
                        rate = dec_sorted[1] if len(dec_sorted)>1 else None
                qty_x_rate = round(qty*rate,2) if (qty and rate) else None
                key = (hsn, qty, amount)
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    "Description": description,
                    "HSN": hsn,
                    "Qty": qty,
                    "RateExclTax": rate,
                    "Amount": amount,
                    "Qty_x_Rate": qty_x_rate
                })
        return items

    def extract_totals(full_text: str) -> Dict[str,Any]:
        totals = {
            "TaxableValue": None,
            "CGST_total": None,
            "SGST_total": None,
            "IGST_total": None,
            "Tax_Total": None,
            "Round_off": None,
            "GrandTotal": None,
            "TotalTaxAmount": None
        }
        m = re.search(r"(Taxable\s*Value|SubTotal)\s*[:\-\s]*([0-9,]+\.\d{2})", full_text, re.I)
        if m: totals["TaxableValue"] = parse_decimal_token(m.group(2))
        cg = re.search(r"CGST\s*[:\-\s]*([0-9,]+\.\d{2})", full_text, re.I)
        sg = re.search(r"SGST\s*[:\-\s]*([0-9,]+\.\d{2})", full_text, re.I)
        ig = re.search(r"IGST\s*[:\-\s]*([0-9,]+\.\d{2})", full_text, re.I)
        if cg: totals["CGST_total"] = parse_decimal_token(cg.group(1))
        if sg: totals["SGST_total"] = parse_decimal_token(sg.group(1))
        if ig: totals["IGST_total"] = parse_decimal_token(ig.group(1))
        ro = re.search(r"ROUND\s*OFF\s*[:\-\s]*([\-\(]?[0-9,]+\.\d{2}\)?)", full_text, re.I)
        if ro:
            val = ro.group(1).replace("(", "-").replace(")", "")
            totals["Round_off"] = parse_decimal_token(val)
        gt = re.search(r"(Grand\s*Total|Grand Total|Total)[^\d\n\r]{0,40}([₹]?\s*[0-9,]+\.\d{2})", full_text, re.I)
        if gt:
            totals["GrandTotal"] = parse_decimal_token(gt.group(2))
        else:
            matches = re.findall(r"₹\s*([0-9,]+\.\d{2})", full_text)
            if matches: totals["GrandTotal"] = parse_decimal_token(matches[-1])
        cg_v = totals.get("CGST_total") or 0.0
        sg_v = totals.get("SGST_total") or 0.0
        ig_v = totals.get("IGST_total") or 0.0
        tax_sum = round(cg_v + sg_v + ig_v, 2) if (cg_v or sg_v or ig_v) else None
        if tax_sum is not None:
            totals["Tax_Total"] = tax_sum
            totals["TotalTaxAmount"] = tax_sum
        else:
            tt = re.search(r"Total\s*Tax\s*Amount[^\d\n\r]*([0-9,]+\.\d{2})", full_text, re.I)
            if tt:
                totals["TotalTaxAmount"] = parse_decimal_token(tt.group(1))
                totals["Tax_Total"] = totals["TotalTaxAmount"]
        return totals

    def items_from_azure_doc_fields(result) -> List[Dict[str,Any]]:
        items = []
        if not getattr(result, "documents", None):
            return items
        doc = result.documents[0]
        fields = getattr(doc, "fields", {}) or {}
        arr = None
        for k in fields:
            if k.lower() == "items" or "item" in k.lower():
                arr = fields[k]
                break
        if arr is None:
            return items
        # try iterate arr.value
        try:
            val_array = getattr(arr, "value", None) or getattr(arr, "valueArray", None) or None
            if val_array and hasattr(val_array, "__iter__"):
                for entry in val_array:
                    obj = getattr(entry, "valueObject", None) or getattr(entry, "value", None) or None
                    if obj and hasattr(obj, "items"):
                        props = {}
                        for name, fld in obj.items():
                            val = None
                            if getattr(fld, "valueString", None) is not None:
                                val = fld.valueString
                            elif getattr(fld, "valueNumber", None) is not None:
                                val = fld.valueNumber
                            elif getattr(fld, "valueCurrency", None):
                                val = getattr(fld, "valueCurrency").amount
                            elif getattr(fld, "content", None):
                                val = fld.content
                            props[name] = val
                        item = {
                            "Description": props.get("Description") or props.get("description") or props.get("Name") or None,
                            "HSN": props.get("ProductCode") or props.get("HSN") or None,
                            "Qty": int(props.get("Quantity")) if props.get("Quantity") is not None else None,
                            "RateInclTax": float(props.get("UnitPrice")) if props.get("UnitPrice") is not None else None,
                            "Amount": float(props.get("Amount")) if props.get("Amount") is not None else None,
                            "Qty_x_Rate": None
                        }
                        if item["Qty"] and item["RateInclTax"]:
                            item["Qty_x_Rate"] = round(item["Qty"] * item["RateInclTax"], 2)
                        items.append(item)
                    else:
                        content = getattr(entry, "content", None) or str(entry)
                        parsed = extract_items_strict(content)
                        if parsed:
                            items.extend(parsed)
            else:
                content = str(arr)
                parsed = extract_items_strict(content)
                if parsed:
                    items.extend(parsed)
        except Exception:
            pass
        return items

    def extract_pdf_bytes(pdf_file_bytes):
        # pdf_file_bytes is a BytesIO-like object from Streamlit uploader
        if not AZURE_ENDPOINT or not AZURE_KEY:
            raise RuntimeError("Azure credentials not found in .env (AZURE_ENDPOINT / AZURE_KEY).")
        # write to tmp file and call Azure
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf_file_bytes.read())
                tmp_path = tmp.name
            client = DocumentIntelligenceClient(endpoint=AZURE_ENDPOINT, credential=AzureKeyCredential(AZURE_KEY))
            with open(tmp_path, "rb") as fh:
                poller = client.begin_analyze_document(model_id="prebuilt-invoice", body=fh)
                result = poller.result()
            full_text = build_full_text(result)
            header = {}
            if getattr(result, "documents", None) and len(result.documents) > 0:
                doc = result.documents[0]
                for k, v in doc.fields.items():
                    try:
                        val = getattr(v, "value", None) or getattr(v, "content", None) or getattr(v, "valueString", None) or getattr(v, "valueNumber", None) or str(v)
                        header[k] = val
                    except Exception:
                        header[k] = None
            # try to fill vendor detection fallback
            if not header.get("VendorName"):
                m = re.search(r"(M\/s\s+[A-Za-z0-9 \&\.\-]+)", full_text, re.I)
                if m:
                    header["VendorName"] = m.group(1).strip()
            if header.get("InvoiceTotal") and isinstance(header.get("InvoiceTotal"), str):
                header["InvoiceTotal_parsed"] = parse_decimal_token(header["InvoiceTotal"])
            items = items_from_azure_doc_fields(result)
            if not items:
                items = extract_items_strict(full_text)
            if not items:
                items = extract_items_hsn_window(full_text)
            totals = extract_totals(full_text)
            if totals.get("GrandTotal") is None and header.get("InvoiceTotal_parsed") is not None:
                totals["GrandTotal"] = header.get("InvoiceTotal_parsed")
            if totals.get("TotalTaxAmount") is None:
                cg = totals.get("CGST_total") or 0.0
                sg = totals.get("SGST_total") or 0.0
                totals["TotalTaxAmount"] = round(cg + sg, 2) if (cg or sg) else None
            return {"header": header, "items": items, "totals": totals, "full_text": full_text}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # ---------------------------
    # Excel reading (row 2 as header)
    # ---------------------------
    def read_excel_row2_header(excel_file) -> Dict[str,List[Dict[str,Any]]]:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(excel_file.read())
                tmp_path = tmp.name
            sheets_json = {}
            with pd.ExcelFile(tmp_path) as xls:
                for sheet in xls.sheet_names:
                    df_raw = xls.parse(sheet, header=None, dtype=object)
                    if df_raw.shape[0] < 2:
                        df = xls.parse(sheet, header=0, dtype=object)
                        df_clean = df.applymap(lambda x: to_float_safe(x))
                    else:
                        header_row = df_raw.iloc[1].tolist()
                        new_cols = []
                        for i, h in enumerate(header_row):
                            if pd.isna(h):
                                new_cols.append(f"col_{i}")
                            else:
                                nh = str(h).strip()
                                nh = re.sub(r"\s+", " ", nh)
                                new_cols.append(nh)
                        df_data = df_raw.iloc[2:].copy()
                        df_data.columns = new_cols
                        df_data = df_data.reset_index(drop=True)
                        # forced text columns
                        text_columns = {"sku","name","ean/upc","image"}
                        def convert_cell(col, val):
                            if col.strip().lower() in text_columns:
                                if pd.isna(val):
                                    return None
                                return str(val).strip()
                            return to_float_safe(val)
                        df_clean = df_data.copy()
                        for col in df_clean.columns:
                            df_clean[col] = df_clean[col].apply(lambda v, c=col: convert_cell(c, v))
                    df_clean = df_clean.where(pd.notnull(df_clean), None)
                    records = df_clean.to_dict(orient="records")
                    sheets_json[sheet] = records
            return sheets_json
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # ---------------------------
    # Comparison logic
    # ---------------------------
    def find_excel_row_by_po(excel_rows, po_ref):
        if po_ref is None:
            return None
        tgt = str(po_ref).strip()
        for r in excel_rows:
            # try common keys
            v = r.get("PO Ref No") or r.get("PO Ref No.") or r.get("PO Ref") or r.get("PO Ref No")
            if v is None:
                for k in r.keys():
                    if k and k.strip().lower().startswith("po"):
                        v = r.get(k)
                        break
            if v is None:
                continue
            # numeric compare if possible
            a = parse_decimal_token(tgt)
            b = parse_decimal_token(v)
            if a is not None and b is not None:
                if is_close(a, b, tol=0.5):
                    return r
            else:
                if str(v).strip().lower() == str(tgt).strip().lower():
                    return r
        return None

    def filter_product_lines(items: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
        """Remove tax/GST-only lines from extracted items (CGST/SGST lines)."""
        filtered = []
        for it in items:
            desc = (it.get("Description") or "") if it else ""
            if not desc:
                # sometimes azure returns empty; include only if HSN/Qty/Amount present
                if it.get("HSN") and (it.get("Qty") or it.get("Amount")):
                    filtered.append(it)
                continue
            low = desc.lower()
            if any(x in low for x in ("cgst", "sgst", "igst", "tax", "round off", "roundoff", "total tax", "tax amount")):
                continue
            filtered.append(it)
        return filtered

    def compare_items(pdf_items, excel_rows):
        results = []
        matched = set()
        # build excel index by normalized starts and word sets
        excel_index_by_start = {}
        excel_word_sets = []
        for idx, row in enumerate(excel_rows):
            name = row.get("Name") or row.get("Product Name") or row.get("Name ")
            start = None
            if name:
                nw = normalize_words(name)
                start = nw[0] if nw else None
            if start:
                excel_index_by_start.setdefault(start, []).append(idx)
            excel_word_sets.append((idx, set(normalize_words(name))))
        # process pdf items (filter GST lines)
        pdf_items = filter_product_lines(pdf_items)
        for pdf_idx, pdf_item in enumerate(pdf_items):
            pdf_desc = pdf_item.get("Description") or pdf_item.get("description") or ""
            pdf_qty = parse_decimal_token(pdf_item.get("Qty"))
            rec = {
                "pdf_index": pdf_idx,
                "pdf_description": pdf_desc,
                "pdf_qty": pdf_qty,
                "matched_excel_index": None,
                "matched_excel_row": None,
                "description_match": False,
                "qty_match": False
            }
            # try start match
            pdf_start = None
            nw = normalize_words(pdf_desc)
            if nw:
                pdf_start = nw[0]
            chosen_idx = None
            if pdf_start and pdf_start in excel_index_by_start:
                for cand in excel_index_by_start[pdf_start]:
                    if cand not in matched:
                        chosen_idx = cand
                        break
                if chosen_idx is None:
                    chosen_idx = excel_index_by_start[pdf_start][0]
            # if not found, try word-set overlap with >=2 common words or description_matches function
            if chosen_idx is None:
                for idx, wset in excel_word_sets:
                    # skip already matched if possible
                    if idx in matched:
                        continue
                    # direct fuzzy function
                    excel_name = excel_rows[idx].get("Name")
                    if description_matches(pdf_desc, excel_name):
                        chosen_idx = idx
                        break
            if chosen_idx is not None:
                matched.add(chosen_idx)
                erec = excel_rows[chosen_idx]
                rec["matched_excel_index"] = chosen_idx
                rec["matched_excel_row"] = erec
                rec["description_match"] = description_matches(pdf_desc, erec.get("Name"))
                excel_qty = parse_decimal_token(erec.get("Ordered Quantity") or erec.get("OrderedQuantity") or erec.get("Ordered Qty"))
                rec["excel_ordered_qty"] = excel_qty
                rec["qty_match"] = is_close(pdf_qty, excel_qty, tol=0.5)
            results.append(rec)
        total_items = len(results)
        descr_matches = sum(1 for r in results if r["description_match"])
        qty_matches = sum(1 for r in results if r["qty_match"])
        descr_accuracy = round((descr_matches / total_items * 100) if total_items else 0.0, 2)
        qty_accuracy = round((qty_matches / total_items * 100) if total_items else 0.0, 2)
        return {"per_item": results, "summary": {
            "total_items": total_items,
            "description_start_matches": descr_matches,
            "qty_matches": qty_matches,
            "description_start_accuracy_pct": descr_accuracy,
            "qty_accuracy_pct": qty_accuracy
        }}

    def compare_pdf_and_excel(pdf_obj, excel_rows):
        header = pdf_obj.get("header", {})
        pdf_items = pdf_obj.get("items", []) or []
        totals = pdf_obj.get("totals", {}) or {}
        pdf_invoice_id = header.get("InvoiceId") or header.get("invoice_id") or header.get("Invoice Number")
        matched_excel_row = find_excel_row_by_po(excel_rows, pdf_invoice_id)
        header_po_match = False
        if matched_excel_row:
            # do a best-effort compare (string or numeric)
            a = str(pdf_invoice_id).strip().lower() if pdf_invoice_id else None
            b = str(matched_excel_row.get("PO Ref No") or matched_excel_row.get("PO Ref No.") or matched_excel_row.get("PO Ref") or "").strip().lower()
            header_po_match = (a == b)
        # totals compare
        excelsrc = matched_excel_row if matched_excel_row else (excel_rows[0] if excel_rows else None)
        total_match = False
        tax_match = False
        pdf_total_val = parse_decimal_token(header.get("InvoiceTotal_parsed") or header.get("InvoiceTotal") or totals.get("GrandTotal"))
        excel_total_val = parse_decimal_token(excelsrc.get("Total Value") if excelsrc else None)
        if pdf_total_val is not None and excel_total_val is not None:
            total_match = is_close(pdf_total_val, excel_total_val, tol=1.0)
        # tax
        pdf_tax = None
        if header.get("TotalTaxAmount") is not None:
            pdf_tax = parse_decimal_token(header.get("TotalTaxAmount"))
        else:
            pdf_tax = parse_decimal_token(totals.get("TotalTaxAmount") or totals.get("Tax_Total"))
        excel_tax = parse_decimal_token(excelsrc.get("Included Tax") if excelsrc else None)
        if pdf_tax is not None and excel_tax is not None:
            tax_match = is_close(pdf_tax, excel_tax, tol=1.0)
        # items compare
        items_comp = compare_items(pdf_items, excel_rows)
        report = {
            "header": {
                "pdf_invoice_id": pdf_invoice_id,
                "matched_excel_row_for_po": matched_excel_row,
                "invoiceid_vs_po_match": header_po_match
            },
            "totals": {
                "pdf_total_value": pdf_total_val,
                "excel_total_value": excel_total_val,
                "total_match": total_match,
                "pdf_tax": pdf_tax,
                "excel_tax": excel_tax,
                "tax_match": tax_match
            },
            "items": items_comp
        }
        # accuracy overall
        # compute overall accuracy as average of total_match(1/0), tax_match, qty_accuracy (percent/100)
        score_components = []
        score_components.append(1.0 if total_match else 0.0)
        score_components.append(1.0 if tax_match else 0.0)
        score_components.append((items_comp["summary"]["qty_accuracy_pct"] or 0.0) / 100.0)
        overall_accuracy = round(sum(score_components) / len(score_components) * 100, 2) if score_components else 0.0
        report["overall_accuracy_pct"] = overall_accuracy
        return report

    # ---------------------------
    # Build excel bytes for download (report + items)
    # ---------------------------
    def build_excel_bytes(report, pdf_data, excel_rows):
        out = BytesIO()
        # prepare dataframes
        header_df = pd.DataFrame([{
            "PDF Invoice ID": report["header"]["pdf_invoice_id"],
            "InvoiceID_vs_PO_match": report["header"]["invoiceid_vs_po_match"],
            "PDF Total": report["totals"]["pdf_total_value"],
            "Excel Total": report["totals"]["excel_total_value"],
            "Total Match": report["totals"]["total_match"],
            "PDF Tax": report["totals"]["pdf_tax"],
            "Excel Tax": report["totals"]["excel_tax"],
            "Tax Match": report["totals"]["tax_match"],
            "Overall Accuracy (%)": report["overall_accuracy_pct"]
        }])
        items_rows = []
        for it in report["items"]["per_item"]:
            matched = it.get("matched_excel_row") or {}
            items_rows.append({
                "PDF_Index": it["pdf_index"],
                "PDF_Description": it["pdf_description"],
                "PDF_Qty": it["pdf_qty"],
                "Excel_Name": matched.get("Name") if matched else None,
                "Excel_Ordered_Qty": it.get("excel_ordered_qty"),
                "Description_Match": it["description_match"],
                "Qty_Match": it["qty_match"]
            })
        items_df = pd.DataFrame(items_rows)
        excel_df = pd.DataFrame(excel_rows) if excel_rows else pd.DataFrame()
        # write to excel using context manager
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            header_df.to_excel(writer, sheet_name="summary", index=False)
            items_df.to_excel(writer, sheet_name="item_comparison", index=False)
            excel_df.to_excel(writer, sheet_name="excel_po", index=False)
            # writer closed automatically
        out.seek(0)
        return out.getvalue()

    # ---------------------------
    # Streamlit UI
    # ---------------------------
    st.title("📄 SujataInvoice Reconciliation")

    st.markdown("""
    Upload invoice PDF and Excel PO. Azure credentials are read from `.env` (hidden).
    Required .env keys: AZURE_ENDPOINT, AZURE_KEY
    """)

    col1, col2 = st.columns(2)
    with col1:
        pdf_file = st.file_uploader("Upload PDF invoice", type=["pdf"])
    with col2:
        excel_file = st.file_uploader("Upload Excel PO (xlsx)", type=["xlsx", "xls"])

    # show warning if credentials missing
    if not AZURE_ENDPOINT or not AZURE_KEY:
        st.warning("Azure credentials NOT found in `.env`. Please add AZURE_ENDPOINT and AZURE_KEY. The app will not call Azure without them.")

    if st.button("🔍 Reconcile", disabled=not (pdf_file and excel_file and AZURE_ENDPOINT and AZURE_KEY)):
        try:
            with st.spinner("Extracting PDF..."):
                pdf_data = extract_pdf_bytes(pdf_file)
            st.success("PDF extracted")
            st.session_state.pdf_data = pdf_data
            st.write("Preview (header):")
            st.json(pdf_data["header"])
            # read excel
            with st.spinner("Reading Excel..."):
                excel_sheets = read_excel_row2_header(excel_file)
                first_sheet = list(excel_sheets.keys())[0]
                excel_rows = excel_sheets[first_sheet]
            st.success("Excel loaded")
            st.session_state.excel_rows = excel_rows
            # Compare
            with st.spinner("Comparing..."):
                report = compare_pdf_and_excel(pdf_data, excel_rows)
            st.session_state.report = report
            st.success("Comparison done")

        except Exception as e:
            st.error(f"Error: {e}")
            logger.error(f"Reconciliation error: {e}")

    # Show report if available
    if st.session_state.report:
        report = st.session_state.report
        st.markdown("---")
        st.header("📊 Sujata Reconciliation Report")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Invoice ID Match", "✅" if report["header"]["invoiceid_vs_po_match"] else "❌", report["header"]["pdf_invoice_id"])
        with col2:
            st.metric("Total Match", "✅" if report["totals"]["total_match"] else "❌",
                      f"PDF ₹{report['totals']['pdf_total_value']:,.2f}" if report['totals']['pdf_total_value'] else "N/A")
        with col3:
            st.metric("Tax Match", "✅" if report["totals"]["tax_match"] else "❌",
                      f"PDF ₹{report['totals']['pdf_tax']:,.2f}" if report['totals']['pdf_tax'] else "N/A")
        with col4:
            s = report["items"]["summary"]
            st.metric("Item Qty Match", f"{s['qty_accuracy_pct']}%", f"{s['qty_matches']}/{s['total_items']} qty matched")

        st.markdown("### Item comparisons")
        s = report["items"]["summary"]
        st.write(f"Total items: {s['total_items']} — Description accuracy: {s['description_start_accuracy_pct']}% — Qty accuracy: {s['qty_accuracy_pct']}%")
        
        rows = []
        if report["items"]["per_item"]:
            for item in report["items"]["per_item"]:
                rows.append({
                    "PDF Description": item["pdf_description"],
                    "PDF Qty": item["pdf_qty"],
                    "Excel Name": item.get("matched_excel_row", {}).get("Name") if item.get("matched_excel_row") else None,
                    "Excel Ordered Qty": item.get("excel_ordered_qty"),
                    "Description Match": item["description_match"],
                    "Qty Match": item["qty_match"]
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        # Standardized download section
        st.markdown("---")
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            download_module_report(
                df=pd.DataFrame(rows),
                module_name="reconciliation",
                report_name=f"Sujata_Detailed_{report['header']['pdf_invoice_id']}",
                button_label="📥 Download Detailed Report",
                key="dl_sujata_detailed"
            )
        with col_dl2:
            download_module_report(
                df=pd.DataFrame([report["totals"]]),
                module_name="reconciliation",
                report_name=f"Sujata_Summary_{report['header']['pdf_invoice_id']}",
                button_label="📥 Download Summary",
                key="dl_sujata_summary"
            )

# Always call main for Streamlit execution
main()

