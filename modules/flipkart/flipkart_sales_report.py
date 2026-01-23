import streamlit as st
import pandas as pd
import plotly.express as px
import warnings

warnings.filterwarnings("ignore", message="Workbook contains no default style*")

import io

from common.ui_utils import (
    apply_professional_style, 
    get_download_filename, 
    render_header,
    download_module_report,
    auto_save_generated_reports
)

# Module name and Tool name for MongoDB tracking
MODULE_NAME = "flipkart"
TOOL_NAME = "flipkart_sales_report"

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="Flipkart Sales Analysis", layout="wide")
apply_professional_style()

# ---------- SIDEBAR ----------
with st.sidebar:
    st.header("📁 Upload Files")
    flipkart_file = st.file_uploader("Upload Flipkart PM Excel", type=["xlsx", "xls"], key="flipkart_pm")
    top_products_file = st.file_uploader("Upload Top Products (CSV / Excel)", type=["csv", "xlsx", "xls"], key="top_products")
    st.markdown("---")
    st.info("👆 Upload files, then click **Generate Analysis** below")

# ---------- TITLE ----------
render_header("Flipkart Sales Analysis")

# ---------- SESSION STATE ----------
if 'flip_results' not in st.session_state:
    st.session_state.flip_results = None

# ---------- BUTTON IN MAIN CONTENT ----------
generate = st.button("🚀 Generate Analysis", type="primary", use_container_width=True)

# ---------- MAIN ----------
if generate:
    if not flipkart_file or not top_products_file:
        st.error("❌ Please upload both files in the sidebar")
    else:
        try:
            # ---------- LOAD ----------
            flipkart = pd.read_excel(flipkart_file)
            top = pd.read_csv(top_products_file) if top_products_file.name.endswith(".csv") else pd.read_excel(top_products_file)

            if "Brand" in top.columns:
                top.rename(columns={"Brand": "Brand1"}, inplace=True)

            # ---------- VALIDATION ----------
            required_pm = ["FNS", "Product Name", "Vendor SKU Codes", "Brand", "Brand Manager"]
            for c in required_pm:
                if c not in flipkart.columns:
                    raise KeyError(f"Flipkart PM me '{c}' missing")

            if "Product Id" not in top.columns:
                raise KeyError("Top Products me 'Product Id' missing")
            if "Final Sale Units" not in top.columns:
                raise KeyError("Final Sale Units missing")

            # ---------- CLEAN KEYS ----------
            top["Product Id"] = top["Product Id"].astype(str).str.strip().str.upper()
            flipkart["FNS"] = flipkart["FNS"].astype(str).str.strip().str.upper()

            flipkart = flipkart.drop_duplicates("FNS")

            cp_col = [c for c in flipkart.columns if str(c).lower().startswith("cp")][0]

            # ---------- MERGE ----------
            final_df = top.merge(
                flipkart[
                    ["FNS", "Product Name", "Vendor SKU Codes", "Brand", "Brand Manager", cp_col]
                ],
                left_on="Product Id",
                right_on="FNS",
                how="left"
            ).rename(columns={
                "Brand Manager": "Manager",
                cp_col: "cost"
            })

            # ---------- SAFE TEXT CLEAN ----------
            def clean_text(x):
                try:
                    if pd.isna(x):
                        return "Unknown"
                    return str(x).strip()
                except Exception:
                    return "Unknown"

            final_df["Product Name"] = final_df["Product Name"].apply(clean_text)
            final_df["Vendor SKU Codes"] = final_df["Vendor SKU Codes"].apply(clean_text)

            # ---------- BRAND STANDARDIZATION ----------
            final_df["Brand"] = (
                final_df["Brand"]
                .astype(str)
                .str.strip()
                .str.lower()
                .str.title()
                .replace("Nan", "Unknown")
            )

            # ---------- NUMERIC CLEAN ----------
            final_df["Final Sale Units"] = pd.to_numeric(
                final_df["Final Sale Units"], errors="coerce"
            ).fillna(0).clip(lower=0)
            # ---------- REMOVE ZERO SALE UNITS ---------- 22/12/2025 changes
            final_df["Final Sale Units"] = pd.to_numeric(final_df["Final Sale Units"], errors="coerce").fillna(0)
            final_df = final_df[final_df["Final Sale Units"].astype(int) != 0]

            if "Final Sale Amount" in final_df.columns:
                final_df.rename(columns={"Final Sale Amount": "Sales"}, inplace=True)

            final_df["Sales"] = pd.to_numeric(final_df["Sales"], errors="coerce").fillna(0)
            final_df["cost"] = pd.to_numeric(final_df["cost"], errors="coerce").fillna(0)
            final_df["Manager"] = final_df["Manager"].fillna("Unknown")
            final_df["FNS"] = final_df["FNS"].fillna("Unknown")
            
            # ---------- NEW COLUMN: As Per Qty Cost ----------
            final_df["As Per Qty Cost"] = final_df["cost"] * final_df["Final Sale Units"]

            st.session_state.flip_results = final_df
            st.success("✅ Analysis generated successfully!")
            
            # AUTO-SAVE generated reports to database
            # Only save once when generated
            if st.session_state.flip_results is not None:
                reports_to_save = {
                    "Flipkart Sales Data": final_df
                }
                auto_save_generated_reports(reports_to_save, MODULE_NAME, tool_name=TOOL_NAME)

        except Exception as e:
            st.error(f"❌ Error: {e}")

