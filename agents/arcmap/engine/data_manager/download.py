from pathlib import Path
from urllib.request import Request, urlopen
from .path_guard import ensure_writable

def download(url, output_path, user_agent="ZagentArcMap/3.0", timeout=60):
    output = ensure_writable(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": user_agent})
    with urlopen(req, timeout=timeout) as response, output.open("wb") as fh:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    return str(output)
