"""
Quick script to check MongoDB connection and report status.
"""
import os
from dotenv import load_dotenv
load_dotenv(override=True)

try:
    import certifi
    from pymongo import MongoClient
    
    uri = os.getenv("MONGO_URI", "")
    db_name = os.getenv("MONGO_DB_NAME", "report_app")
    
    print(f"URI configured: {bool(uri and 'mongodb' in uri)}")
    print(f"DB Name: {db_name}")
    
    if uri:
        print("\nAttempting MongoDB connection...")
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            tlsCAFile=certifi.where()
        )
        
        # Ping to verify connection
        client.admin.command('ping')
        print("✅ MongoDB connection successful!")
        
        # Check database
        db = client[db_name]
        
        # List collections
        collections = db.list_collection_names()
        print(f"\nCollections in '{db_name}':")
        for col in collections:
            print(f"  - {col}")
        
        # Check report_downloads collection
        downloads = db["report_downloads"]
        count = downloads.count_documents({})
        print(f"\n📊 report_downloads count: {count}")
        
        # Show recent 3 documents
        if count > 0:
            print("\nRecent reports:")
            for doc in downloads.find().sort("downloaded_at", -1).limit(3):
                print(f"  - {doc.get('report_name', 'N/A')} ({doc.get('module', 'N/A')}) at {doc.get('downloaded_at', 'N/A')}")
        else:
            print("\n⚠️ No reports found in collection!")
            
        # Test inserting a document
        print("\n🧪 Testing insert...")
        from datetime import datetime
        test_doc = {
            "test": True,
            "created_at": datetime.now(),
            "message": "Test document - can be deleted"
        }
        result = db["test_collection"].insert_one(test_doc)
        print(f"✅ Test insert successful! ID: {result.inserted_id}")
        
        # Clean up test
        db["test_collection"].delete_one({"_id": result.inserted_id})
        print("✅ Test document cleaned up")
        
    else:
        print("❌ MONGO_URI not configured!")
        
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
