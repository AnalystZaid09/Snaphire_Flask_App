"""
Centralized UI Utilities for IBI Reporting Application.
Provides consistent styling, download with MongoDB logging, and date-stamped filenames.
Professional-grade utilities for enterprise deployment.
"""

import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
import pandas as pd
from io import BytesIO
import os
import sys
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Import MongoDB utilities from common.mongo
try:
    from common.mongo import (
        log_report_download, 
        log_multi_report_download, 
        downloads_col, 
        MONGO_CONNECTED,
        save_module_report,
        save_and_track_report,
        save_reconciliation_report
    )
    MONGO_AVAILABLE = MONGO_CONNECTED
except ImportError:
    MONGO_AVAILABLE = False
    log_report_download = None
    log_multi_report_download = None
    downloads_col = None
    save_module_report = None
    save_and_track_report = None


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
    Format: base_name_2026-01-11_15-30-45.xlsx
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_name = base_name.replace(f".{extension}", "").replace(" ", "_")
    # Clean up any double underscores
    base_name = "_".join(filter(None, base_name.split("_")))
    return f"{base_name}_{timestamp}.{extension}"


def render_header(title: str, subtitle: Optional[str] = None):
    """Renders a styled header section."""
    st.markdown(f"""
        <div class="report-header">
            <h2 class="report-title">{title}</h2>
            {f'<p style="color: #94a3b8;">{subtitle}</p>' if subtitle else ''}
        </div>
    """, unsafe_allow_html=True)


def to_excel(df: pd.DataFrame, apply_doc_formatting: bool = False, sheet_name: str = 'Report') -> bytes:
    """Convert DataFrame to Excel bytes with optional formatting."""
    output = BytesIO()
    # Handle MultiIndex or standard Index
    index_needed = isinstance(df.index, pd.MultiIndex) or (df.index.name is not None)
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=index_needed, sheet_name=sheet_name)
        
        if apply_doc_formatting and 'DOC' in df.columns:
            try:
                from openpyxl.styles import PatternFill, Font
                workbook = writer.book
                worksheet = writer.sheets[sheet_name]
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


def to_multi_sheet_excel(reports: Dict[str, pd.DataFrame]) -> bytes:
    """
    Convert multiple DataFrames to a multi-sheet Excel file.
    
    Args:
        reports: Dict of {sheet_name: DataFrame}
    
    Returns:
        Excel file as bytes
    """
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in reports.items():
            # Clean sheet name (Excel has 31 char limit and special char restrictions)
            clean_name = str(sheet_name)[:31].replace('/', '-').replace('\\', '-')
            clean_name = clean_name.replace('[', '').replace(']', '').replace('*', '')
            clean_name = clean_name.replace('?', '').replace(':', '-')
            
            # Handle MultiIndex
            index_needed = isinstance(df.index, pd.MultiIndex) or (df.index.name is not None)
            df.to_excel(writer, index=index_needed, sheet_name=clean_name)
    
    return output.getvalue()


def download_report(df: pd.DataFrame, base_filename: str, button_label: str = "📥 Download Report",
                    module_name: str = "unknown", report_name: str = "Report",
                    apply_doc_formatting: bool = False, key: str = None,
                    sheet_name: str = "Report") -> bool:
    """
    Creates download button and logs full report data to MongoDB when downloaded.
    
    Args:
        df: DataFrame to download
        base_filename: Base name for the file (timestamp will be added)
        button_label: Label for the download button
        module_name: Name of the module (for MongoDB logging)
        report_name: Human-readable report name (for MongoDB logging)
        apply_doc_formatting: Whether to apply DOC column formatting
        key: Unique key for the button
        sheet_name: Sheet name for Excel file
    
    Returns:
        True if download was clicked, False otherwise
    """
    # Generate filename with timestamp
    filename = get_download_filename(base_filename)
    
    # Convert to Excel
    excel_data = to_excel(df, apply_doc_formatting, sheet_name)
    
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
        _log_download(df, filename, module_name, report_name, len(excel_data), sheet_name)
    
    return downloaded


def download_multi_sheet_excel(reports: Dict[str, pd.DataFrame], base_filename: str,
                                module_name: str, button_label: str = "📥 Download All Reports",
                                key: str = None) -> bool:
    """
    Download multiple reports as a multi-sheet Excel file with MongoDB logging.
    
    Args:
        reports: Dict of {sheet_name: DataFrame}
        base_filename: Base name for the file
        module_name: Name of the module for logging
        button_label: Label for the download button
        key: Unique key for the button
    
    Returns:
        True if download was clicked, False otherwise
    """
    if not reports:
        st.warning("No reports to download")
        return False
    
    # Generate filename with timestamp
    filename = get_download_filename(base_filename)
    
    # Convert to multi-sheet Excel
    excel_data = to_multi_sheet_excel(reports)
    
    # Create download button
    downloaded = st.download_button(
        label=button_label,
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"download_multi_{base_filename}_{datetime.now().timestamp()}"
    )
    
    # Log each report to MongoDB when button is clicked
    if downloaded:
        user = st.session_state.get("user", "anonymous")
        
        if log_multi_report_download:
            try:
                log_multi_report_download(
                    user_email=user,
                    module=module_name,
                    reports=reports,
                    filename=filename,
                    metadata={"multi_sheet": True, "sheet_count": len(reports)}
                )
                st.toast(f"✅ {len(reports)} reports saved to database", icon="📥")
            except Exception as e:
                logger.warning(f"Multi-report log error: {e}")
    
    return downloaded


