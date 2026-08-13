UNITS = ("B", "KB", "MB", "GB", "TB")


def clock(seconds: float) -> str:
    """Seconds as m:ss, or h:mm:ss once it runs past an hour."""
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"


def bytes_size(count: int) -> str:
    """Bytes in the largest unit they fill, to one decimal until the number is wide on its own."""
    size = float(max(0, count))
    for unit in UNITS:
        if size < 1024 or unit == UNITS[-1]:
            return f"{size:.0f} {unit}" if unit == "B" or size >= 100 else f"{size:.1f} {unit}"
        size /= 1024
    return f"{count} B"
