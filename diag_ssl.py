from pymongo import MongoClient
import os
import ssl
from dotenv import load_dotenv
import urllib.parse
import re

load_dotenv(override=True)

def _get_safe_mongo_uri():
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri or "://" not in uri: return uri
    try:
        scheme_part, rest = uri.split("://", 1)
        scheme = scheme_part + "://"
        if "@" not in rest: return uri
        creds_part, host_part = rest.rsplit("@", 1)
        is_encoded = "%" in creds_part
        if ":" in creds_part:
            user, password = creds_part.split(":", 1)
            safe_user = urllib.parse.quote_plus(user) if not is_encoded else user
            safe_password = urllib.parse.quote_plus(password) if not is_encoded else password
            return f"{scheme}{safe_user}:{safe_password}@{host_part}"
    except: pass
    return uri

def test_no_ssl():
    uri = _get_safe_mongo_uri()
    print(f"Testing connection to: {uri.split('@')[-1]}")
    
    try:
        print("\n--- Test 1: Standard Connection ---")
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("✅ Success: Standard connection works!")
    except Exception as e:
        print(f"❌ Standard connection failed: {e}")

    try:
        print("\n--- Test 2: Connection with SSL verification disabled ---")
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, tlsAllowInvalidCertificates=True)
        client.admin.command('ping')
        print("✅ Success: Connection works without SSL verification!")
    except Exception as e:
        print(f"❌ Connection failed even without SSL verification: {e}")

if __name__ == "__main__":
    test_no_ssl()
