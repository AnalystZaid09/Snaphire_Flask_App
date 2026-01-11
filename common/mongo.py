"""
MongoDB Configuration for IBI Reporting Application.
Handles database connections and collection references.
"""

from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# MongoDB Atlas URI (with escaped password)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://syedzaidali09112000_db_user:syed%400911@cluster0.pwosxdt.mongodb.net/?appName=Cluster0")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "report_app")

# Initialize MongoDB client
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[MONGO_DB_NAME]
    MONGO_CONNECTED = True
except Exception as e:
    print(f"MongoDB connection error: {e}")
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    MONGO_CONNECTED = False

# Collection references
users_col = db["users"]
downloads_col = db["report_downloads"]
saved_reports_col = db["saved_reports"]

# Create indexes
try:
    downloads_col.create_index([("user_email", 1), ("downloaded_at", -1)])
    downloads_col.create_index([("module", 1)])
    saved_reports_col.create_index([("user_email", 1), ("created_at", -1)])
except Exception:
    pass


def log_report_download(user_email: str, module: str, report_name: str, filename: str,
                        df_data=None, row_count: int = 0, col_count: int = 0, 
                        file_size: int = 0, metadata: dict = None):
    """Log a report download to MongoDB with full report data."""
    try:
        report_data = None
        if df_data is not None:
            try:
                if hasattr(df_data, 'to_dict'):
                    if len(df_data) > 10000:
                        report_data = df_data.head(10000).to_dict(orient='records')
                    else:
                        report_data = df_data.to_dict(orient='records')
            except Exception:
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
        
        if report_data:
            document["report_data"] = report_data
        
        downloads_col.insert_one(document)
        return True
    except Exception as e:
        print(f"MongoDB log error: {e}")
        return False