"""
MongoDB Configuration for IBI Reporting Application.
Handles database connections and collection references.
Professional-grade setup for MongoDB Atlas deployment.
"""

from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConfigurationError
import os
from datetime import datetime
from dotenv import load_dotenv
import logging

import urllib.parse
import re
import certifi

# Load environment variables (override=True ensures .env wins)
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _get_safe_mongo_uri():
    """Get MongoDB URI from environment and safely encode credentials."""
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017").strip()
    
    # Remove quotes if the user accidentally included them in .env
    if (uri.startswith('"') and uri.endswith('"')) or (uri.startswith("'") and uri.endswith("'")):
        uri = uri[1:-1]
        
    if not uri or "://" not in uri:
        return uri
    
    try:
        # Split scheme (mongodb:// or mongodb+srv://)
        scheme_part, rest = uri.split("://", 1)
        scheme = scheme_part + "://"
        
        # Check if credentials exist (before the last '@')
        if "@" not in rest:
            return uri
            
        creds_part, host_part = rest.rsplit("@", 1)
        
        # Improved "already encoded" detection: 
        # Check for % followed by two hex digits
        is_encoded = bool(re.search(r'%[0-9a-fA-F]{2}', creds_part))
        
        # Handle user:password
        if ":" in creds_part:
            user, password = creds_part.split(":", 1)
            safe_user = urllib.parse.quote_plus(user) if not is_encoded else user
            safe_password = urllib.parse.quote_plus(password) if not is_encoded else password
            return f"{scheme}{safe_user}:{safe_password}@{host_part}"
        else:
            # Handle user only
            safe_user = urllib.parse.quote_plus(creds_part) if not is_encoded else creds_part
            return f"{scheme}{safe_user}@{host_part}"
            
    except Exception as e:
        logger.warning(f"Could not safe-encode MongoDB URI: {e}")
        
    return uri

# MongoDB Configuration from environment
MONGO_URI = _get_safe_mongo_uri()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "report_app").strip()

# Connection settings for production reliability
CONNECTION_TIMEOUT_MS = 10000  # 10 seconds
SERVER_SELECTION_TIMEOUT_MS = 10000  # 10 seconds
MAX_POOL_SIZE = 50
MIN_POOL_SIZE = 10

# Initialize MongoDB client with retry logic
MONGO_CONNECTED = False
client = None
db = None

