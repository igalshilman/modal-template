"""
The coders' workspace, in git: a clone of the project for each coder
(``WORKSPACE/ENG-1.parser``), on a branch of its own (``eng-1-parser``), off the
project's default branch, which its pull request goes into. The coders run real
commands on this machine: use a sandbox.
"""

import asyncio
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import restate

# GitHub's credentials, GITHUB_TOKEN, as git asks for them: read when it pushes, so the token is in
# no URL, config or error message. The helpers before it (your machine's, such as its keychain) are
# dropped: they would answer, or ask you, first.
HELPER = '!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'
CREDENTIALS = ["-c", "credential.helper=", "-c", f"credential.helper={HELPER}"]


class GitError(Exception):
    """A git command that failed: retried, as the next attempt may succeed (a network error, say)."""


async def git(cwd: str | Path, *args: str) -> str:
    """Run git in ``cwd``, and return what it printed."""
    process = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    if process.returncode != 0:
        command = next((a for a in args if not a.startswith("-") and "=" not in a), "")
        raise GitError(f"git {command}: {err.decode().strip()}")
    return out.decode().strip()


async def has(cwd: str | Path, ref: str) -> bool:
    try:
        await git(cwd, "rev-parse", "--verify", "--quiet", ref)
        return True
    except GitError:
        return False


async def default_branch(folder: str | Path) -> str:
    """The remote's default branch, in a clone: the one its HEAD names, else ``origin/main``."""
    for attempt in range(2):
        try:
            return await git(folder, "rev-parse", "--abbrev-ref", "origin/HEAD")
        except GitError:
            if attempt == 0:  # a clone made before the remote had a branch: ask the remote
                try:
                    await git(folder, "remote", "set-head", "origin", "--auto")
                except GitError:
                    break
    return "origin/main"


def task_of(key: str) -> tuple[str, str]:
    """A coder's key as its issue and task: ``ENG-1.parser`` is ``("ENG-1", "parser")``."""
    issue, _, task = key.partition(".")
    if not re.fullmatch(r"[\w-]+", issue) or not re.fullmatch(r"[\w-]+", task):
        raise restate.TerminalError(f"{key} is not an issue's task, such as ENG-1.parser")
    return issue, task


def branch_of(key: str) -> str:
    """The coder ``key``'s branch: ``ENG-1.parser`` is on ``eng-1-parser``."""
    issue, task = task_of(key)
    return f"{issue.lower()}-{task}"


def coder_of_branch(branch: str) -> str | None:
    """The coder whose branch ``branch`` is (``eng-1-parser`` is ``ENG-1.parser``'s), or None."""
    found = re.fullmatch(r"([a-z][a-z0-9]*-\d+)-([a-z0-9-]+)", branch)
    return f"{found[1].upper()}.{found[2]}" if found else None


def _folder(root: str, key: str) -> tuple[Path, bool]:
    """The clone's folder, and whether git cloned into it already; a half-made one is removed."""
    folder = Path(root, key).resolve()
    if (folder / ".git").exists():
        return folder, True
    shutil.rmtree(folder, ignore_errors=True)
    Path(root).mkdir(parents=True, exist_ok=True)
    return folder, False


async def clone(root: str, remote: str, key: str) -> Path:
    """The clone of the coder ``key``, in ``root``: made the first time, on its branch.

    Each step is done once, so an attempt that failed half way is finished by the next.
    """
    _, task = task_of(key)
    branch = branch_of(key)
    folder, cloned = await asyncio.to_thread(_folder, root, key)
    if cloned and await has(folder, f"refs/heads/{branch}"):
        return folder
    if not cloned:
        await git(root, *CREDENTIALS, "clone", "--quiet", remote, str(folder))
    await git(folder, "config", "--replace-all", "credential.helper", "")
    await git(folder, "config", "--add", "credential.helper", HELPER)
    await git(folder, "config", "user.name", f"🛠️ Coder · {task}")  # its commits are signed, as its comments are
    await git(folder, "config", "user.email", "factory@restate.localhost")
    await git(folder, "config", "push.autoSetupRemote", "true")  # a plain `git push` pushes its branch
    # Its branch: the remote's, if a run before pushed it, or else a new one off the default branch.
    await git(folder, "fetch", "--quiet", "origin")
    start = f"origin/{branch}" if await has(folder, f"origin/{branch}") else await default_branch(folder)
    await git(folder, "checkout", "--quiet", "--no-track", "-b", branch, start)
    return folder


@dataclass
class Pushed:
    """What the coder ``key`` pushed, as its pull request has it, read in its clone."""

    folder: Path
    branch: str

    async def changes(self) -> str:
        """Its changes against the default branch: the files, and the diff."""
        await git(self.folder, "fetch", "--quiet", "origin")
        return await git(
            self.folder, "diff", "--stat", "--patch", f"{await default_branch(self.folder)}...{self.branch}"
        )

    async def file(self, path: str) -> str:
        """A file of the pull request, as pushed."""
        return await git(self.folder, "show", f"{self.branch}:{path}")


def pushed(root: str, key: str) -> Pushed:
    return Pushed(Path(root, key).resolve(), f"origin/{branch_of(key)}")


async def project(remote: str) -> str:
    """The project's repository, ``remote``, with a first commit (a README) if it has none.

    A new repository on GitHub is empty, and the coders' branches start off its default branch.
    """
    if await git(tempfile.gettempdir(), *CREDENTIALS, "ls-remote", "--heads", remote):
        return remote
    first = Path(tempfile.mkdtemp(prefix="factory-"))
    try:
        await git(first, "init", "--quiet", "--initial-branch", "main")
        (first / "README.md").write_text("# A demo project\n\nBuilt by the factory.\n")
        await git(first, "add", "README.md")
        await git(
            first,
            "-c",
            "user.name=Restate factory",
            "-c",
            "user.email=factory@restate.localhost",
            "commit",
            "-qm",
            "A README",
        )
        await git(first, *CREDENTIALS, "push", "--quiet", remote, "main")
    finally:
        shutil.rmtree(first, ignore_errors=True)
    return remote
