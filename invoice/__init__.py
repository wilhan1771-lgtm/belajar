from flask import Blueprint

invoice_bp = Blueprint("invoice", __name__, url_prefix="/invoice")

from . import routes