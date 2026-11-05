"""
The Restate app on Modal, connected to Restate Cloud.

One container serves app/ through an outbound connection to Restate Cloud:
``python -m restate connect app.__main__:app``, the same ``app`` that
``uv run app`` serves on your machine. Its keys (RESTATE_CONNECT_KEY, and
OPENAI_API_KEY for the assistant) are a Modal secret (see README.md). Run the
commands from python/, the project's directory:

    uv sync && uv run modal setup                                                                 # once
    uv run modal secret create restate-template RESTATE_CONNECT_KEY=… OPENAI_API_KEY=…            # once
    uv run modal deploy modal/on_modal.py                                                         # builds the image, then runs the app
    npx @restatedev/restate@1.8.1-hotfix.2 deployments register connect://notes-python-v1        # once (after `restate cloud login`)

`uv run modal app logs restate-template-python` follows the app;
`uv run modal app stop restate-template-python` stops it.
"""

import subprocess
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent  # the project: pyproject.toml, uv.lock and app/
NAME = "notes-python-v1"  # the deployment, registered in Restate Cloud as connect://notes-python-v1

image = (
    modal.Image.debian_slim(python_version="3.13")
    # The dependencies of pyproject.toml, at the versions of uv.lock; no dependency group (dev, examples).
    .uv_sync(str(ROOT), extra_options="--no-default-groups")
    # Only the app: the tutorial and the examples are for your machine.
    .add_local_dir(ROOT / "app", "/srv/app", ignore=["**/__pycache__"])
)

app = modal.App("restate-template-python", image=image)


@app.cls(
    min_containers=1,  # the app reaches Restate Cloud from here: one container, always up
    secrets=[modal.Secret.from_name("restate-template")],
)
class App:
    process: subprocess.Popen[bytes]

    @modal.enter()
    def start(self) -> None:
        self.process = subprocess.Popen(
            ["python", "-m", "restate", "connect", "app.__main__:app", "--name", NAME], cwd="/srv"
        )
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
