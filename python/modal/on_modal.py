"""
The Restate app on Modal, connected to Restate Cloud.

One container runs src/app.py, which connects to Restate Cloud with
`restate.connect`. Its keys (RESTATE_CONNECT_KEY, and OPENAI_API_KEY if you
include the tutorial) are a Modal secret, created once from restate.env (see README.md). Run the commands from python/, the project's
directory:

    uv sync && uv run modal setup                                           # once
    uv run modal secret create restate-template --from-dotenv restate.env   # once
    uv run modal deploy modal/on_modal.py                                   # the image builds on Modal, then the app runs
    npx @restatedev/restate deployments register connect://notes-python-v1  # once: tells Restate Cloud about the deployment

`uv run modal app logs restate-template-python` follows the app;
`uv run modal app stop restate-template-python` stops it.
"""

import subprocess
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent  # the project: pyproject.toml, uv.lock and src/

image = (
    modal.Image.debian_slim(python_version="3.13")
    # The dependencies of pyproject.toml, at the versions of uv.lock; not the dev group.
    .uv_sync(str(ROOT), extra_options="--no-dev")
    .add_local_dir(ROOT / "src", "/app/src")
)

app = modal.App("restate-template-python", image=image)


@app.cls(
    min_containers=1,  # the app reaches Restate Cloud from here: one container, always up
    max_containers=1,
    secrets=[modal.Secret.from_name("restate-template")],
)
class App:
    process: subprocess.Popen[bytes]

    @modal.enter()
    def start(self) -> None:
        self.process = subprocess.Popen(["python", "src/app.py"], cwd="/app")
        # A bad key or a broken app exits right away: fail the container now, not later.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"the app exited with {self.process.returncode}")
            time.sleep(0.2)

    @modal.exit()
    def stop(self) -> None:
        # SIGTERM: the SDK finishes the requests in flight, then exits.
        self.process.terminate()
        try:
            self.process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.process.kill()
