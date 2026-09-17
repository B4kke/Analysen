from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() not in TRACKING_KEYS and not k.casefold().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))
