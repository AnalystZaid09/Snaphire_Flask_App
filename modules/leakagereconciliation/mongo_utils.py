"""
MongoDB Utilities for Module Reports.
Provides MongoDB connection and report saving functionality.
"""

import os
import sys
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv

# Add parent directories to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables from module's .env
env_path = os.path.join(current_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Try project root
    load_dotenv()

# Try to import pymongo, handle if not installed
try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    MongoClient = None

def get_mongo_client():
    """
    Wrapper for centralized MongoDB client from common.mongo.
    """
    try:
        from common.mongo import client, MONGO_CONNECTED
        if not MONGO_CONNECTED:
            return None, "MongoDB not connected"
        return client, None
    except ImportError:
        return None, "common.mongo not found"

def save_reconciliation_report(collection_name, invoice_no, summary_data, line_items_data, metadata=None):
    """
    Saves the reconciliation report to the specified MongoDB collection.
    
    Args:
        collection_name (str): Name of the collection (e.g., 'bajaj_reconciliation').
        invoice_no (str): The invoice number (used as a key identifier).
        summary_data (dict): The summary dictionary or DataFrame (will be converted to dict).
        line_items_data (list or pd.DataFrame): The detailed line items.
        metadata (dict): Additional metadata like timestamp, file names, accuracy, etc.
    """
    client, error = get_mongo_client()
    if error:
        # Don't show error to user, just log silently
        print(f"MongoDB Connection Info: {error}")
        return False

    try:
        import pandas as pd
    except ImportError:
        pd = None

    db_name = os.getenv("MONGO_DB_NAME", "report_app")
    db = client[db_name]
    collection = db[collection_name]

    # Convert DataFrame to records if needed
    if pd and hasattr(summary_data, 'to_dict'):
        summary_data = summary_data.to_dict(orient='records')
    
    if pd and hasattr(line_items_data, 'to_dict'):
        line_items_data = line_items_data.to_dict(orient='records')

    document = {
        "invoice_no": invoice_no,
        "created_at": datetime.now(),
        "summary": summary_data,
        "line_items": line_items_data,
        "metadata": metadata or {}
    }

    try:
        # Insert to keep history
        collection.insert_one(document)
        st.success(f"✅ Report saved to MongoDB ({db_name}.{collection_name})")
        return True
    except Exception as e:
        st.error(f"Error saving to MongoDB: {str(e)}")
        return False
    finally:
        client.close()
