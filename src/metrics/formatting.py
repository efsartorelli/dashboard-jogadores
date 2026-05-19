def format_int(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def format_compact(value) -> str:
    value = int(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B".replace(".", ",")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".", ",")
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def initials(name) -> str:
    cleaned = "".join(part[0] for part in str(name).replace("_", " ").split() if part)
    return (cleaned[:2] or "BR").upper()
