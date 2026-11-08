from datetime import datetime
import os
import threading

from .storage import APP_DIR

_lock = threading.Lock()


def log(message: str) -> None:
    if os.environ.get("TT_DIAGNOSTICS") != "1":
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        with (APP_DIR / "diagnostics.log").open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().astimezone().isoformat()} {message}\n")
