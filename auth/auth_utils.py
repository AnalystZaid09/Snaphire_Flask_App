import bcrypt
from common.mongo import users_col

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed)

def authenticate_user(email, password):
    user = users_col.find_one({"email": email})
    if not user:
        return None
    if verify_password(password, user["password"]):
        return user
    return None
