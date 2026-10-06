import re
import unicodedata


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def format_usd(amount: float | None) -> str:
    if not amount:
        return "undisclosed"
    for value, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if amount >= value:
            return f"${amount / value:.1f}{suffix}".replace(".0", "")
    return f"${amount:,.0f}"
