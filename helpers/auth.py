
from flask import session, redirect, url_for

def require_login():
    return session.get("user") is not None

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
