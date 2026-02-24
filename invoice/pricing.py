def div_round(n, d):
    if d <= 0:
        raise ValueError("d must be > 0")
    if n >= 0:
        return (n + d // 2) // d
    return -((-n + d // 2) // d)

def interpolate_price(size, points):
    """
    points: {60:60000, 70:55000}
    size: 65 -> 57500
    """
    if size is None:
        return None
    try:
        size = int(size)
    except (TypeError, ValueError):
        return None

    pts = {}
    for k, v in points.items():
        if v is None or str(v).strip() == "":
            continue
        try:
            pts[int(k)] = int(v)
        except (TypeError, ValueError):
            pass

    if size in pts:
        return pts[size]

    lo = (size // 10) * 10
    hi = lo + 10
    if lo not in pts or hi not in pts:
        return None

    p_lo = pts[lo]
    p_hi = pts[hi]

    num = (p_lo - p_hi) * (size - lo)  # integer
    adj = div_round(num, 10)           # round
    return p_lo - adj