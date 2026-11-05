"""
The Restate app on Modal, called by Restate Cloud: on_modal.py, the other way round.

At least one container, always up, serves app/ over HTTP/2 on a Modal Server's endpoint:
``python -m restate serve app.__main__:app``, the same ``app`` that ``uv run app``
serves on your machine. Restate Cloud calls it, instead of the app connecting
out.

Its keys (OPENAI_API_KEY for the assistant) are on_modal.py's Modal secret,
which needs no RESTATE_CONNECT_KEY here (see README.md). Run the commands from
python/, the project's directory:

    uv sync && uv run modal setup                                                       # once
    uv run modal secret create restate-template OPENAI_API_KEY=…                        # once
    uv run modal deploy modal/on_modal_push.py                                          # builds the image, runs the app, prints its URL
    npx @restatedev/restate@1.8.1-hotfix.2 deployments register --force --yes \\
        https://<workspace>--restate-template-python-push-app.us-east.modal.direct \\
        --extra-header Modal-Key=wk-… --extra-header Modal-Secret=ws-…                  # after each deploy (after `restate cloud login`)

The Modal-Key and Modal-Secret are a proxy auth token's
(modal.com/settings/proxy-auth-tokens), which Restate sends on every request:
only Restate can call the endpoint.
`uv run modal app logs restate-template-python-push` follows the app;
`uv run modal app stop restate-template-python-push` stops it.
"""

import socket
import subprocess
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent  # the project: pyproject.toml, uv.lock and app/
PORT = 9080  # the port of the app in the container, behind Modal's endpoint

image = (
    modal.Image.debian_slim(python_version="3.13")
    # The dependencies of pyproject.toml, at the versions of uv.lock; no dependency group (dev, examples).
    .uv_sync(str(ROOT), extra_options="--no-default-groups")
    # Only the app: the tutorial and the examples are for your machine.
    .add_local_dir(ROOT / "app", "/srv/app", ignore=["**/__pycache__"])
)

app = modal.App("restate-template-python-push", image=image)


@app.server(
    port=PORT,
    h2_enabled=True,  # HTTP/2 end to end, so Restate talks to the app in streaming mode
    min_containers=1,
    startup_timeout=60,
    exit_grace_period=600,  # a turn runs on, while a container is replaced
    secrets=[modal.Secret.from_name("restate-template")],
)
class App:
    process: subprocess.Popen[bytes]

    @modal.enter()
    def start(self) -> None:
        self.process = subprocess.Popen(
            ["python", "-m", "restate", "serve", "app.__main__:app", "--port", str(PORT)], cwd="/srv"
        )
        # Until the app takes connections. A broken app exits right away: fail the container now, not later.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"the app exited with {self.process.returncode}")
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
                return
            except OSError:
                time.sleep(0.2)
        raise TimeoutError(f"the app is not on port {PORT} after 30s")

    @modal.exit()
    def stop(self) -> None:
        # SIGTERM: the SDK winds down the requests in flight, and Restate retries the rest.
        self.process.terminate()
        try:
            self.process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.process.kill()
