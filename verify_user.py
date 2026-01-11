from common.mongo import get_collection, MONGO_CONNECTED
import os
from dotenv import load_dotenv

load_dotenv(override=True)

def verify():
    if not MONGO_CONNECTED:
        print("❌ MongoDB not connected. Please check your .env")
        return

    users_col = get_collection("users")
    if users_col is None:
        print("❌ Could not access 'users' collection.")
        return

    print("--- User Verification ---")
    user = users_col.find_one({"email": "admin@test.com"})
    if user:
        print("✅ Found user: admin@test.com")
        print(f"   Role: {user.get('role')}")
        print(f"   Has hashed password: {'Yes' if 'password' in user else 'No'}")
    else:
        print("❌ User 'admin@test.com' NOT found in database.")
        
    # Also check for just 'admin' if they tried that
    user_short = users_col.find_one({"email": "admin"})
    if user_short:
        print("✅ Found user: admin")
    else:
        print("ℹ️ User 'admin' (shortname) not found.")

if __name__ == "__main__":
    verify()
