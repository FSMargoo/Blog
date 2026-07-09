#!/usr/bin/env python3
"""
Local preview server with live reload for the blog.

Builds the site (unless --no-build) and serves public/ over HTTP.
Use --watch to auto-rebuild when source files change.
Injects a live-reload script into HTML pages — browser auto-refreshes
when a rebuild completes.

Usage:
    python serve.py                 # build + serve on :8000
    python serve.py --no-build      # serve existing public/ only
    python serve.py -w              # build, serve, auto-rebuild + live reload
    python serve.py -p 3000 -w -v   # custom port + watch + verbose logging
"""

import argparse
import http.server
import json
import os
import queue
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

# ------------------------------------------------------------------ #
# Paths
# ------------------------------------------------------------------ #
ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"

WATCH_DIRS = [
    ROOT / "content",
    ROOT / "templates",
    ROOT / "static",
]
WATCH_FILES = [
    ROOT / "config.yaml",
]
BUILD_LOCK = threading.Lock()

# ------------------------------------------------------------------ #
# Live Reload (SSE)
# ------------------------------------------------------------------ #
LIVE_RELOAD_SCRIPT = b"""
<script>
(function(){var s=new EventSource('/__sse__');s.onmessage=function(e){if(e.data==='reload')location.reload()}})()
</script>
"""


class LiveReload:
    """Manages SSE clients for live reload."""

    def __init__(self):
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    def add_client(self):
        q = queue.Queue()
        with self._lock:
            self._clients.append(q)
        return q

    def remove_client(self, q):
        with self._lock:
            self._clients.remove(q)

    def notify_reload(self):
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait("reload")
                except queue.Full:
                    pass


LIVE = LiveReload()

# ------------------------------------------------------------------ #
# Build
# ------------------------------------------------------------------ #


def build_site() -> bool:
    """Run build.py as a subprocess. Returns True on success."""
    if not BUILD_LOCK.acquire(blocking=False):
        print("[build] Build already running; skipping duplicate request.")
        return False

    try:
        print("[build] Running build.py...")
        result = subprocess.run(
            [sys.executable, "-u", str(ROOT / "build.py"), "--no-pdf"],
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            print("[build] Build failed!")
            return False
        print("[build] Build complete")
        LIVE.notify_reload()
        return True
    finally:
        BUILD_LOCK.release()


# ------------------------------------------------------------------ #
# HTTP handler
# ------------------------------------------------------------------ #


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves public/ with quiet logging + live reload injection + SSE."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", True):
            if args and args[0] in ("200", "304"):
                return
        color = ""
        if args:
            code = args[0]
            if code[0] == "2":
                color = "\033[32m"
            elif code[0] in ("4", "5"):
                color = "\033[31m"
            elif code[0] == "3":
                color = "\033[33m"
        sys.stdout.write(f"  {color}{args[0]}\033[0m {args[1]}\n" if args else "")

    # ---- SSE endpoint ----
    def do_GET(self):
        if self.path == "/__sse__":
            self._handle_sse()
        else:
            super().do_GET()

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = LIVE.add_client()
        try:
            # Send initial comment to establish connection
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Keep-alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            LIVE.remove_client(q)

    # ---- Inject live-reload script into HTML responses ----
    def do_GET(self):
        """Override to handle SSE and inject live-reload into HTML."""
        if self.path == "/__sse__":
            self._handle_sse()
            return

        # Resolve path
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")

        # Only inject into HTML files
        if not path.endswith(".html"):
            return super().do_GET()

        # Serve HTML with live-reload injection
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(404, "File not found")
            return

        if data.startswith(b"<!DOCTYPE") or data.startswith(b"<html") or b"</body>" in data:
            data = data.replace(b"</body>", LIVE_RELOAD_SCRIPT + b"</body>")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ------------------------------------------------------------------ #
# File watcher (polling)
# ------------------------------------------------------------------ #


class FileWatcher:
    """Polling-based file watcher for --watch mode."""

    def __init__(self, callback, interval=1.5):
        self.callback = callback
        self.interval = interval
        self._mtimes = {}
        self._running = False

    def _collect_paths(self):
        paths = set()
        for d in WATCH_DIRS:
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file() and not any(part.startswith(".") for part in f.parts):
                        paths.add(str(f))
        for f in WATCH_FILES:
            if f.exists():
                paths.add(str(f))
        return paths

    def _snapshot(self):
        snap = {}
        for p in self._collect_paths():
            try:
                snap[p] = os.path.getmtime(p)
            except OSError:
                pass
        return snap

    def start(self):
        self._mtimes = self._snapshot()
        self._running = True
        print(
            f"[watch] Watching {len(WATCH_DIRS)} dirs + "
            f"{len(WATCH_FILES)} files for changes..."
        )
        print("[watch] Press Ctrl+C to stop.\n")
        try:
            while self._running:
                time.sleep(self.interval)
                current = self._snapshot()
                if current != self._mtimes:
                    all_keys = set(current.keys()) | set(self._mtimes.keys())
                    changed = []
                    for k in all_keys:
                        old_mt = self._mtimes.get(k)
                        new_mt = current.get(k)
                        if old_mt != new_mt:
                            rel = Path(k).relative_to(ROOT)
                            changed.append(
                                f"  {'+' if new_mt and not old_mt else '-' if not new_mt else '~'} {rel}"
                            )
                    if changed:
                        print(f"[watch] {len(changed)} file(s) changed:")
                        for c in changed[:10]:
                            print(c)
                        if len(changed) > 10:
                            print(f"  ... and {len(changed) - 10} more")
                        print()
                        self.callback()
                    self._mtimes = current
        except KeyboardInterrupt:
            pass

    def stop(self):
        self._running = False


# ------------------------------------------------------------------ #
# Server
# ------------------------------------------------------------------ #


class Server(socketserver.ThreadingTCPServer):
    """Threading HTTP server with quiet logging toggle."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, handler, quiet=True):
        super().__init__(addr, handler)
        self.quiet = quiet


def serve(bind, port, quiet):
    """Start the HTTP server (blocks until KeyboardInterrupt)."""
    handler = Handler
    with Server((bind, port), handler, quiet=quiet) as httpd:
        url = f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}"
        print(f"[serve] Serving at {url}")
        print(f"[serve] Live reload enabled — browser refreshes on rebuild")
        print(f"[serve] Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] Shutting down...")


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #


def main():
    parser = argparse.ArgumentParser(
        description="Local preview server for the blog."
    )
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("-b", "--bind", type=str, default="127.0.0.1", help="Bind address")
    parser.add_argument("--no-build", action="store_true", help="Skip build, serve existing public/")
    parser.add_argument("-w", "--watch", action="store_true", help="Watch for source changes and auto-rebuild")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log every HTTP request")
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("  Blog Preview Server")
    print("=" * 50)
    print()

    if not args.no_build:
        if not build_site():
            sys.exit(1)
    elif not PUBLIC.exists():
        print("[serve] public/ not found. Building first...\n")
        if not build_site():
            sys.exit(1)

    if args.watch:
        def server_thread():
            serve(args.bind, args.port, quiet=not args.verbose)

        t = threading.Thread(target=server_thread, daemon=True)
        t.start()
        time.sleep(0.5)

        watcher = FileWatcher(callback=build_site, interval=1.5)
        try:
            watcher.start()
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()
            print("\n[watch] Stopped.")
    else:
        serve(args.bind, args.port, quiet=not args.verbose)


if __name__ == "__main__":
    main()