def _log_download(df: pd.DataFrame, filename: str, module_name: str, 
                  report_name: str, file_size: int, sheet_name: str = None):
    """Internal function to log download to MongoDB."""
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
                file_size=file_size,
                sheet_name=sheet_name
            )
            if success:
                st.toast(f"✅ {report_name} saved to database", icon="📥")
        except Exception as e:
            logger.warning(f"MongoDB log error: {e}")


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
            logger.warning(f"Auto-log error for {report_name}: {e}")
            
    if success_count > 0:
        st.toast(f"✅ {success_count} reports saved to MongoDB", icon="💾")
    
    return success_count == len(reports_dict)


def display_dataframe(df: pd.DataFrame, height: int = 400, use_container_width: bool = True):
    """Display DataFrame with proper styling."""
    st.dataframe(df, use_container_width=use_container_width, height=height)


def create_download_section(reports: Dict[str, pd.DataFrame], module_name: str,
                            section_title: str = "📥 Download Reports"):
    """
    Create a standardized download section with individual and combined download options.
    
    Args:
        reports: Dict of {report_name: DataFrame}
        module_name: Module name for logging
        section_title: Title for the download section
    """
    st.markdown(f"### {section_title}")
    
    # Individual downloads
    cols = st.columns(min(len(reports), 3))
    for idx, (report_name, df) in enumerate(reports.items()):
        with cols[idx % 3]:
            download_report(
                df=df,
                base_filename=report_name.replace(" ", "_"),
                button_label=f"📥 {report_name}",
                module_name=module_name,
                report_name=report_name,
                key=f"dl_{module_name}_{report_name}_{idx}"
            )
    
    # Combined download if multiple reports
    if len(reports) > 1:
        st.markdown("---")
        download_multi_sheet_excel(
            reports=reports,
            base_filename=f"{module_name}_all_reports",
            module_name=module_name,
            button_label="📦 Download All Reports (Combined Excel)",
            key=f"dl_combined_{module_name}"
        )


# =============================================================================
# Module-Specific Report Download (NEW STRUCTURE)
# =============================================================================

def download_module_report(df: pd.DataFrame, module_name: str, report_name: str,
                           button_label: str = "📥 Download", key: str = None,
                           apply_doc_formatting: bool = False) -> bool:
    """
    Download button that saves report to module-specific collection.
    
    Each module has its own collection (e.g., 'stock_movement').
    Reports are saved by name with download tracking.
    
    Args:
        df: DataFrame to download
        module_name: Module/collection name (e.g., 'stock_movement')
        report_name: Report name (e.g., 'amazon_business_pivot')
        button_label: Label for download button
        key: Unique key for the button
        apply_doc_formatting: Whether to apply DOC column formatting
    
    Returns:
        True if download was clicked
    """
    # Generate filename with timestamp
    base_filename = report_name.replace(" ", "_").lower()
    filename = get_download_filename(base_filename)
    
    # Convert to Excel
    excel_data = to_excel(df, apply_doc_formatting, report_name[:31])
    
    # Create download button
    downloaded = st.download_button(
        label=button_label,
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"dl_{module_name}_{report_name}_{datetime.now().timestamp()}"
    )
    
    # Save to module collection and log download when clicked
    if downloaded:
        user = st.session_state.get("user", "anonymous")
        
        if save_and_track_report:
            try:
                save_and_track_report(
                    module_name=module_name,
                    report_name=report_name,
                    df_data=df,
                    user_email=user,
                    filename=filename,
                    is_download=True,
                    metadata={
                        "row_count": len(df),
                        "column_count": len(df.columns),
                        "file_size_bytes": len(excel_data)
                    }
                )
                st.toast(f"✅ {report_name} saved to {module_name}", icon="📥")
            except Exception as e:
                logger.warning(f"Module report save error: {e}")
    
    return downloaded


def save_module_reports_on_generate(reports: Dict[str, pd.DataFrame], module_name: str):
    """
    Save all reports to module collection when generated (before download).
    
    Call this after generating reports to pre-save them to the module collection.
    Downloads will then update the download tracking.
    
    Args:
        reports: Dict of {report_name: DataFrame}
        module_name: Module/collection name
    """
    if not MONGO_AVAILABLE or not save_module_report:
        return
    
    user = st.session_state.get("user", "anonymous")
    
    for report_name, df in reports.items():
        try:
            save_module_report(
                module_name=module_name,
                report_name=report_name,
                df_data=df,
                user_email=user,
                metadata={
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "auto_saved": True
                }
            )
        except Exception as e:
            logger.warning(f"Auto-save error for {report_name}: {e}")


def create_module_download_section(reports: Dict[str, pd.DataFrame], module_name: str,
                                    section_title: str = "📥 Download Reports"):
    """
    Create download section with module-specific collection saving.
    
    Args:
        reports: Dict of {report_name: DataFrame}
        module_name: Module/collection name
        section_title: Title for the section
    """
    st.markdown(f"### {section_title}")
    
    cols = st.columns(min(len(reports), 3))
    for idx, (report_name, df) in enumerate(reports.items()):
        with cols[idx % 3]:
            download_module_report(
                df=df,
                module_name=module_name,
                report_name=report_name,
                button_label=f"📥 {report_name}",
                key=f"dl_{module_name}_{report_name}_{idx}"
            )

