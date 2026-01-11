from common.mongo import _get_safe_mongo_uri, MONGO_URI, MONGO_DB_NAME
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

def debug():
    raw_uri = os.getenv("MONGO_URI", "Not Set")
    encoded_uri = _get_safe_mongo_uri()
    
    print("--- MongoDB Debug Info ---")
    print(f"Raw URI (from .env): {raw_uri[:15]}... (length: {len(raw_uri)})")
    
    # Masking for safety
    if "@" in encoded_uri:
        masked = encoded_uri.split("@")[0].split("://")[-1]
        if ":" in masked:
            u, p = masked.split(":", 1)
            display = encoded_uri.replace(p, "****")
            print(f"Encoded URI (masked): {display}")
        else:
            print(f"Encoded URI: (no credentials found or user only)")
    else:
        print(f"Encoded URI: {encoded_uri}")
        
    print(f"Database: {MONGO_DB_NAME}")
    
    try:
        print("\nAttempting connection test...")
        client = MongoClient(encoded_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("✅ SUCCESS: Connected to MongoDB!")
    except Exception as e:
        print(f"❌ FAILURE: {e}")

if __name__ == "__main__":
    debug()
