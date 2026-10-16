"""Open the current checkout, restarting only its own outdated development server."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from oss.web_server import application_revision


URL = "http://127.0.0.1:8765"


def health() -> dict | None:
    try:
        with urlopen(URL + "/api/health", timeout=1) as response:
            data = json.load(response)
        return data if isinstance(data, dict) else None
    except (URLError, OSError, ValueError):
        return None


def port_in_use() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=1):
            return True
    except OSError:
        return False


def main() -> None:
    revision = application_revision()
    running = health()
    if running:
        if Path(running.get("project_dir", "")).resolve() != PROJECT_DIR:
            raise RuntimeError("Port 8765 belongs to another project. Its server was left running.")
        if running.get("revision") != revision:
            server_pid = int(running["pid"])
            if server_pid <= 0:
                raise RuntimeError("The development server returned an invalid process ID.")
            os.kill(server_pid, signal.SIGTERM)
            print("Restarting the development server with the current code.")
            for _ in range(40):
                if not port_in_use():
                    break
                time.sleep(0.05)
            running = None
    elif port_in_use():
        raise RuntimeError("Port 8765 is occupied by an unrecognized or older server.")

    if not running:
        log_path = Path(tempfile.gettempdir()) / ("oss-ax-dev-" + revision + ".log")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_DIR / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", "-m", "oss.web_server", "--port", "8765"],
                cwd=PROJECT_DIR, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        for _ in range(40):
            running = health()
            if running and running.get("revision") == revision:
                break
            if process.poll() is not None:
                raise RuntimeError(f"The server could not start. See {log_path}")
            time.sleep(0.5)
        else:
            raise RuntimeError(f"The server did not become ready. See {log_path}")

    target = URL + "/?v=" + revision
    if "--no-browser" not in sys.argv:
        webbrowser.open(target)
    print(target)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
