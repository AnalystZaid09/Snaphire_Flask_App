"""
Verify MongoDB collections and recent data.
"""
import certifi
from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv('MONGO_URI')
client = MongoClient(uri, tlsCAFile=certifi.where())
db = client['report_app']

# List all collections
print("=" * 60)
print(f"📂 COLLECTIONS IN DATABASE: {db.name}")
print("=" * 60)
for col_name in db.list_collection_names():
    count = db[col_name].count_documents({})
    print(f"  {col_name}: {count} documents")

# Show download_history (lightweight download tracking)
print("\n" + "=" * 60)
print("📥 DOWNLOAD HISTORY (Lightweight)")
print("=" * 60)

history_count = db.download_history.count_documents({})
if history_count == 0:
    print("  No downloads yet. Note: Downloads are only logged when a user clicks a Download button.")
else:
    print(f"  Showing last 10 of {history_count} downloads:")
    for doc in db.download_history.find().sort('downloaded_at', -1).limit(10):
        dt = doc.get('downloaded_at')
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt, datetime) else str(dt)
        print(f"\n  📄 {doc.get('report_name', 'N/A')}")
        print(f"     Tool: {doc.get('tool_name', 'N/A')}")
        print(f"     Module: {doc.get('module_name', 'N/A')}")
        print(f"     User: {doc.get('user_email', 'N/A')}")
        print(f"     Time: {dt_str}")

# Show report_downloads (full reports with data)
print("\n" + "=" * 60)
print("📊 REPORT_DOWNLOADS (Full Reports with Data)")
print("=" * 60)

reports_count = db.report_downloads.count_documents({})
print(f"  Total reports: {reports_count}")

if reports_count > 0:
    print("\n  Recent 10 reports:")
    for doc in db.report_downloads.find().sort('downloaded_at', -1).limit(10):
        report_name = doc.get('report_name', 'N/A')
        module = doc.get('module', 'N/A')
        metadata = doc.get('metadata', {})
        tool_name = metadata.get('tool_name', 'Not recorded')
        dt = doc.get('downloaded_at')
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt, datetime) else str(dt)
        print(f"    - {dt_str} | {report_name} ({module}) [Tool: {tool_name}]")
