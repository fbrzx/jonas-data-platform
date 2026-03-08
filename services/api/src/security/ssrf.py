"""SSRF (Server-Side Request Forgery) protection utilities.

Use `check_url` before making any outbound HTTP request whose URL is
derived from user input or connector configuration.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse


def check_url(url: str) -> str | None:
    """Return an error string if the URL targets a private/internal address, else None.

    Validates both the initially resolved IP and must be called again inside any
    redirect handler — never use with follow_redirects=True.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return "Only http/https URLs are supported"

    hostname = parsed.hostname or ""
    if not hostname:
        return "Invalid URL: missing hostname"

    try:
        ip_str = socket.gethostbyname(hostname)
        addr = ipaddress.ip_address(ip_str)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return "Access to private/internal/loopback addresses is not permitted."
    except socket.gaierror:
        return f"Could not resolve hostname: {hostname!r}"
    except ValueError:
        pass  # non-standard IP string; let httpx handle it

    return None
