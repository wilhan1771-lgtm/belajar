# helpers/auth.py
from flask import session, redirect, url_for

def require_login():
    """
    Mengecek apakah user sudah login.
    Return True kalau login, False kalau tidak.
    """
    return session.get("user_id") is not None

def login_required(func):
    """
    Decorator untuk route yang membutuhkan login.
    """
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not require_login():
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper
