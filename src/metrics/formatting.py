def format_int(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def format_compact(value) -> str:
    return format_int(value)


def initials(name) -> str:
    cleaned = "".join(part[0] for part in str(name).replace("_", " ").split() if part)
    return (cleaned[:2] or "BR").upper()
