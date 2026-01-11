"""
Create Admin User Script for IBI Reporting Application.
Run this script to create an initial admin user in MongoDB.

Usage: python create_admin.py
"""

from common.mongo import get_collection, MONGO_CONNECTED
from auth.auth_utils import hash_password

# Check MongoDB connection
if not MONGO_CONNECTED:
    print("❌ MongoDB not connected!")
    print("   Please check your .env file and ensure MONGO_URI is configured correctly.")
    print("   Run 'python test_mongo_connection.py' to diagnose connection issues.")
    exit(1)

# Get users collection
users_col = get_collection("users")

if users_col is None:
    print("❌ Could not access users collection")
    exit(1)

# Check if admin already exists
existing_admin = users_col.find_one({"email": "admin@test.com"})
if existing_admin:
    print("⚠️ Admin user already exists!")
    print("   Email: admin@test.com")
    exit(0)

# Create admin user
try:
    users_col.insert_one({
        "email": "admin@test.com",
        "password": hash_password("admin123"),
        "role": "admin"
    })
    print("✅ Admin user created successfully!")
    print("   Email: admin@test.com")
    print("   Password: admin123")
    print("   ⚠️ Change the password after first login!")
except Exception as e:
    print(f"❌ Error creating admin user: {e}")
    exit(1)
