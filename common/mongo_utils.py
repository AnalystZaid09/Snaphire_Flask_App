"""
Shared MongoDB Utilities for All Modules.
Consolidates common MongoDB operations for reconciliation reports and general report saving.

This module replaces the duplicate mongo_utils.py files in each module folder.
All modules should import from this shared utility.
"""

import os
import sys
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, Union
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Add parent directories to path for imports (ensures this works from any module)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def get_mongo_client():
    """
    Get the centralized MongoDB client from common.mongo.
    
    Returns:
        tuple: (client, error_message) - client is None if connection failed
    """
    try:
        from common.mongo import client, MONGO_CONNECTED
        if not MONGO_CONNECTED:
            return None, "MongoDB not connected"
        return client, None
    except ImportError:
        return None, "common.mongo not found"


def save_reconciliation_report(
    module_name: str,
    collection_name: str, 
    invoice_no: str, 
    summary_data: Any, 
    line_items_data: Any, 
    tool_name: str = None,
    metadata: Optional[Dict] = None
) -> bool:
    """
    Saves a reconciliation report to the specified MongoDB collection.
    
    This is a universal function that works for all modules (amazon, flipkart, 
    reconciliation, leakagereconciliation, stockmovement).
    
    Args:
        module_name: Name of the calling module (e.g., 'amazon', 'flipkart')
        collection_name: Target MongoDB collection (e.g., 'amazon_reconciliation')
        invoice_no: The invoice number (used as a key identifier)
        summary_data: Summary data - can be dict, list, or DataFrame
        line_items_data: Line items data - can be dict, list, or DataFrame
        tool_name: Name of the tool generating the report (optional)
        metadata: Optional additional metadata
    
    Returns:
        bool: True if save was successful, False otherwise
    """
    client, error = get_mongo_client()
    if error:
        logger.info(f"MongoDB Connection Info: {error}")
        return False

    # Try to import pandas for DataFrame handling
    try:
        import pandas as pd
        has_pandas = True
    except ImportError:
        pd = None
        has_pandas = False

    try:
        from common.mongo import get_db, log_report_download, register_report_info
        db = get_db()
        if db is None:
            return False
            
        collection = db[collection_name]

        # Convert DataFrame to records if needed
        row_count = 0
        if has_pandas and hasattr(summary_data, 'to_dict'):
            row_count = len(summary_data)
            summary_data = summary_data.to_dict(orient='records')
        
        if has_pandas and hasattr(line_items_data, 'to_dict'):
            line_items_data = line_items_data.to_dict(orient='records')

        # Derive tool_name if not provided
        effective_tool_name = tool_name or f"{module_name}_reconciliation"

        document = {
            "invoice_no": invoice_no,
            "module": module_name,
            "tool_name": effective_tool_name,
            "created_at": datetime.now(),
            "summary": summary_data,
            "line_items": line_items_data,
            "metadata": metadata or {}
        }

        # Insert to collection (keeps history - no upsert)
        result = collection.insert_one(document)
        report_id = str(result.inserted_id)
        
        # Register in centralized report_registry
        user = st.session_state.get("user", "anonymous")
        try:
            register_report_info(
                module_name=module_name,
                tool_name=effective_tool_name,
                report_name=f"Reconciliation_{invoice_no}",
                report_id=report_id,
                user_email=user,
                filename=f"Invoice_{invoice_no}",
                row_count=row_count,
                metadata={
                    "invoice_no": invoice_no,
                    "target_collection": collection_name,
                    "type": "reconciliation_save",
                    **(metadata or {})
                }
            )
        except Exception as e:
            logger.warning(f"Registry log error: {e}")
        
        # Also log to central downloads collection for unified tracking (legacy)
        try:
            log_report_download(
                user_email=user,
                module=module_name,
                report_name=f"Reconciliation_{collection_name}",
                filename=f"Invoice_{invoice_no}",
                df_data=summary_data,
                metadata={
                    "invoice_no": invoice_no,
                    "target_collection": collection_name,
                    "type": "reconciliation_save"
                }
            )
        except Exception as e:
            logger.warning(f"Central log error: {e}")

        st.success(f"✅ Report saved to MongoDB ({collection_name})")
        return True
        
    except Exception as e:
        st.error(f"Error saving to MongoDB: {str(e)}")
        logger.error(f"MongoDB save error: {e}")
        return False


