import re
import unicodedata


def company_name_key(name: str) -> str:
    """Find potential duplicates; this is not legal-entity verification."""
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"\(주\)|㈜|주식회사|\s+", "", normalized)
