import streamlit as st
import pandas as pd
from io import BytesIO

# --------------------------------------------------
# Page config
# --------------------------------------------------
from mongo_utils import save_reconciliation_report
from ui_utils import apply_professional_style, get_download_filename, render_header
from datetime import datetime

# --------------------------------------------------
# Page config
# --------------------------------------------------
st.set_page_config(page_title="Order Analysis Dashboard", layout="wide")
apply_professional_style()

render_header("Order Analysis Dashboard")

# --------------------------------------------------
# Upload files
# --------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    orders_file = st.file_uploader("Upload Orders File", type=["xlsx"])
with c2:
    pm_file = st.file_uploader("Upload Product Master File", type=["xlsx"])

# --------------------------------------------------
# Generate button
# --------------------------------------------------
if st.button("🚀 Generate Analysis"):

    if orders_file is None or pm_file is None:
        st.error("Please upload both files")
        st.stop()

    # --------------------------------------------------
    # Load data
    # --------------------------------------------------
    Working = pd.read_excel(orders_file)
    pm = pd.read_excel(pm_file)

    # --------------------------------------------------
    # Cleaning
    # --------------------------------------------------
    Working.columns = Working.columns.str.strip().str.lower()
    pm.columns = pm.columns.str.strip().str.lower()

    Working["date"] = pd.to_datetime(Working["purchase-date"]).dt.date
    Working["asin"] = Working["asin"].astype(str).str.strip()
    pm["asin"] = pm["asin"].astype(str).str.strip()

    pm_unique = pm.drop_duplicates("asin")

    # --------------------------------------------------
    # Mapping
    # --------------------------------------------------
    bm_col = [c for c in pm.columns if "brand" in c and "manager" in c][0]

    Working["Brand"] = Working["asin"].map(pm_unique.set_index("asin")["brand"])
    Working["Brand Manager"] = Working["asin"].map(
        pm_unique.set_index("asin")[bm_col]
    )

    Working["cost"] = pd.to_numeric(
        Working["asin"].map(pm_unique.set_index("asin")["cp"]),
        errors="coerce"
    ).fillna(0)
    
    vendor_sku_col = pm_unique.columns[3]  # Excel column 4

    Working["Vendor SKU"] = Working["asin"].map(
        pm_unique.set_index("asin")[vendor_sku_col]
    )
    
    # --------------------------------------------------
    # FORCE NUMERIC COLUMNS (VERY IMPORTANT)
    # --------------------------------------------------
    num_cols = ["quantity", "item-price", "cost"]

    for col in num_cols:
        Working[col] = pd.to_numeric(Working[col], errors="coerce").fillna(0)


    # --------------------------------------------------
    # Filters
    # --------------------------------------------------
    Working = Working[
        (Working["quantity"] != 0) &
        (Working["item-price"] != 0) &
        (Working["item-status"] != "Cancelled")
    ]
    
    Working[num_cols] = Working[num_cols].fillna(0)

    for col in Working.columns:
        if Working[col].dtype == "object":
            Working[col] = Working[col].astype(str)
            
    # --------------------------------------------------
    # Tabs
    # --------------------------------------------------
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Brand Manager Analysis",
        "Brand Analysis",
        "Brand & ASIN Summary",
        "BM / Brand / ASIN Summary",
        "📊 Summary Pivots",
        "🧾 Raw Data"
    ])
    
    # Save to MongoDB
    try:
        with st.spinner("Saving Raw Data to DB..."):
            save_reconciliation_report(
                collection_name="amazon_sales_analysis",
                invoice_no=f"SalesAnalysis_{datetime.now().strftime('%Y%m%d%H%M')}",
                summary_data=pd.DataFrame(),
                line_items_data=Working,
                metadata={"type": "sales_analysis", "records": len(Working)}
            )
    except Exception as e:
        pass

    # ==================================================
    # TAB 1 – BRAND MANAGER ANALYSIS (DATE WISE + GRAND TOTAL)
    # ==================================================
    with tab1:
        pivot_bm = pd.pivot_table(
            Working,
            index="Brand Manager",
            columns="date",
            values=["quantity", "item-price", "cost"],
            aggfunc="sum",
            fill_value=0
        )

        pivot_bm = pivot_bm.swaplevel(0, 1, axis=1).sort_index(axis=1, level=0)
        pivot_bm.columns = pivot_bm.columns.map(
            lambda x: (x[0], f"Sum of {x[1]}")
        )

        # 🔥 RIGHT SIDE GRAND TOTAL (ROW-WISE, DATE BASED)
        pivot_bm[("Grand Total", "Total Sum of quantity")] = (
            pivot_bm.loc[:, pd.IndexSlice[:, "Sum of quantity"]].sum(axis=1)
        )
        pivot_bm[("Grand Total", "Total Sum of item-price")] = (
            pivot_bm.loc[:, pd.IndexSlice[:, "Sum of item-price"]].sum(axis=1)
        )
        pivot_bm[("Grand Total", "Total Sum of cost")] = (
            pivot_bm.loc[:, pd.IndexSlice[:, "Sum of cost"]].sum(axis=1)
        )
        

        # 🔥 BOTTOM GRAND TOTAL ROW
        grand_row = pivot_bm.sum(axis=0).to_frame().T
        grand_row.index = ["Grand Total"]

        pivot_bm_final = pd.concat([pivot_bm, grand_row])

        st.dataframe(pivot_bm_final, use_container_width=True)

        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pivot_bm_final.to_excel(writer)
        out.seek(0)

        st.download_button(
            "📥 Download Brand Manager Analysis",
            out,
            get_download_filename("brand_manager_analysis")
        )

    # ==================================================
    # TAB 2 – BRAND ANALYSIS (DATE WISE + GRAND TOTAL)
    # ==================================================
    with tab2:
        pivot_brand = pd.pivot_table(
            Working,
            index="Brand",
            columns="date",
            values=["quantity", "item-price", "cost"],
            aggfunc="sum",
            fill_value=0
        )

        pivot_brand = pivot_brand.swaplevel(0, 1, axis=1).sort_index(axis=1, level=0)
        pivot_brand.columns = pivot_brand.columns.map(
            lambda x: (x[0], f"Sum of {x[1]}")
        )

        pivot_brand[("Grand Total", "Total Sum of quantity")] = (
            pivot_brand.loc[:, pd.IndexSlice[:, "Sum of quantity"]].sum(axis=1)
        )
        pivot_brand[("Grand Total", "Total Sum of item-price")] = (
            pivot_brand.loc[:, pd.IndexSlice[:, "Sum of item-price"]].sum(axis=1)
        )
        
        pivot_brand[("Grand Total", "Total Sum of cost")] = (
            pivot_brand.loc[:, pd.IndexSlice[:, "Sum of cost"]].sum(axis=1)
        )
        
        
        grand_row = pivot_brand.sum(axis=0).to_frame().T
        grand_row.index = ["Grand Total"]

        pivot_brand_final = pd.concat([pivot_brand, grand_row])

        st.dataframe(pivot_brand_final, use_container_width=True)

        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pivot_brand_final.to_excel(writer)
        out.seek(0)

        st.download_button(
            "📥 Download Brand Analysis",
            out,
            get_download_filename("brand_analysis")
        )

    # ==================================================
    # TAB 3 – BRAND & ASIN SUMMARY (SORT + GRAND TOTAL BOTTOM)
    # ==================================================
    with tab3:
        brand_asin = (
            Working
            .groupby(["asin","Vendor SKU","Brand","product-name"])[["quantity", "item-price", "cost"]]
            .sum()
            .reset_index()
            .sort_values("quantity", ascending=False)
        )

        total_row = brand_asin[["quantity", "item-price", "cost"]].sum().to_frame().T
        total_row.insert(0, "asin", "Grand Total")
        total_row.insert(1, "Vendor SKU", "")
        total_row.insert(2, "Brand", "")
        total_row.insert(3, "product-name", "")

        brand_asin_final = pd.concat([brand_asin, total_row], ignore_index=True)

        st.dataframe(brand_asin_final, use_container_width=True)

        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            brand_asin_final.to_excel(writer, index=False)
        out.seek(0)

        st.download_button(
            "📥 Download Brand & ASIN Summary",
            out,
            "brand_asin_summary.xlsx"
        )

    # ==================================================
    # TAB 4 – BM / BRAND / ASIN SUMMARY
    # ==================================================
    with tab4:
        bm_brand_asin = (
            Working
            .groupby(["asin","Vendor SKU","Brand","Brand Manager","product-name"])[
                ["quantity", "item-price", "cost"]
            ]
            .sum()
            .reset_index()
            .sort_values("quantity", ascending=False)
        )

        total_row = bm_brand_asin[["quantity", "item-price", "cost"]].sum().to_frame().T
        total_row.insert(0, "asin", "Grand Total")
        total_row.insert(1, "Vendor SKU", "")
        total_row.insert(2, "Brand", "")
        total_row.insert(3, "Brand Manager", "")
        total_row.insert(4, "product-name", "")


        bm_brand_asin_final = pd.concat(
            [bm_brand_asin, total_row], ignore_index=True
        )

        st.dataframe(bm_brand_asin_final, use_container_width=True)

        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            bm_brand_asin_final.to_excel(writer, index=False)
        out.seek(0)

        st.download_button(
            "📥 Download BM / Brand / ASIN Summary",
            out,
            get_download_filename("bm_brand_asin_summary")
        )

    # ==================================================
    # TAB 5 – SUMMARY PIVOTS
    # ==================================================
    with tab5:
        brand_summary = (
            Working
            .groupby("Brand")[["quantity", "item-price", "cost"]]
            .sum()
            .reset_index()
            .sort_values("quantity", ascending=False)
        )

        brand_total = brand_summary[["quantity", "item-price", "cost"]].sum().to_frame().T
        brand_total.insert(0, "Brand", "Grand Total")

        brand_summary_final = pd.concat([brand_summary, brand_total], ignore_index=True)
        st.dataframe(brand_summary_final, use_container_width=True)
        
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            brand_summary_final.to_excel(writer, sheet_name="Brand Summary", index=False)
        out.seek(0)

        st.download_button(
            "📥 Download Brand Report",
            out,
            get_download_filename("Brand_report")
        )

        bm_summary = (
            Working
            .groupby("Brand Manager")[["quantity", "item-price", "cost"]]
            .sum()
            .reset_index()
            .sort_values("quantity", ascending=False)
        )

        bm_total = bm_summary[["quantity", "item-price", "cost"]].sum().to_frame().T
        bm_total.insert(0, "Brand Manager", "Grand Total")

        bm_summary_final = pd.concat([bm_summary, bm_total], ignore_index=True)
        st.dataframe(bm_summary_final, use_container_width=True)
        
        # 📥 DOWNLOAD SUMMARY REPORT
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            bm_summary_final.to_excel(writer, sheet_name="BM Summary", index=False)
        out.seek(0)

        st.download_button(
            "📥 Download Brand Manager Report",
            out,
            get_download_filename("Brand_Manager_report")
        )

    # ==================================================
    # TAB 6 – RAW DATA
    # ==================================================
    with tab6:
        st.dataframe(Working, use_container_width=True)
     
        # 📥 DOWNLOAD RAW DATA
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            Working.to_excel(writer, index=False, sheet_name="Raw Data")
        out.seek(0)

        st.download_button(
            "📥 Download Raw Data",
            out,
            get_download_filename("raw_data")
        )

    st.success("✅ All reports generated correctly (date-wise & grand totals fixed)")