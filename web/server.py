from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8710

if __name__ == "__main__":
    os.chdir(ROOT)
    print(f"[web] listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), SimpleHTTPRequestHandler).serve_forever()
