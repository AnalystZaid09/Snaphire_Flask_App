# ============================================================
# USHA Invoice ↔ Amazon PO Reconciliation
# FINAL STABLE VERSION (Azure prebuilt-invoice)
# AZURE CREDENTIALS HIDDEN (ENV ONLY)
# ============================================================

import os
import io
import pandas as pd
import streamlit as st
from difflib import SequenceMatcher
from dotenv import load_dotenv
from common.mongo import save_reconciliation_report
from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report
)

MODULE_NAME = "reconciliation"

from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

# ============================================================
# ENV (SECURE)
# ============================================================

load_dotenv()

AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY")

if not AZURE_ENDPOINT or not AZURE_KEY:
    raise RuntimeError(
        "AZURE_ENDPOINT or AZURE_KEY not found in environment variables"
    )

# ============================================================
# AZURE FIELD HELPERS (CRITICAL)
# ============================================================

def field_text(field):
    if field is None:
        return ""
    return field.content or ""

def field_number(field):
    if field is None:
        return 0.0
    if getattr(field, "value_number", None) is not None:
        return float(field.value_number)
    if getattr(field, "value_currency", None) is not None:
        return float(field.value_currency.amount)
    return 0.0

def safe_tax_amount(t):
    obj = getattr(t, "value_object", None)
    if not obj:
        return 0.0
    amt = obj.get("Amount")
    if not amt:
        return 0.0
    return field_number(amt)

# ============================================================
# TEXT HELPERS
# ============================================================

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalize_key(text):
    stop = {
        "usha","with","and","of","nos","pc","pcs",
        "manual","sewing","machine","electric"
    }
    return " ".join(sorted(set(w for w in text.lower().split() if w not in stop)))

# ============================================================
# AZURE INVOICE EXTRACTION (BOTH INVOICE TYPES)
# ============================================================

def extract_invoice(pdf_bytes):

    client = DocumentIntelligenceClient(
        endpoint=AZURE_ENDPOINT,
        credential=AzureKeyCredential(AZURE_KEY)
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-invoice",
        body=io.BytesIO(pdf_bytes)
    )

    result = poller.result()
    doc = result.documents[0]
    fields = doc.fields

    # ---------------- ITEMS ----------------
    items = []
    items_field = fields.get("Items")

    if items_field and items_field.value_array:
        for item in items_field.value_array:
            obj = item.value_object or {}

            items.append({
                "description": field_text(obj.get("Description")),
                "hsn": field_text(obj.get("ProductCode")),
                "qty": field_number(obj.get("Quantity")),
                "unit_price": field_number(obj.get("UnitPrice")),
                "line_total": field_number(obj.get("Amount"))
            })

    # ---------------- TAX ----------------
    tax = {
        "central": 0.0,
        "state": 0.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 0.0
    }

    tax_field = fields.get("TaxDetails")
    if tax_field and tax_field.value_array:
        for t in tax_field.value_array:
            name = (t.content or "").lower()
            amt = safe_tax_amount(t)
            if amt == 0:
                continue

            if "central" in name:
                tax["central"] += amt
            elif "state" in name:
                tax["state"] += amt
            elif "cgst" in name:
                tax["cgst"] += amt
            elif "sgst" in name:
                tax["sgst"] += amt
            elif "igst" in name:
                tax["igst"] += amt

    tax["total"] = round(sum(tax.values()), 2)

    invoice_total = field_number(fields.get("InvoiceTotal"))

    return {
        "items": items,
        "tax": tax,
        "invoice_total": invoice_total
    }

# ============================================================
# PO EXCEL LOADER (AMAZON FORMAT)
# ============================================================

def load_po_excel(file):

    raw = pd.read_excel(file, header=None, dtype=object)

    header_row = next(
        i for i in range(len(raw))
        if raw.iloc[i].astype(str).str.contains("SKU", case=False).any()
    )

    df = raw.iloc[header_row+1:].copy()
    df.columns = raw.iloc[header_row]
    df = df.dropna(how="all")

    def to_num(s):
        return pd.to_numeric(
            s.astype(str).str.replace(r"[^\d.\-]", "", regex=True),
            errors="coerce"
        ).fillna(0)

    po = pd.DataFrame()
    po["SKU"] = df["SKU"].astype(str)
    po["Name"] = df["Name"].astype(str)
    po["qty_po"] = to_num(df["Ordered Quantity"])
    po["unit_price_po"] = to_num(df["Item Price"])
    po["line_total_po"] = to_num(df["Total Value"])
    po["included_tax_po"] = to_num(df["Included Tax"])
    po["key"] = po["Name"].apply(normalize_key)

    return po

# ============================================================
# LINE-LEVEL RECONCILIATION
# ============================================================

