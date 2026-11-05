"""
The Restate app on Modal, connected to Restate Cloud.

One container runs src/app.ts, which connects to Restate Cloud with
`restate.connect`. Its keys (RESTATE_CONNECT_KEY, and OPENAI_API_KEY if you
include the tutorial) are a Modal secret, created once from restate.env (see
README.md).

    pip install modal python-dotenv && modal setup                          # once
    modal secret create restate-template --from-dotenv restate.env          # once
    modal deploy modal/on_modal.py                                          # the image builds on Modal, then the app runs
    restate deployments register connect://notes-v1                         # once: tells Restate Cloud about the deployment

`modal app logs restate-template` follows the app; `modal app stop
restate-template` stops it.
"""

import subprocess
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent  # the project: package.json and src/

image = (
    modal.Image.from_registry("node:24-bookworm-slim", add_python="3.13")  # Node.js, and Modal's runtime beside it
    .workdir("/app")
    .run_commands("corepack enable")  # pnpm, the version package.json pins
    .add_local_file(ROOT / "package.json", "/app/package.json", copy=True)
    .add_local_file(ROOT / "pnpm-workspace.yaml", "/app/pnpm-workspace.yaml", copy=True)
    .add_local_file(ROOT / "pnpm-lock.yaml", "/app/pnpm-lock.yaml", copy=True)
    .run_commands("pnpm install --prod --frozen-lockfile")
    .add_local_dir(ROOT / "src", "/app/src")
)

app = modal.App("restate-template", image=image)


@app.cls(
    min_containers=1,  # the app reaches Restate Cloud from here: one container, always up
    max_containers=1,
    secrets=[modal.Secret.from_name("restate-template")],
)
class App:
    @modal.enter()
    def start(self):
        self.app = subprocess.Popen(["node", "src/app.ts"], cwd="/app")
        # A bad key or a broken app exits right away: fail the container now, not later.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.app.poll() is not None:
                raise RuntimeError(f"the app exited with {self.app.returncode}")
            time.sleep(0.2)

    @modal.exit()
    def stop(self):
        # SIGTERM: the SDK finishes the requests in flight, then exits.
        self.app.terminate()
        try:
            self.app.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.app.kill()
