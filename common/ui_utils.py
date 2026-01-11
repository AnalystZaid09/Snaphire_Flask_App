"""
Centralized UI Utilities for IBI Reporting Application.
Provides consistent styling, download with MongoDB logging, and date-stamped filenames.
"""

import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List
import pandas as pd
from io import BytesIO
import os
import sys

# Import MongoDB utilities from common.mongo
try:
    from common.mongo import log_report_download, downloads_col
    MONGO_AVAILABLE = True
except ImportError:
    # Fallback if imports fail
    MONGO_AVAILABLE = False
    log_report_download = None
    downloads_col = None

def apply_professional_style():
    """Applies professional CSS styling."""
    st.markdown("""
        <style>
        .report-header {
            text-align: center;
            padding: 1rem 0;
            margin-bottom: 1.5rem;
        }
        .report-title {
            color: #f8fafc;
            font-size: 1.5rem;
            font-weight: 600;
        }
        </style>
    """, unsafe_allow_html=True)

def get_download_filename(base_name: str, extension: str = "xlsx") -> str:
    """
    Generates a filename with exact current date and time.
    Format: base_name_2026-01-11_01-55-17.xlsx
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_name = base_name.replace(f".{extension}", "").replace(" ", "_")
    return f"{base_name}_{timestamp}.{extension}"

def render_header(title: str, subtitle: Optional[str] = None):
    """Renders a styled header section."""
    st.markdown(f"""
        <div class="report-header">
            <h2 class="report-title">{title}</h2>
            {f'<p style="color: #94a3b8;">{subtitle}</p>' if subtitle else ''}
        </div>
    """, unsafe_allow_html=True)

def to_excel(df: pd.DataFrame, apply_doc_formatting: bool = False) -> bytes:
    """Convert DataFrame to Excel bytes."""
    output = BytesIO()
    # Handle MultiIndex or standard Index
    index_needed = isinstance(df.index, pd.MultiIndex) or (not df.index.name is None)
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=index_needed, sheet_name='Report')
        
        if apply_doc_formatting and 'DOC' in df.columns:
            try:
                from openpyxl.styles import PatternFill, Font
                workbook = writer.book
                worksheet = writer.sheets['Report']
                doc_col_idx = df.columns.get_loc('DOC') + (2 if index_needed else 1)
                
                for row_idx in range(2, len(df) + 2):
                    cell = worksheet.cell(row=row_idx, column=doc_col_idx)
                    doc_value = df.iloc[row_idx - 2]['DOC']
                    
                    if pd.notna(doc_value) and doc_value != '':
                        try:
                            doc_val = float(doc_value)
                            if doc_val < 7:
                                color = 'FF4444'
                            elif doc_val < 15:
                                color = 'FF8800'
                            elif doc_val < 30:
                                color = '44FF44'
                            elif doc_val < 45:
                                color = 'FFFF44'
                            elif doc_val < 60:
                                color = '44DDFF'
                            elif doc_val < 90:
                                color = '8B4513'
                            else:
                                color = '000000'
                            
                            cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                            cell.font = Font(color='FFFFFF' if doc_val < 15 or doc_val >= 60 else '000000', bold=True)
                        except (ValueError, TypeError):
                            pass
            except ImportError:
                pass
    
    return output.getvalue()

def download_report(df: pd.DataFrame, base_filename: str, button_label: str = "📥 Download Report",
                    module_name: str = "unknown", report_name: str = "Report",
                    apply_doc_formatting: bool = False, key: str = None):
    """
    Creates download button and logs full report data to MongoDB when downloaded.
    """
    # Generate filename with timestamp
    filename = get_download_filename(base_filename)
    
    # Convert to Excel
    excel_data = to_excel(df, apply_doc_formatting)
    
    # Create download button
    downloaded = st.download_button(
        label=button_label,
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"download_{base_filename}_{datetime.now().timestamp()}"
    )
    
    # Log full report to MongoDB when button is clicked
    if downloaded:
        user = st.session_state.get("user", "anonymous")
        
        if log_report_download:
            try:
                success = log_report_download(
                    user_email=user,
                    module=module_name,
                    report_name=report_name,
                    filename=filename,
                    df_data=df,
                    row_count=len(df),
                    col_count=len(df.columns),
                    file_size=len(excel_data)
                )
                if success:
                    st.toast(f"✅ {report_name} saved to database", icon="📥")
            except Exception as e:
                print(f"MongoDB log error: {e}")
    
    return downloaded

def auto_log_reports(reports_dict: Dict[str, pd.DataFrame], module_name: str):
    """
    Automatically log multiple reports to MongoDB without waiting for download clicks.
    Useful for tools that generate multiple outputs at once.
    """
    if not MONGO_AVAILABLE or not log_report_download:
        return False
    
    user = st.session_state.get("user", "anonymous")
    success_count = 0
    
    for report_name, df in reports_dict.items():
        try:
            filename = f"auto_{get_download_filename(report_name)}"
            success = log_report_download(
                user_email=user,
                module=module_name,
                report_name=report_name,
                filename=filename,
                df_data=df,
                row_count=len(df),
                col_count=len(df.columns)
            )
            if success:
                success_count += 1
        except Exception as e:
            print(f"Auto-log error for {report_name}: {e}")
            
    if success_count > 0:
        st.toast(f"✅ {success_count} reports dumped to MongoDB", icon="💾")
    
    return success_count == len(reports_dict)

def display_dataframe(df: pd.DataFrame, height: int = 400, use_container_width: bool = True):
    """Display DataFrame with proper styling."""
    st.dataframe(df, use_container_width=use_container_width, height=height)
