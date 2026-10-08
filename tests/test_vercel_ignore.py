"""zpf-web's Ignored Build Step must never skip a branch that changes web/.

Each test builds a small history, pushes it to a bare "GitHub", and runs
web/scripts/vercel-ignore.sh inside a `git clone --depth=10` of the branch --
the clone Vercel makes. Exit 0 skips the build, 1 builds. No network: the
remote is a file:// URL.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web" / "scripts" / "vercel-ignore.sh"


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


class Repo:
    """A working repo, its bare remote, and Vercel-shaped clones of it."""

    def __init__(self, root: Path):
        self.root = root
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(root),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
        }
        self.remote = root / "remote.git"
        self.work = root / "work"
        self.git(root, "init", "--quiet", "--bare", str(self.remote))
        self.git(root, "init", "--quiet", "-b", "main", str(self.work))
        self.commit("web/page.txt", "v1", also=("docs/notes.txt", "v1"))

    def git(self, cwd: Path, *args: str) -> str:
        out = subprocess.run(["git", *args], cwd=cwd, env=self.env,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()

    def commit(self, path: str, text: str, also: tuple[str, str] | None = None) -> str:
        for name, body in [(path, text)] + ([also] if also else []):
            target = self.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            self.git(self.work, "add", name)
        self.git(self.work, "commit", "--quiet", "-m", f"{path}: {text}")
        return self.git(self.work, "rev-parse", "HEAD")

    def filler(self, count: int) -> None:
        """`count` empty commits on the checked-out branch, in one process."""
        branch = self.git(self.work, "symbolic-ref", "--short", "HEAD")
        stream = ""
        for n in range(count):
            msg = f"filler {n}"
            stream += (f"commit refs/heads/{branch}\n"
                       f"committer t <t@example.test> 1700000000 +0000\n"
                       f"data {len(msg)}\n{msg}\n")
            if n == 0:
                stream += f"from refs/heads/{branch}^0\n"
        subprocess.run(["git", "fast-import", "--quiet"], cwd=self.work, env=self.env,
                       input=stream, text=True, check=True)

    def checkout(self, *args: str) -> None:
        self.git(self.work, "checkout", "--quiet", *args)

    def merge(self, branch: str) -> None:
        self.git(self.work, "merge", "--quiet", "--no-ff", "--no-edit", branch)

    def push(self, *branches: str) -> None:
        self.git(self.work, "push", "--quiet", "--force", str(self.remote),
                 *[f"{b}:refs/heads/{b}" for b in branches])

    def clone(self, branch: str) -> Path:
        dest = self.root / f"clone-{branch.replace('/', '-')}"
        self.git(self.root, "clone", "--quiet", "--depth=10", "--branch", branch,
                 f"file://{self.remote}", str(dest))
        return dest

    def ignore(self, clone: Path, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["sh", str(SCRIPT)], cwd=clone / "web",
                              env={**self.env, **env}, capture_output=True,
                              text=True, check=False)


def preview(branch: str, **extra: str) -> dict[str, str]:
    return {"VERCEL_ENV": "preview", "VERCEL_GIT_COMMIT_REF": branch, **extra}


def test_first_push_whose_tip_merges_main_builds(repo):
    """PR #182: the web change sits under a merge FROM main that touched no web/."""
    repo.checkout("-b", "feature")
    repo.commit("web/page.txt", "v2")
    repo.checkout("main")
    repo.commit("docs/notes.txt", "v2")
    repo.checkout("feature")
    repo.merge("main")
    repo.push("main", "feature")
    clone = repo.clone("feature")

    # the rule this replaced skipped exactly this push
    old = subprocess.run("git diff --quiet HEAD^ HEAD -- ':/web'", shell=True,
                         cwd=clone / "web", env=repo.env, check=False)
    assert old.returncode == 0

    result = repo.ignore(clone, **preview("feature"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "web/ changed since the merge base with main" in result.stdout


def test_first_push_with_the_web_change_below_the_tip_builds(repo):
    repo.checkout("-b", "feature")
    repo.commit("web/page.txt", "v2")
    repo.commit("docs/notes.txt", "v2")
    repo.push("main", "feature")

    result = repo.ignore(repo.clone("feature"), **preview("feature"))
    assert result.returncode == 1, result.stdout + result.stderr


def test_branch_that_only_merges_web_changes_from_main_skips(repo):
    repo.checkout("-b", "feature")
    repo.commit("docs/notes.txt", "v2")
    repo.checkout("main")
    repo.commit("web/page.txt", "v2")
    repo.checkout("feature")
    repo.merge("main")
    repo.push("main", "feature")

    result = repo.ignore(repo.clone("feature"), **preview("feature"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing under web/ changed" in result.stdout


def test_every_push_of_a_branch_that_changes_web_builds(repo):
    """A preview is judged against main, never against the last preview."""
    repo.checkout("-b", "feature")
    built = repo.commit("web/page.txt", "v2")
    repo.commit("docs/notes.txt", "v2")
    repo.push("main", "feature")

    result = repo.ignore(repo.clone("feature"),
                         **preview("feature", VERCEL_GIT_PREVIOUS_SHA=built))
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.parametrize("changes_web, expected", [(True, 1), (False, 0)])
def test_a_fork_deeper_than_the_clone_is_deepened_until_the_merge_base(
        repo, changes_web, expected):
    repo.checkout("-b", "feature")
    repo.commit("web/page.txt" if changes_web else "docs/notes.txt", "v2")
    repo.filler(70)             # the fork is 71 commits below the tip
    repo.push("main", "feature")

    result = repo.ignore(repo.clone("feature"), **preview("feature"))
    assert result.returncode == expected, result.stdout + result.stderr
    assert "no merge base with main at depth 64" in result.stdout


def test_production_keeps_the_previous_deployment_rule(repo):
    base = repo.git(repo.work, "rev-parse", "HEAD")
    repo.commit("web/page.txt", "v2")
    since_web = repo.commit("docs/notes.txt", "v2")
    repo.commit("docs/notes.txt", "v3")
    repo.push("main")
    clone = repo.clone("main")
    prod = {"VERCEL_ENV": "production", "VERCEL_GIT_COMMIT_REF": "main"}

    assert repo.ignore(clone, **prod, VERCEL_GIT_PREVIOUS_SHA=base).returncode == 1
    assert repo.ignore(clone, **prod, VERCEL_GIT_PREVIOUS_SHA=since_web).returncode == 0
    assert repo.ignore(clone, **prod).returncode == 0            # HEAD^: docs only
    missing = repo.ignore(clone, **prod, VERCEL_GIT_PREVIOUS_SHA="f" * 40)
    assert missing.returncode == 1, missing.stdout
    assert "could not diff" in missing.stdout


def test_no_reachable_main_builds(repo):
    repo.checkout("-b", "feature")
    repo.commit("docs/notes.txt", "v2")
    repo.push("main", "feature")
    clone = repo.clone("feature")

    repo.git(clone, "remote", "set-url", "origin", f"file://{repo.root}/gone.git")
    unreachable = repo.ignore(clone, **preview("feature"))
    assert unreachable.returncode == 1
    assert "could not fetch main" in unreachable.stdout

    repo.git(clone, "remote", "remove", "origin")
    no_remote = repo.ignore(clone, **preview("feature"))
    assert no_remote.returncode == 1
    assert "no remote" in no_remote.stdout


def test_outside_a_checkout_builds(repo, tmp_path):
    (tmp_path / "bare" / "web").mkdir(parents=True)
    result = repo.ignore(tmp_path / "bare", **preview("feature"))
    assert result.returncode == 1
    assert "not a git checkout" in result.stdout
