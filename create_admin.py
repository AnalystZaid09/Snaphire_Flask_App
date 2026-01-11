from common.mongo import users_col
from auth.auth_utils import hash_password

users_col.insert_one({
    "email": "admin@test.com",
    "password": hash_password("admin123"),
    "role": "admin"
})

print("✅ Admin user created successfully")