def init_mongo_connection(max_retries=3):
    """Initialize MongoDB connection with retry logic."""
    global client, db, MONGO_CONNECTED
    
    # Diagnostic print (masked password)
    safe_uri_display = MONGO_URI
    if "@" in MONGO_URI:
        parts = MONGO_URI.split("@")
        creds = parts[0].rsplit("/", 1)[-1] if "/" in parts[0] else parts[0]
        if ":" in creds:
            u, p = creds.split(":", 1)
            safe_uri_display = MONGO_URI.replace(p, "****")
        else:
            safe_uri_display = MONGO_URI.replace(creds, "****")
    
    logger.info(f"🔌 Attempting to connect to MongoDB...")
    logger.info(f"🔗 URI (masked): {safe_uri_display}")
    
    for attempt in range(max_retries):
        try:
            client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                connectTimeoutMS=CONNECTION_TIMEOUT_MS,
                maxPoolSize=MAX_POOL_SIZE,
                minPoolSize=MIN_POOL_SIZE,
                retryWrites=True,
                w='majority',
                tlsCAFile=certifi.where()
            )
            # Verify connection
            client.admin.command('ping')
            db = client[MONGO_DB_NAME]
            MONGO_CONNECTED = True
            logger.info(f"✅ MongoDB connected successfully to {MONGO_DB_NAME}")
            return True
        except (ServerSelectionTimeoutError, ConfigurationError) as e:
            logger.warning(f"MongoDB connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt == max_retries - 1:
                logger.error(f"❌ MongoDB connection failed after {max_retries} attempts")
                # Create fallback client without ping verification
                try:
                    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
                    db = client[MONGO_DB_NAME]
                except Exception:
                    pass
                return False
        except Exception as e:
            logger.error(f"Unexpected MongoDB error: {e}")
            return False
    return False

# Initialize on module load
init_mongo_connection()

# Collection references (safely access after init)
def get_db():
    """Get database reference, initializing connection if needed."""
    global db, MONGO_CONNECTED
    if db is None:
        init_mongo_connection()
    return db

def get_collection(name):
    """Get a collection by name."""
    database = get_db()
    if database is not None:
        return database[name]
    return None

# Collection getter functions (safe access)
def get_users_collection():
    """Get users collection safely."""
    return get_collection("users")

def get_downloads_collection():
    """Get report_downloads collection safely."""
    return get_collection("report_downloads")

def get_saved_reports_collection():
    """Get saved_reports collection safely."""
    return get_collection("saved_reports")

# Legacy collection references (for backward compatibility)
# Note: These are evaluated at module load time
downloads_col = get_collection("report_downloads")
saved_reports_col = get_collection("saved_reports")

# Create indexes for performance
def ensure_indexes():
    """Create indexes for optimal query performance."""
    try:
        if downloads_col is not None:
            downloads_col.create_index([("user_email", 1), ("downloaded_at", -1)])
            downloads_col.create_index([("module", 1)])
            downloads_col.create_index([("report_name", 1)])
            downloads_col.create_index([("downloaded_at", -1)])
        if saved_reports_col is not None:
            saved_reports_col.create_index([("user_email", 1), ("created_at", -1)])
            saved_reports_col.create_index([("module", 1), ("report_name", 1)])
        logger.info("✅ MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")

# Ensure indexes on startup
if MONGO_CONNECTED:
    ensure_indexes()


def log_report_download(user_email: str, module: str, report_name: str, filename: str,
                        df_data=None, row_count: int = 0, col_count: int = 0, 
                        file_size: int = 0, metadata: dict = None, sheet_name: str = None):
    """
    Log a report download to MongoDB with full report data.
    
    Args:
        user_email: User who downloaded the report
        module: Module name (e.g., 'amazon', 'flipkart')
        report_name: Human-readable report name
        filename: Downloaded filename with timestamp
        df_data: DataFrame to store (optional, limited to 10K rows)
        row_count: Number of rows in the report
        col_count: Number of columns in the report
        file_size: Size of the downloaded file in bytes
        metadata: Additional metadata dict
        sheet_name: Sheet name for multi-sheet Excel files
    """
    if not MONGO_CONNECTED or downloads_col is None:
        logger.warning("MongoDB not connected, skipping download log")
        return False
        
    try:
        report_data = None
        if df_data is not None:
            try:
                if hasattr(df_data, 'to_dict'):
                    # Limit to 10K rows to avoid document size issues
                    if len(df_data) > 10000:
                        report_data = df_data.head(10000).to_dict(orient='records')
                    else:
                        report_data = df_data.to_dict(orient='records')
                elif isinstance(df_data, list):
                    report_data = df_data[:10000] if len(df_data) > 10000 else df_data
            except Exception as e:
                logger.warning(f"Could not serialize report data: {e}")
                report_data = None
        
        document = {
            "user_email": user_email,
            "module": module,
            "report_name": report_name,
            "file_name": filename,
            "sheet_name": sheet_name,
            "downloaded_at": datetime.now(),
            "metadata": {
                "row_count": row_count,
                "column_count": col_count,
                "file_size_bytes": file_size,
                **(metadata or {})
            }
        }
        
        # Only add report_data if it exists and is not too large
        if report_data:
            document["report_data"] = report_data
        
        downloads_col.insert_one(document)
        logger.info(f"✅ Report logged: {report_name} ({filename})")
        return True
    except Exception as e:
        logger.error(f"MongoDB log error: {e}")
        return False


def log_multi_report_download(user_email: str, module: str, reports: dict, 
                               filename: str, metadata: dict = None):
    """
    Log multiple reports (multi-sheet Excel) to MongoDB.
    
    Args:
        user_email: User who downloaded the report
        module: Module name
        reports: Dict of {sheet_name: DataFrame}
        filename: Downloaded filename
        metadata: Additional metadata
    """
    if not MONGO_CONNECTED:
        return False
    
    success_count = 0
    for sheet_name, df in reports.items():
        try:
            row_count = len(df) if hasattr(df, '__len__') else 0
            col_count = len(df.columns) if hasattr(df, 'columns') else 0
            
            success = log_report_download(
                user_email=user_email,
                module=module,
                report_name=f"{sheet_name}",
                filename=filename,
                df_data=df,
                row_count=row_count,
                col_count=col_count,
                metadata=metadata,
                sheet_name=sheet_name
            )
            if success:
                success_count += 1
        except Exception as e:
            logger.error(f"Error logging report {sheet_name}: {e}")
    
    return success_count == len(reports)


def get_connection_status():
    """Get MongoDB connection status for health checks."""
    return {
        "connected": MONGO_CONNECTED,
        "database": MONGO_DB_NAME,
        "uri_configured": bool(os.getenv("MONGO_URI"))
    }


# =============================================================================
# Module-Specific Report Saving (NEW STRUCTURE)
# =============================================================================

def save_module_report(module_name: str, report_name: str, df_data=None, 
                       user_email: str = None, metadata: dict = None):
    """
    Save a report to a module-specific collection.
    
    Each module has its own collection (e.g., 'stock_movement', 'amazon', 'flipkart').
    Reports are saved by their specific name within the collection.
    
    Args:
        module_name: Module name (becomes collection name, e.g., 'stock_movement')
        report_name: Report name (e.g., 'amazon_business_pivot')
        df_data: DataFrame or list data to save
        user_email: User who generated the report
        metadata: Additional metadata
    
    Returns:
        str: Document ID if successful, None otherwise
    """
    if not MONGO_CONNECTED:
        logger.warning("MongoDB not connected, skipping report save")
        return None
    
    try:
        database = get_db()
        if database is None:
            return None
        
        # Get or create module collection
        collection = database[module_name]
        
        # Prepare report data
        report_data = None
        row_count = 0
        col_count = 0
        
        if df_data is not None:
            try:
                if hasattr(df_data, 'to_dict'):
                    row_count = len(df_data)
                    col_count = len(df_data.columns) if hasattr(df_data, 'columns') else 0
                    # Limit to 10K rows
                    if row_count > 10000:
                        report_data = df_data.head(10000).to_dict(orient='records')
                    else:
                        report_data = df_data.to_dict(orient='records')
                elif isinstance(df_data, list):
                    row_count = len(df_data)
                    report_data = df_data[:10000] if row_count > 10000 else df_data
            except Exception as e:
                logger.warning(f"Could not serialize report data: {e}")
        
        # Create document
        document = {
            "report_name": report_name,
            "generated_at": datetime.now(),
            "generated_by": user_email or "anonymous",
            "row_count": row_count,
            "column_count": col_count,
            "data": report_data,
            "metadata": metadata or {},
            "downloads": []  # Track downloads
        }
        
        result = collection.insert_one(document)
        logger.info(f"✅ Report saved: {report_name} to {module_name} collection")
        return str(result.inserted_id)
        
    except Exception as e:
        logger.error(f"MongoDB save error: {e}")
        return None


def log_download_event(module_name: str, report_id: str, user_email: str, filename: str):
    """
    Log a download event to an existing report document.
    
    Args:
        module_name: Module/collection name
        report_id: MongoDB document ID of the report
        user_email: User who downloaded
        filename: Downloaded filename
    """
    if not MONGO_CONNECTED:
        return False
    
    try:
        from bson import ObjectId
        database = get_db()
        if database is None:
            return False
        
        collection = database[module_name]
        
        download_event = {
            "downloaded_at": datetime.now(),
            "downloaded_by": user_email,
            "filename": filename
        }
        
        collection.update_one(
            {"_id": ObjectId(report_id)},
            {"$push": {"downloads": download_event}}
        )
        
        logger.info(f"📥 Download logged: {filename}")
        return True
        
    except Exception as e:
        logger.error(f"Download log error: {e}")
        return False


def save_and_track_report(module_name: str, report_name: str, df_data=None,
                          user_email: str = None, filename: str = None,
                          is_download: bool = False, metadata: dict = None):
    """
    Combined function to save report and optionally log download.
    
    Use this when user clicks download button - it saves the report 
    and logs the download event in one call.
    
    Args:
        module_name: Module/collection name
        report_name: Report name
        df_data: DataFrame data
        user_email: User email
        filename: Download filename
        is_download: If True, also log download event
        metadata: Additional metadata
    
    Returns:
        bool: True if successful
    """
    # Save the report
    report_id = save_module_report(
        module_name=module_name,
        report_name=report_name,
        df_data=df_data,
        user_email=user_email,
        metadata=metadata
    )
    
    if not report_id:
        return False
    
    # If this is a download, log the download event
    if is_download and filename:
        log_download_event(
            module_name=module_name,
            report_id=report_id,
            user_email=user_email or "anonymous",
            filename=filename
        )
    
    return True


def get_module_reports(module_name: str, limit: int = 50):
    """
    Get recent reports from a module collection.
    
    Args:
        module_name: Module/collection name
        limit: Maximum number of reports to return
    
    Returns:
        list: List of report documents (without full data)
    """
    if not MONGO_CONNECTED:
        return []
    
    try:
        database = get_db()
        if database is None:
            return []
        
        collection = database[module_name]
        
        # Get reports without the full data field for performance
        reports = list(collection.find(
            {},
            {"data": 0}  # Exclude data field
        ).sort("generated_at", -1).limit(limit))
        
        return reports
        
    except Exception as e:
        logger.error(f"Error fetching reports: {e}")
        return []