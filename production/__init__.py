from flask import Blueprint

production_bp = Blueprint("production", __name__, url_prefix="/production")

from . import routes