"""The Stalwart process: started, stopped and watched by the supervisor (and the live tests).
Its modes: bootstrap (first start, no config.json yet), recovery (management only, used once
to set it up) and normal."""
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .client import EngineUnavailable


class Stalwart:
    def __init__(self, binary, data_dir, http_port=17880):
        self.binary = str(binary)
        self.data_dir = Path(data_dir)
        self.config = self.data_dir / "config.json"
        self.http_port = http_port
        self.process = None

    def start(self, mode="normal", recovery_password=None):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CONFIG_PATH": str(self.config)}
        if mode in ("bootstrap", "recovery"):
            env["STALWART_RECOVERY_MODE_PORT"] = str(self.http_port)
            env["STALWART_RECOVERY_ADMIN"] = f"admin:{recovery_password}"
        if mode == "recovery":
            env["STALWART_RECOVERY_MODE"] = "1"
        self.process = subprocess.Popen([self.binary, "--config", str(self.config)], env=env, cwd=self.data_dir)

    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self, timeout=15):
        if not self.running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def wait_until_up(self, timeout=60):
        """Until its HTTP side answers (any answer; 401 included)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running():
                raise EngineUnavailable(f"Stalwart exited with {self.process.returncode}")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.http_port}/jmap/session", timeout=2)
                return
            except urllib.error.HTTPError:
                return
            except OSError:
                time.sleep(0.5)
        raise EngineUnavailable("Stalwart didn't come up in time")
