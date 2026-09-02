"""Refresh and serve the audit dashboard at a stable localhost URL."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class DashboardHandler(SimpleHTTPRequestHandler):
    """Static handler that prevents stale local dashboard responses."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        help="seconds between output/web change checks",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="serve the existing dashboard without regenerating it",
    )
    return parser.parse_args()


def audit_signature(input_root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a stable signature for all current audit contracts."""
    return tuple(
        (str(path), stat.st_mtime_ns, stat.st_size)
        for path in sorted(input_root.glob("**/audit.json"))
        if (stat := path.stat())
    )


def refresh_dashboard(project_root: Path) -> None:
    subprocess.run(
        [sys.executable, str(project_root / "scripts/generate_audit_dashboard.py")],
        cwd=project_root,
        check=True,
    )


def watch_audits(project_root: Path, interval: float, stop: threading.Event) -> None:
    """Regenerate the dashboard after audit files are added or changed."""
    input_root = project_root / "output/web"
    previous = audit_signature(input_root)
    while not stop.wait(interval):
        current = audit_signature(input_root)
        if current == previous:
            continue
        time.sleep(0.35)  # Let an atomic report write settle before reading it.
        try:
            refresh_dashboard(project_root)
            previous = audit_signature(input_root)
            print(f"Dashboard refreshed after audit change ({len(previous)} reports)", flush=True)
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"Dashboard refresh failed; watcher will retry: {error}", flush=True)


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    output_root = project_root / "output"
    if not args.skip_refresh:
        refresh_dashboard(project_root)

    handler = partial(DashboardHandler, directory=str(output_root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    stop_watcher = threading.Event()
    watcher = threading.Thread(
        target=watch_audits,
        args=(project_root, args.watch_interval, stop_watcher),
        name="audit-dashboard-watcher",
        daemon=True,
    )
    watcher.start()
    print(f"Dashboard: http://{args.host}:{args.port}/dashboard.html", flush=True)
    print(f"Watching output/web every {args.watch_interval:g}s", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_watcher.set()
        watcher.join(timeout=max(args.watch_interval + 1, 2))
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
