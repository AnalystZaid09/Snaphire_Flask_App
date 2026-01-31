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
import pandas as pd

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
    
    # Detect if this is a localhost/local connection
    is_local = any(x in MONGO_URI.lower() for x in ["localhost", "127.0.0.1", "0.0.0.0"])
    
    for attempt in range(max_retries):
        try:
            # Check if we should allow invalid certificates (for machines with SSL issues)
            allow_invalid_tls = os.getenv("MONGO_TLS_ALLOW_INVALID", "false").lower() == "true"
            
            # Build connection options
            connection_options = {
                "serverSelectionTimeoutMS": SERVER_SELECTION_TIMEOUT_MS,
                "connectTimeoutMS": CONNECTION_TIMEOUT_MS,
                "maxPoolSize": MAX_POOL_SIZE,
                "minPoolSize": MIN_POOL_SIZE
            }
            
            # Only add SSL options for non-local connections (e.g., MongoDB Atlas)
            if not is_local and "mongodb+srv" in MONGO_URI:
                connection_options["tlsCAFile"] = certifi.where()
                connection_options["retryWrites"] = True
                connection_options["w"] = "majority"
                if allow_invalid_tls:
                    connection_options["tlsAllowInvalidCertificates"] = True
            
            client = MongoClient(MONGO_URI, **connection_options)
            
            # Verify connection
            client.admin.command('ping')
            db = client[MONGO_DB_NAME]
            MONGO_CONNECTED = True
            logger.info(f"✅ MongoDB connected successfully to {MONGO_DB_NAME}")
            return True
        except ServerSelectionTimeoutError as e:
            logger.warning(f"MongoDB connection timeout {attempt + 1}/{max_retries}: {e}")
        except ConfigurationError as e:
            logger.error(f"MongoDB configuration error (check URI): {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected MongoDB error during connect: {e}")
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
    
def refresh_mongo_config():
    """Reload environment and reconnect to MongoDB."""
    global MONGO_URI, MONGO_DB_NAME, MONGO_CONNECTED, client, db
    load_dotenv(override=True)
    MONGO_URI = _get_safe_mongo_uri()
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "report_app").strip()
    
    # Reset existing connection
    if client:
        try:
            client.close()
        except:
            pass
    client = None
    db = None
    MONGO_CONNECTED = False
    
    return init_mongo_connection()

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

def get_download_history_collection():
    """Get download_history collection safely."""
    return get_collection("download_history")

# Legacy collection references (for backward compatibility)
# Note: These are evaluated at module load time
downloads_col = get_collection("report_downloads")
saved_reports_col = get_collection("saved_reports")
history_col = get_collection("download_history")

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


from datetime import datetime, date