if st.session_state.flip_results is not None:
    final_df = st.session_state.flip_results
    
    # ---------- METRICS ----------
    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Units", int(final_df["Final Sale Units"].sum()))
    m2.metric("Total Sales", f"₹{final_df['Sales'].sum():,.0f}")
    m3.metric("Brands", final_df["Brand"].nunique())
    m4.metric("Managers", final_df["Manager"].nunique())

    # ---------- TABS ----------
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📊 Brand Analysis",
        "👥 Manager Analysis",
        "📋 Raw Data",
        "📉 Charts",
        "📦 Brand / FNS Pivot",
        "🏷 Manager / Brand / FNS Pivot",
        "📌 Brand Pivot",
        "📌 Brand Manager Pivot"
    ])

    # ---------- TAB 1 (BRAND + GRAND TOTAL) ----------
    with tab1:
        pivot = final_df.pivot_table(
            index="Brand",
            columns="Order Date",
            values=["Final Sale Units", "Sales"],
            aggfunc="sum",
            fill_value=0
        )
        pivot.columns = pivot.columns.swaplevel(0, 1)
        pivot = pivot.sort_index(axis=1, level=0)
        pivot.columns = pd.MultiIndex.from_tuples(
            [(date, "Final Sale Units") if metric == "Final Sale Units" else (date, "Sales")
            for date, metric in pivot.columns]
        )
        pivot["Total sum of Final Sale Units"] = final_df.groupby("Brand")["Final Sale Units"].sum()
        pivot["Total sum of Sales"] = final_df.groupby("Brand")["Sales"].sum()
        pivot.loc["Grand Total"] = pivot.sum(numeric_only=True)

        st.dataframe(pivot, use_container_width=True)
        download_module_report(
            df=pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="Brand Pivot",
            button_label="⬇️ Download Brand Pivot",
            key="flip_brand_pivot"
        )

    with tab2:
        pivot = final_df.pivot_table(
            index="Manager",
            columns="Order Date",
            values=["Final Sale Units", "Sales"],
            aggfunc="sum",
            fill_value=0
        )
        pivot.columns = pivot.columns.swaplevel(0, 1)
        pivot = pivot.sort_index(axis=1, level=0)
        pivot.columns = pd.MultiIndex.from_tuples(
            [(date, "Final Sale Units") if metric == "Final Sale Units" else (date, "Sales")
            for date, metric in pivot.columns]
        )
        pivot["Total sum of Final Sale Units"] = final_df.groupby("Manager")["Final Sale Units"].sum()
        pivot["Total sum of Sales"] = final_df.groupby("Manager")["Sales"].sum()
        pivot.loc["Grand Total"] = pivot.sum(numeric_only=True)

        st.dataframe(pivot, use_container_width=True)
        download_module_report(
            df=pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="Manager Pivot",
            button_label="⬇️ Download Manager Pivot",
            key="flip_manager_pivot"
        )

    # ---------- TAB 3 ----------
    with tab3:
        st.dataframe(final_df, use_container_width=True)
        download_module_report(
            df=final_df,
            module_name=MODULE_NAME,
            report_name="Raw Data",
            button_label="⬇️ Download Raw Data",
            key="flip_raw_data"
        )

    # ---------- TAB 4 ----------
    with tab4:
        fig = px.bar(
            final_df.groupby("Brand")["Sales"].sum().reset_index(),
            x="Brand",
            y="Sales",
            title="Sales by Brand"
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---------- TAB 5 ----------
    with tab5:
        base = final_df.groupby(
            ["FNS", "Brand", "Product Name", "Vendor SKU Codes"]
        ).agg({
            "Final Sale Units": "sum",
            "Sales": "sum",
            "cost": "mean"
        })
        base["As Per Qty Cost"] = base["cost"] * base["Final Sale Units"]
        grand = pd.DataFrame(
            [[base["Final Sale Units"].sum(), base["Sales"].sum(), base["cost"].mean(), (base["cost"] * base["Final Sale Units"]).sum()]],
            index=pd.MultiIndex.from_tuples([("Grand Total", "", "", "")], names=base.index.names),
            columns=["Final Sale Units", "Sales", "cost", "As Per Qty Cost"]
        )
        pivot_df = pd.concat([base, grand])
        st.dataframe(pivot_df, use_container_width=True)
        download_module_report(
            df=pivot_df.reset_index(),
            module_name=MODULE_NAME,
            report_name="Brand FNS Pivot",
            button_label="⬇️ Download Brand/FNS Pivot",
            key="flip_brand_fns"
        )

    # ---------- TAB 6 ----------
    with tab6:
        base = final_df.groupby(
            ["FNS", "Manager", "Brand", "Product Name", "Vendor SKU Codes"]
        ).agg({
            "Final Sale Units": "sum",
            "Sales": "sum",
            "cost": "mean"
        })
        base["As Per Qty Cost"] = base["cost"] * base["Final Sale Units"]
        grand = pd.DataFrame(
            [[base["Final Sale Units"].sum(), base["Sales"].sum(), base["cost"].mean(), (base["cost"] * base["Final Sale Units"]).sum()]],
            index=pd.MultiIndex.from_tuples([("Grand Total", "", "", "", "")], names=base.index.names),
            columns=["Final Sale Units", "Sales", "cost", "As Per Qty Cost"]
        )
        pivot_df = pd.concat([base, grand])
        st.dataframe(pivot_df, use_container_width=True)
        download_module_report(
            df=pivot_df.reset_index(),
            module_name=MODULE_NAME,
            report_name="Manager Brand FNS Pivot",
            button_label="⬇️ Download Manager/Brand/FNS Pivot",
            key="flip_mgr_brand_fns"
        )

    # ---------- TAB 7 : BRAND PIVOT ----------
    with tab7:
        brand_pivot = final_df.pivot_table(
            index="Brand",
            values=["Final Sale Units", "Sales"],
            aggfunc="sum",
            fill_value=0
        ).rename(columns={"Final Sale Units": "Sum of Final Sale Units", "Sales": "Sum of Final Sale Amount"})
        brand_pivot.loc["Grand Total"] = brand_pivot.sum(numeric_only=True)
        st.dataframe(brand_pivot, use_container_width=True)
        download_module_report(
            df=brand_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="Simple Brand Pivot",
            button_label="⬇️ Download Brand Pivot",
            key="flip_brand_simple"
        )

    # ---------- TAB 8 : BRAND MANAGER PIVOT ----------
    with tab8:
        manager_pivot = final_df.pivot_table(
            index="Manager",
            values=["Final Sale Units", "Sales"],
            aggfunc="sum",
            fill_value=0
        ).rename(columns={"Final Sale Units": "Sum of Final Sale Units", "Sales": "Sum of Final Sale Amount"})
        manager_pivot.loc["Grand Total"] = manager_pivot.sum(numeric_only=True)
        st.dataframe(manager_pivot, use_container_width=True)
        download_module_report(
            df=manager_pivot.reset_index(),
            module_name=MODULE_NAME,
            report_name="Simple Manager Pivot",
            button_label="⬇️ Download Manager Pivot",
            key="flip_mgr_simple"
        )

else:
    st.info("👆 Upload files and click **Generate Analysis**")