def save_report(
    module_name: str,
    report_name: str,
    data: Any,
    tool_name: str = None,
    collection_name: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> bool:
    """
    General-purpose report save function with centralized tracking.
    
    Args:
        module_name: Name of the calling module
        report_name: Human-readable name of the report
        data: Report data (DataFrame, dict, or list)
        tool_name: Name of the tool generating the report (optional, derived from module if not provided)
        collection_name: Optional custom collection name (defaults to module_name)
        metadata: Optional additional metadata
    
    Returns:
        bool: True if save was successful, False otherwise
    """
    try:
        from common.mongo import (
            get_db, log_report_download, MONGO_CONNECTED, 
            save_report_with_tracking
        )
        
        if not MONGO_CONNECTED:
            return False
            
        # Try to import pandas for DataFrame handling
        try:
            import pandas as pd
            has_pandas = True
        except ImportError:
            pd = None
            has_pandas = False
        
        # Convert DataFrame to records if needed
        data_to_save = data
        row_count = 0
        col_count = 0
        
        if has_pandas and hasattr(data, 'to_dict'):
            row_count = len(data)
            col_count = len(data.columns)
            data_to_save = data.to_dict(orient='records')
        elif isinstance(data, list):
            row_count = len(data)
            
        user = st.session_state.get("user", "anonymous")
        
        # Derive tool_name from module_name if not provided
        effective_tool_name = tool_name or f"{module_name}_tool"
        
        # Use the new tracking function
        filename = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        report_id = save_report_with_tracking(
            module_name=collection_name or module_name,
            tool_name=effective_tool_name,
            report_name=report_name,
            df_data=data,
            user_email=user,
            filename=filename,
            metadata=metadata
        )
        
        return report_id is not None
        
    except Exception as e:
        logger.error(f"Save report error: {e}")
        return False


# =============================================================================
# Module-Specific Convenience Functions
# =============================================================================

def save_amazon_report(collection_name: str, invoice_no: str, 
                       summary_data: Any, line_items_data: Any, 
                       tool_name: str = None,
                       metadata: Optional[Dict] = None) -> bool:
    """Convenience wrapper for Amazon module."""
    return save_reconciliation_report(
        module_name="amazon",
        collection_name=collection_name,
        invoice_no=invoice_no,
        summary_data=summary_data,
        line_items_data=line_items_data,
        tool_name=tool_name or "amazon_reconciliation",
        metadata=metadata
    )


def save_flipkart_report(collection_name: str, invoice_no: str,
                         summary_data: Any, line_items_data: Any,
                         tool_name: str = None,
                         metadata: Optional[Dict] = None) -> bool:
    """Convenience wrapper for Flipkart module."""
    return save_reconciliation_report(
        module_name="flipkart",
        collection_name=collection_name,
        invoice_no=invoice_no,
        summary_data=summary_data,
        line_items_data=line_items_data,
        tool_name=tool_name or "flipkart_reconciliation",
        metadata=metadata
    )


def save_generic_reconciliation_report(collection_name: str, invoice_no: str,
                                        summary_data: Any, line_items_data: Any,
                                        tool_name: str = None,
                                        metadata: Optional[Dict] = None) -> bool:
    """Convenience wrapper for Reconciliation module."""
    return save_reconciliation_report(
        module_name="reconciliation",
        collection_name=collection_name,
        invoice_no=invoice_no,
        summary_data=summary_data,
        line_items_data=line_items_data,
        tool_name=tool_name or "generic_reconciliation",
        metadata=metadata
    )


def save_leakage_report(collection_name: str, invoice_no: str,
                        summary_data: Any, line_items_data: Any,
                        tool_name: str = None,
                        metadata: Optional[Dict] = None) -> bool:
    """Convenience wrapper for Leakage Reconciliation module."""
    return save_reconciliation_report(
        module_name="leakagereconciliation",
        collection_name=collection_name,
        invoice_no=invoice_no,
        summary_data=summary_data,
        line_items_data=line_items_data,
        tool_name=tool_name or "leakage_reconciliation",
        metadata=metadata
    )


def save_stockmovement_report(collection_name: str, invoice_no: str,
                               summary_data: Any, line_items_data: Any,
                               tool_name: str = None,
                               metadata: Optional[Dict] = None) -> bool:
    """Convenience wrapper for Stock Movement module."""
    return save_reconciliation_report(
        module_name="stockmovement",
        collection_name=collection_name,
        invoice_no=invoice_no,
        summary_data=summary_data,
        line_items_data=line_items_data,
        tool_name=tool_name or "stock_movement",
        metadata=metadata
    )
