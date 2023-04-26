def build_server_url(url: str) -> str:
    HTTPS_PROTOCOL = 'https://'
    if not url.startswith(HTTPS_PROTOCOL):
        url = HTTPS_PROTOCOL + url
    if not url.endswith('/'):
        url += '/'
    return url
