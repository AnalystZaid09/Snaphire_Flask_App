"""
Database Initialization Script for IBI Reporting App.
Configures MongoDB collections and indexes based on MONGODB_SCHEMA.md.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Load environment
load_dotenv(override=True)

def initialize_database():
    """Create collections and indexes as per MONGODB_SCHEMA.md."""
    
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "report_app")
    
    logger.info(f"🚀 Initializing Database: {db_name}")
    
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        # Ping to verify connection
        client.admin.command('ping')
        db = client[db_name]
        logger.info("✅ Connected to MongoDB")
        
        # 1. Initialize Users Collection
        logger.info("Creating 'users' structure...")
        users = db["users"]
        try:
            users.create_index([("email", 1)], unique=True)
        except Exception as ex:
            logger.warning(f"⚠️ Could not create unique index on users.email: {ex}")
            logger.info("Proceeding with other collections...")
        
        # 2. Initialize Report Registry (The Central Hub)
        logger.info("Creating 'report_registry' structure...")
        registry = db["report_registry"]
        registry.create_index([("module_name", 1), ("tool_name", 1)])
        registry.create_index([("generated_at", -1)])
        registry.create_index([("generated_by", 1)])
        
        # 3. Initialize Legacy Download Logs
        logger.info("Creating 'report_downloads' structure...")
        downloads = db["report_downloads"]
        downloads.create_index([("user_email", 1), ("downloaded_at", -1)])
        downloads.create_index([("module", 1)])
        downloads.create_index([("downloaded_at", -1)])
        
        # 4. Initialize Module-Specific Collections
        modules = [
            "amazon", 
            "flipkart", 
            "reconciliation", 
            "leakagereconciliation", 
            "stockmovement"
        ]
        
        for module in modules:
            logger.info(f"Creating module collection: '{module}'...")
            col = db[module]
            # Standard indexes for modules
            col.create_index([("tool_name", 1)])
            col.create_index([("report_name", 1)])
            col.create_index([("generated_at", -1)])
            col.create_index([("generated_by", 1)])
            
        logger.info("---")
        logger.info("🏆 Database structure initialized successfully!")
        logger.info(f"Database: {db_name}")
        logger.info(f"Collections configured: {len(modules) + 3}")
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    
    return True

if __name__ == "__main__":
    if initialize_database():
        print("\nSUCCESS: Your MongoDB database is now ready with the correct structure.")
    else:
        print("\nFAILURE: Could not initialize database. Check your MONGO_URI in .env.")