def reconcile(inv_items, po_df):

    rows = []

    for it in inv_items:
        key = normalize_key(it["description"])
        po_df["score"] = po_df["key"].apply(lambda x: similarity(key, x))
        best = po_df.sort_values("score", ascending=False).iloc[0]

        rows.append({
            "description": it["description"],
            "hsn": it["hsn"],
            "qty_inv": it["qty"],
            "unit_price_inv": it["unit_price"],
            "line_total_inv": it["line_total"],
            "SKU": best["SKU"],
            "PO Name": best["Name"],
            "qty_po": best["qty_po"],
            "unit_price_po": best["unit_price_po"],
            "line_total_po": best["line_total_po"],
            "match_score": round(best["score"], 3),
            "qty_match": it["qty"] == best["qty_po"],
            "price_match": round(it["unit_price"], 2) == round(best["unit_price_po"], 2)
        })

    return pd.DataFrame(rows)

# ============================================================
# EXCEL DOWNLOAD
# ============================================================

def build_reconciliation_excel(comp_df, invoice, po_df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        comp_df.to_excel(
            writer,
            index=False,
            sheet_name="Line_Level_Reconciliation"
        )

        summary_rows = [
            ["Central Tax", invoice["tax"]["central"], None, None],
            ["State Tax", invoice["tax"]["state"], None, None],
            ["CGST", invoice["tax"]["cgst"], None, None],
            ["SGST", invoice["tax"]["sgst"], None, None],
            [
                "Invoice GST Total",
                invoice["tax"]["total"],
                po_df["included_tax_po"].sum(),
                invoice["tax"]["total"] - po_df["included_tax_po"].sum()
            ],
            [
                "Total Invoice Value",
                invoice["invoice_total"],
                po_df["line_total_po"].sum(),
                invoice["invoice_total"] - po_df["line_total_po"].sum()
            ],
        ]

        summary_df = pd.DataFrame(
            summary_rows,
            columns=["Metric", "Invoice", "PO", "Difference"]
        )

        summary_df.to_excel(
            writer,
            index=False,
            sheet_name="Financial_Summary"
        )

    output.seek(0)
    return output

# ============================================================
# STREAMLIT UI
# ============================================================

# Apply Professional UI
apply_professional_style()
render_header("Usha Invoice Reconciliation", "PDF Invoice vs Excel PO")
pdfs = st.file_uploader("Upload Invoice PDFs", type="pdf", accept_multiple_files=True)
po_file = st.file_uploader("Upload PO Excel", type="xlsx")

if st.button("Run Reconciliation"):

    if not pdfs or po_file is None:
        st.error("❌ Upload invoice PDFs and PO Excel")
        st.stop()

    po_df = load_po_excel(po_file)

    for pdf in pdfs:
        st.subheader(pdf.name)

        invoice = extract_invoice(pdf.read())

        comp_df = reconcile(invoice["items"], po_df)

        st.subheader("Line-level Comparison")
        st.dataframe(comp_df, use_container_width=True)

        st.subheader("Financial Summary")
        st.json({
            "Central Tax": invoice["tax"]["central"],
            "State Tax": invoice["tax"]["state"],
            "CGST": invoice["tax"]["cgst"],
            "SGST": invoice["tax"]["sgst"],
            "Invoice GST Total": invoice["tax"]["total"],
            "PO Included Tax": po_df["included_tax_po"].sum(),
            "GST Difference": round(invoice["tax"]["total"] - po_df["included_tax_po"].sum(), 2),
            "Invoice Total": invoice["invoice_total"],
            "PO Total Value": po_df["line_total_po"].sum(),
            "Grand Total Difference": round(invoice["invoice_total"] - po_df["line_total_po"].sum(), 2)
        })

        excel = build_reconciliation_excel(comp_df, invoice, po_df)
        st.download_button(
            label="📥 Download Excel Report",
            data=excel.getvalue(),
            file_name=get_download_filename(f"reconciliation_{pdf.name.replace('.pdf','')}.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Save to MongoDB
        try:
            # Reconstruct invoice_no if possible, else use default or filename
            # Usha script doesn't explicitly extract an Invoice ID in the 'invoice' dict, 
            # so we'll try to find it in the raw fields if we have access, 
            # but extract_invoice only returns items, tax, total.
            # We'll use "Unknown" or maybe add extraction if critical.
            # Given the current structure, let's use the PDF filename as a fallback identifier or just "N/A"
            # Metadata is good place for filename.
            
             save_reconciliation_report(
                collection_name="usha_reconciliation",
                invoice_no="N/A", # Script does not extract Invoice Number
                summary_data=pd.DataFrame([
                    {"Metric": "Invoice_Total", "Value": invoice["invoice_total"]},
                    {"Metric": "PO_Total", "Value": po_df["line_total_po"].sum()},
                     {"Metric": "GST_Diff", "Value": round(invoice["tax"]["total"] - po_df["included_tax_po"].sum(), 2)}
                ]),
                line_items_data=comp_df,
                metadata={
                    "file_name_pdf": pdf.name,
                    "file_name_excel": po_file.name,
                    "timestamp": str(pd.Timestamp.now())
                }
            )
        except Exception as e:
            st.error(f"Failed to auto-save to MongoDB: {e}")
