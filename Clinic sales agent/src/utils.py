from datetime import datetime


def log(message: str):
    import sys
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'), flush=True)


def normalize_url(url: str) -> str:
    if not url:
        return ''
    return url.strip().split('#')[0].rstrip('/')
