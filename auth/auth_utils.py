import bcrypt
from common.mongo import get_collection, get_users_collection, MONGO_CONNECTED


def hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


def verify_password(password, hashed):
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode(), hashed)


def authenticate_user(email, password):
    """
    Authenticate user with email and password.
    
    Returns:
        User document if authenticated, None otherwise.
        Returns None if MongoDB is not connected.
    """
    # Get users collection with null safety
    users_col = get_users_collection()
    
    if users_col is None:
        # MongoDB not connected - cannot authenticate
        return None
    
    try:
        user = users_col.find_one({"email": email})
        if not user:
            return None
        if verify_password(password, user["password"]):
            return user
        return None
    except Exception as e:
        # Log error but don't crash
        print(f"Authentication error: {e}")
        return None