def _serialize_for_mongo(obj):
    """Recursively convert datetime.date objects to datetime.datetime for MongoDB."""
    if isinstance(obj, dict):
        return {k: _serialize_for_mongo(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_mongo(item) for item in obj]
    elif isinstance(obj, date) and not isinstance(obj, datetime):
        return datetime(obj.year, obj.month, obj.day)
    return obj

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
                    # Limit to 5K rows to avoid document size issues (BSON 16MB limit)
                    if len(df_data) > 5000:
                        report_data = df_data.head(5000).to_dict(orient='records')
                    else:
                        report_data = df_data.to_dict(orient='records')
                elif isinstance(df_data, list):
                    report_data = df_data[:5000] if len(df_data) > 5000 else df_data
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
            document["report_data"] = _serialize_for_mongo(report_data)
        
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
    Save a report to a module-specific collection with structured data.
    """
    if not MONGO_CONNECTED:
        return None
    
    try:
        database = get_db()
        if database is None: return None
        
        collection = database[module_name]
        
        # Convert to structured records
        report_data = None
        row_count = 0
        if df_data is not None:
            if hasattr(df_data, 'to_dict'):
                row_count = len(df_data)
                # Cap at 5K rows for safety
                report_data = df_data.head(5000).to_dict(orient='records')
            elif isinstance(df_data, list):
                row_count = len(df_data)
                report_data = df_data[:5000]
        
        document = {
            "report_name": report_name,
            "generated_at": datetime.now(),
            "generated_by": user_email or "anonymous",
            "row_count": row_count,
            "data": report_data,
            "metadata": metadata or {},
            "downloads": []
        }
        
        document = _serialize_for_mongo(document)
        result = collection.insert_one(document)
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error saving module report: {e}")
        return None

def save_reconciliation_report(collection_name: str, invoice_no: str, 
                               summary_data, line_items_data, metadata: dict = None):
    """
    Structured dump for reconciliation reports.
    Saves both summary levels and detailed comparison lines.
    """
    if not MONGO_CONNECTED:
        return None
        
    try:
        database = get_db()
        if database is None: return None
        collection = database[collection_name]
        
        # Structure the data
        summary = summary_data.to_dict(orient='records') if hasattr(summary_data, 'to_dict') else summary_data
        lines = line_items_data.to_dict(orient='records') if hasattr(line_items_data, 'to_dict') else line_items_data
        
        document = {
            "invoice_no": invoice_no,
            "generated_at": datetime.now(),
            "summary": summary,
            "line_items": lines[:5000] if isinstance(lines, list) else lines, # Limit for size
            "metadata": metadata or {},
            "type": "reconciliation"
        }
        
        document = _serialize_for_mongo(document)
        result = collection.insert_one(document)
        logger.info(f"✅ Reconciliation report dumped: {invoice_no}")
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error dumping reconciliation report: {e}")
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


# =============================================================================
# Enhanced Report Saving with Tool Name Support (NEW)
# =============================================================================

def get_report_registry_collection():
    """Get the report_registry collection for centralized tracking."""
    return get_collection("report_registry")


def register_report_info(
    module_name: str,
    tool_name: str,
    report_name: str,
    report_id: str = None,
    user_email: str = None,
    filename: str = None,
    row_count: int = 0,
    metadata: dict = None
) -> bool:
    """
    Register report info in the centralized report_registry collection.
    This provides a lightweight lookup for all reports across modules.
    
    Args:
        module_name: Module name (amazon, flipkart, reconciliation, etc.)
        tool_name: Tool name (amazon_sales_report, flipkart_oos, etc.)
        report_name: Human-readable report name
        report_id: Reference to full report in module collection (optional)
        user_email: User who generated the report
        filename: Downloaded filename
        row_count: Number of rows in the report
        metadata: Additional metadata
    
    Returns:
        bool: True if successful
    """
    if not MONGO_CONNECTED:
        logger.warning("MongoDB not connected, skipping report registry")
        return False
    
    try:
        registry = get_report_registry_collection()
        if registry is None:
            return False
        
        document = {
            "module_name": module_name,
            "tool_name": tool_name,
            "report_name": report_name,
            "report_id": report_id,
            "generated_at": datetime.now(),
            "generated_by": user_email or "anonymous",
            "row_count": row_count,
            "filename": filename,
            "metadata": metadata or {}
        }
        
        registry.insert_one(document)
        logger.info(f"📋 Report registered: {module_name}/{tool_name}/{report_name}")
        return True
        
    except Exception as e:
        logger.error(f"Report registry error: {e}")
        return False


def save_report_with_tracking(
    module_name: str,
    tool_name: str,
    report_name: str,
    df_data=None,
    user_email: str = None,
    filename: str = None,
    metadata: dict = None
) -> str:
    """
    Save a report to module collection AND register in central registry.
    
    This is the primary function to use for saving reports. It:
    1. Saves full report data to the module-specific collection
    2. Registers lightweight info in report_registry for centralized tracking
    
    Args:
        module_name: Module name (amazon, flipkart, reconciliation, etc.)
        tool_name: Tool name (amazon_sales_report, flipkart_oos, etc.)
        report_name: Human-readable report name
        df_data: DataFrame or list data to save
        user_email: User who generated the report
        filename: Downloaded filename
        metadata: Additional metadata
    
    Returns:
        str: Report ID if successful, None otherwise
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
        
        # Convert DataFrame to records
        report_data = None
        row_count = 0
        col_count = 0
        
        if df_data is not None:
            if hasattr(df_data, 'to_dict'):
                row_count = len(df_data)
                col_count = len(df_data.columns) if hasattr(df_data, 'columns') else 0
                # Cap at 5K rows for MongoDB document size limit
                report_data = df_data.head(5000).to_dict(orient='records')
            elif isinstance(df_data, list):
                row_count = len(df_data)
                report_data = df_data[:5000]
        
        # Create document for module collection
        document = {
            "tool_name": tool_name,
            "report_name": report_name,
            "generated_at": datetime.now(),
            "generated_by": user_email or "anonymous",
            "row_count": row_count,
            "column_count": col_count,
            "data": report_data,
            "metadata": metadata or {},
            "downloads": []
        }
        
        # Insert to module collection
        result = collection.insert_one(document)
        report_id = str(result.inserted_id)
        
        logger.info(f"✅ Report saved: {module_name}/{tool_name}/{report_name} (ID: {report_id})")
        
        # Register in central registry
        register_report_info(
            module_name=module_name,
            tool_name=tool_name,
            report_name=report_name,
            report_id=report_id,
            user_email=user_email,
            filename=filename,
            row_count=row_count,
            metadata=metadata
        )
        
        return report_id
        
    except Exception as e:
        logger.error(f"Error saving report with tracking: {e}")
        return None


def get_report_registry(
    module_name: str = None,
    tool_name: str = None,
    limit: int = 100,
    start_date: datetime = None,
    end_date: datetime = None
) -> list:
    """
    Query the report registry for tracking information.
    
    Args:
        module_name: Filter by module (optional)
        tool_name: Filter by tool (optional)
        limit: Maximum number of results
        start_date: Filter by start date (optional)
        end_date: Filter by end date (optional)
    
    Returns:
        list: List of registry entries
    """
    if not MONGO_CONNECTED:
        return []
    
    try:
        registry = get_report_registry_collection()
        if registry is None:
            return []
        
        # Build query
        query = {}
        if module_name:
            query["module_name"] = module_name
        if tool_name:
            query["tool_name"] = tool_name
        if start_date or end_date:
            query["generated_at"] = {}
            if start_date:
                query["generated_at"]["$gte"] = start_date
            if end_date:
                query["generated_at"]["$lte"] = end_date
        
        results = list(registry.find(query).sort("generated_at", -1).limit(limit))
        return results
        
    except Exception as e:
        logger.error(f"Error querying report registry: {e}")
        return []


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

def get_report_data(module_name: str, report_id: str) -> pd.DataFrame:
    """
    Fetch the full data for a specific report and return as DataFrame.
    """
    if not MONGO_CONNECTED:
        return pd.DataFrame()
    
    try:
        from bson import ObjectId
        database = get_db()
        if database is None:
            return pd.DataFrame()
        
        collection = database[module_name]
        report = collection.find_one({"_id": ObjectId(report_id)})
        
        if not report:
            return pd.DataFrame()
            
        # Handle regular report data
        if "data" in report:
            return pd.DataFrame(report["data"])
        # Handle reconciliation summary data
        elif "summary" in report:
            return pd.DataFrame(report["summary"])
            
        return pd.DataFrame()
        
    except Exception as e:
        logger.error(f"Error fetching report data: {e}")
        return pd.DataFrame()

def get_module_list() -> list:
    """
    Get list of all modules that have saved reports in the registry.
    """
    if not MONGO_CONNECTED:
        return []
        
    try:
        registry = get_report_registry_collection()
        if registry is None:
            return []
            
        return sorted(registry.distinct("module_name"))
    except Exception as e:
        logger.error(f"Error getting module list: {e}")
        return []
