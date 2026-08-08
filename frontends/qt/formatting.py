def clock(seconds: float) -> str:
    """Seconds as m:ss, or h:mm:ss once it runs past an hour."""
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"
