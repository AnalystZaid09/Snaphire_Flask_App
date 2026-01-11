"""
MongoDB Configuration for IBI Reporting Application.
Handles database connections and collection references.
"""

from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "report_app")

# Initialize MongoDB client
try:
    client = MongoClient(MONGO_URI)
    # Test connection
    client.admin.command('ping')
    db = client[MONGO_DB_NAME]
    MONGO_CONNECTED = True
except Exception as e:
    print(f"MongoDB connection warning: {e}")
    # Fallback - create client that will try to connect later
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    MONGO_CONNECTED = False

# Collection references
users_col = db["users"]                    # User authentication
downloads_col = db["report_downloads"]      # Download history with report data
saved_reports_col = db["saved_reports"]     # Full report storage (for larger reports)

# Create indexes for better performance
try:
    downloads_col.create_index([("user_email", 1), ("downloaded_at", -1)])
    downloads_col.create_index([("module", 1)])
    saved_reports_col.create_index([("user_email", 1), ("created_at", -1)])
except Exception:
    pass  # Indexes might already exist


def log_report_download(user_email: str, module: str, report_name: str, filename: str,
                        df_data=None, row_count: int = 0, col_count: int = 0, 
                        file_size: int = 0, metadata: dict = None):
    """
    Log a report download to MongoDB with full report data.
    
    Args:
        user_email: Email/username of the user downloading
        module: Module name (e.g., 'amazon', 'flipkart', 'reconciliation')
        report_name: Human-readable name of the report
        filename: Downloaded filename
        df_data: DataFrame data (will be converted to records, max 10000 rows)
        row_count: Number of rows in the report
        col_count: Number of columns
        file_size: File size in bytes
        metadata: Additional metadata dict
    
    Returns:
        bool: True if logged successfully, False otherwise
    """
    try:
        # Convert DataFrame to records if provided
        report_data = None
        if df_data is not None:
            try:
                import pandas as pd
                if hasattr(df_data, 'to_dict'):
                    # Limit to 10000 rows for practical storage
                    if len(df_data) > 10000:
                        report_data = df_data.head(10000).to_dict(orient='records')
                    else:
                        report_data = df_data.to_dict(orient='records')
            except Exception as e:
                print(f"Error converting DataFrame: {e}")
                report_data = None
        
        document = {
            "user_email": user_email,
            "module": module,
            "report_name": report_name,
            "file_name": filename,
            "downloaded_at": datetime.now(),
            "metadata": {
                "row_count": row_count,
                "column_count": col_count,
                "file_size_bytes": file_size,
                **(metadata or {})
            }
        }
        
        # Store full report data if available
        if report_data:
            document["report_data"] = report_data
        
        downloads_col.insert_one(document)
        return True
    except Exception as e:
        print(f"MongoDB log error: {e}")
        return False

