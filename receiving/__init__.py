from flask import Blueprint

receiving_bp = Blueprint("receiving", __name__)

from . import routes