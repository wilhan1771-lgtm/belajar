from flask import Blueprint

invoice_bp = Blueprint("invoice",__name__)

from . import routes  # WAJIB supaya route terdaftar