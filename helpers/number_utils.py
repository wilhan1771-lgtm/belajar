def to_float(v, default=0.0):
    if v is None:
        return default

    if isinstance(v, str):
        v = v.replace(",", ".").strip()
        if v == "":
            return default

    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def to_int(v, default=None):
    if v is None:
        return default

    if isinstance(v, str):
        v = v.strip()
        if v == "":
            return default

    try:
        return int(v)
    except (ValueError, TypeError):
        return default
