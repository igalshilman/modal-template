"""
A lesson on Modal, connected to Restate Cloud.

One container runs the lesson, which connects out to Restate Cloud with
`restate.connect` (the last line of each lesson): Modal exposes no port. The
container gets the keys in restate.env, next to this file (copy
restate.env.example): the connect key from the Cloud UI, Development →
Configure SDK, and OPENAI_API_KEY for lessons 09 to 16.

    pip install modal python-dotenv && modal setup     # once
    modal deploy on_modal.py                           # the image builds on Modal, then lesson 01 runs
    LESSON=15_subagents modal deploy on_modal.py       # another lesson takes its place
    restate deployments register connect://template    # once: tells Restate Cloud about the deployment

`modal app logs restate-template` follows the lesson; `modal app stop
restate-template` stops it.
"""

import os
import subprocess
import time
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
LESSON = os.environ.get("LESSON", "01_object")

image = (
    modal.Image.from_registry("node:24-bookworm-slim", add_python="3.13")  # Node.js, and Modal's runtime beside it
    .workdir("/app")
    .run_commands("corepack enable")  # pnpm, the version package.json pins
    .add_local_file(HERE / "package.json", "/app/package.json", copy=True)
    .add_local_file(HERE / "pnpm-workspace.yaml", "/app/pnpm-workspace.yaml", copy=True)
    .run_commands("pnpm install --prod")
    .add_local_dir(HERE / "src", "/app/src")  # mounted, not built in: a changed lesson redeploys in seconds
)

app = modal.App("restate-template", image=image)


@app.cls(
    min_containers=1,  # the lesson reaches Restate Cloud from here: one container, always up
    max_containers=1,
    secrets=[modal.Secret.from_dotenv(HERE, filename="restate.env")],  # read where `modal deploy` runs
    env={"RESTATE_CONNECT_NAME": "template", "LESSON": LESSON},
)
class Lesson:
    @modal.enter()
    def start(self):
        self.lesson = subprocess.Popen(["node", f"src/{LESSON}.ts"], cwd="/app")
        # A bad key or a broken lesson exits right away: fail the container now, not later.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.lesson.poll() is not None:
                raise RuntimeError(f"lesson {LESSON} exited with {self.lesson.returncode}")
            time.sleep(0.2)

    @modal.exit()
    def stop(self):
        # SIGTERM: the SDK finishes the requests in flight, then exits.
        self.lesson.terminate()
        try:
            self.lesson.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.lesson.kill()
