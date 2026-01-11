"""
MongoDB Configuration for IBI Reporting Application.
Handles database connections and collection references.
"""

from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Prioritize environment variables
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "report_app")
IS_VERCEL = os.getenv("VERCEL") == "1"

# Hardcoded Fallback for Vercel (if environment variables fail)
ATLAS_FALLBACK = "mongodb+srv://syedzaidali09112000_db_user:syed%400911@cluster0.pwosxdt.mongodb.net/?appName=Cluster0"

# If MONGO_URI is missing
if not MONGO_URI:
    if IS_VERCEL:
        print("⚠️  MONGO_URI not found via environment. Using Vercel Fallback URI.")
        MONGO_URI = ATLAS_FALLBACK
    else:
        MONGO_URI = "mongodb://localhost:27017"
        print("⚠️ Warning: MONGO_URI not found. Defaulting to localhost:27017")
else:
    # Basic check for common errors
    if "<db_password>" in MONGO_URI:
        print("❌ Error: MONGO_URI contains <db_password> placeholder.")
    elif "@" in MONGO_URI.split("://")[-1].split("@")[0] and "%40" not in MONGO_URI:
        # Check if password contains unescaped @ (this is a simple check)
        # Note: This is an approximation
        pass
    
    if IS_VERCEL:
        safe_uri = MONGO_URI[:15] + "..." + MONGO_URI[-10:] if len(MONGO_URI) > 25 else "Short URI"
        print(f"✅ MONGO_URI provided: {safe_uri}")

# Initialize MongoDB client
try:
    if not MONGO_URI:
        raise ValueError("MONGO_URI is empty")
        
    # Use shorter timeout for ping
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ping')
    db = client[MONGO_DB_NAME]
    MONGO_CONNECTED = True
    print(f"✅ Connected to MongoDB: {MONGO_DB_NAME}")
except Exception as e:
    print(f"❌ MongoDB connection error: {e}")
    # Fallback - create client that will try to connect later
    client = MongoClient("mongodb://localhost:27017")
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
    """
    try:
        # Convert DataFrame to records if provided
        report_data = None
        if df_data is not None:
            try:
                import pandas as pd
                if hasattr(df_data, 'to_dict'):
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
        
        if report_data:
            document["report_data"] = report_data
        
        downloads_col.insert_one(document)
        return True
    except Exception as e:
        print(f"MongoDB log error: {e}")
        return False