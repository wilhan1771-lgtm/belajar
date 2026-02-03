def interpolate_price(size: int | None, points: dict) -> int | None:
    """
    points contoh: {40:65000, 50:60000, 60:55000, 70:52000}
    size contoh: 54 -> hitung dari 50 & 60
    """
    if size is None:
        return None

    try:
        size = int(size)
    except (TypeError, ValueError):
        return None

    # only keep valid numeric points
    pts: dict[int, int] = {}
    for k, v in points.items():
        if v is None:
            continue
        if str(v).strip() == "":
            continue
        try:
            pts[int(k)] = int(v)
        except (TypeError, ValueError):
            pass

    if size in pts:
        return pts[size]

    lo = (size // 10) * 10
    hi = lo + 10

    if lo in pts and hi in pts:
        p_lo = pts[lo]
        p_hi = pts[hi]
        step = (p_lo - p_hi) / 10.0
        price = p_lo - step * (size - lo)
        return int(round(price))

    return None

