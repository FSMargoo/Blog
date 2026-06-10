#!/usr/bin/env python3
"""
Local preview server for the blog.

Builds the site (unless --no-build) and serves public/ over HTTP.
Use --watch to auto-rebuild when source files change.

Usage:
    python serve.py                 # build + serve on :8000
    python serve.py --no-build      # serve existing public/ only
    python serve.py -w              # build, serve, and auto-rebuild on changes
    python serve.py -p 3000 -w -v   # custom port + watch + verbose logging
"""

import argparse
import http.server
import os
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

# Directories watched by --watch mode
WATCH_DIRS = [
    ROOT / "content",
    ROOT / "templates",
    ROOT / "static",
]
WATCH_FILES = [
    ROOT / "config.yaml",
]

# ------------------------------------------------------------------ #
# Build
# ------------------------------------------------------------------ #


def build_site() -> bool:
    """Run build.py as a subprocess. Returns True on success."""
    print("[build] Running build.py...")
    result = subprocess.run(
        [sys.executable, str(ROOT / "build.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("[build] ❌  Build failed!")
        if result.stderr:
            print(result.stderr)
        return False
    # Print build output compactly
    for line in result.stdout.strip().splitlines():
        print(f"  {line}")
    print("[build] ✓  Build complete\n")
    return True


# ------------------------------------------------------------------ #
# HTTP handler
# ------------------------------------------------------------------ #


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves public/ with optional quiet logging."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", True):
            # Skip standard 200/304 messages
            if args and args[0] in ("200", "304"):
                return
        # Color-coded output
        color = ""
        if args:
            code = args[0]
            if code[0] == "2":
                color = "\033[32m"  # green
            elif code[0] in ("4", "5"):
                color = "\033[31m"  # red
            elif code[0] == "3":
                color = "\033[33m"  # yellow
        sys.stdout.write(f"  {color}{args[0]}\033[0m {args[1]}\n" if args else "")


# ------------------------------------------------------------------ #
# File watcher (polling, no dependencies)
# ------------------------------------------------------------------ #


class FileWatcher:
    """Polling-based file watcher for --watch mode."""

    def __init__(self, callback, interval=1.5):
        self.callback = callback
        self.interval = interval
        self._mtimes = {}
        self._running = False
        self._lock = threading.Lock()

    def _collect_paths(self):
        """Return all file paths under watch."""
        paths = set()
        for d in WATCH_DIRS:
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        paths.add(str(f))
        for f in WATCH_FILES:
            if f.exists():
                paths.add(str(f))
        return paths

    def _snapshot(self):
        """Record mtimes of all watched files."""
        snap = {}
        for p in self._collect_paths():
            try:
                snap[p] = os.path.getmtime(p)
            except OSError:
                pass
        return snap

    def start(self):
        """Start watching. Blocks until stop() is called or KeyboardInterrupt."""
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
                    # Find what changed
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
                        print(
                            f"[watch] {len(changed)} file(s) changed:"
                        )
                        for c in changed[:10]:  # show at most 10
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
        print(f"[serve] ✓  Serving at {url}")
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
    parser.add_argument(
        "-p", "--port", type=int, default=8000, help="Port (default: 8000)"
    )
    parser.add_argument(
        "-b", "--bind", type=str, default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-build", action="store_true", help="Skip build, serve existing public/"
    )
    parser.add_argument(
        "-w", "--watch", action="store_true",
        help="Watch for source changes and auto-rebuild"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log every HTTP request"
    )
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("  Blog Preview Server")
    print("=" * 50)
    print()

    # Build
    if not args.no_build:
        if not build_site():
            sys.exit(1)
    elif not PUBLIC.exists():
        print("[serve] public/ not found. Building first...\n")
        if not build_site():
            sys.exit(1)

    # Watch mode: server in thread, watcher in main
    if args.watch:
        # Start server in background thread
        def server_thread():
            serve(args.bind, args.port, quiet=not args.verbose)

        t = threading.Thread(target=server_thread, daemon=True)
        t.start()
        time.sleep(0.5)  # give server time to start

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
