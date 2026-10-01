"""Узкая ветка `plugin`: дерево только с файлами плагина и шаг конвейера (TRK-478).

Портал Anthropic сканирует всё дерево отслеживаемой ветки (пределы 512 файлов и 256 КиБ на
файл не-картинки, TRK-457#6), а репозиторий целиком в них не входит. Ветку собирает
`scripts/build-plugin-branch.sh`, а двигает шаг джоба `channel` в `images.yml` — следом за
`stable`, на тот же тег выпуска. Скрипт запускается по-настоящему: на дереве репозитория и на
временном git-репозитории с копией файлов плагина.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-plugin-branch.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "images.yml"

TREE_ROOTS = {
    ".claude-plugin",
    ".codex-plugin",
    "gemini-extension.json",
    "skills",
    "LICENSE",
    "README.md",
}
PLUGIN_FILES = (*sorted(TREE_ROOTS), "pyproject.toml")


def _run(*args: str, cwd: Path = ROOT, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kwargs)


def _files(tree: Path) -> set[str]:
    return {str(p.relative_to(tree)) for p in tree.rglob("*") if p.is_file()}


def _git(repo: Path, *args: str) -> str:
    result = _run("git", *args, cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """Копия файлов плагина и скрипта в свежем git-репозитории."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    for name in PLUGIN_FILES:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, repo / name)
        else:
            shutil.copy2(src, repo / name)
    (repo / "app").mkdir()
    (repo / "app" / "not_plugin.py").write_text("x = 1\n")
    _git(repo, "init", "-q")
    return repo


def test_the_script_is_executable_and_parses() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert _run("bash", "-n", str(SCRIPT)).returncode == 0


def test_the_tree_holds_only_the_plugin_within_the_portal_limits(tmp_path: Path) -> None:
    result = _run(str(SCRIPT), str(tmp_path / "tree"))

    assert result.returncode == 0, result.stderr
    files = _files(tmp_path / "tree")
    assert {".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "LICENSE"} <= files
    assert "gemini-extension.json" in files
    assert "skills/casefile/SKILL.md" in files
    assert "skills/AGENTS.md" not in files
    assert all(f.split("/")[0] in TREE_ROOTS for f in files)
    assert len(files) < 512
    assert result.stdout.strip() == f"files: {len(files)}"


def test_a_big_file_that_is_not_an_image_stops_the_build(mini_repo: Path, tmp_path: Path) -> None:
    (mini_repo / "skills" / "big.txt").write_bytes(b"x" * 300_000)

    result = _run(str(mini_repo / "scripts" / SCRIPT.name), str(tmp_path / "tree"))

    assert result.returncode != 0
    assert "256 КиБ" in result.stderr


def test_a_version_different_from_the_release_stops_the_build(
    mini_repo: Path, tmp_path: Path
) -> None:
    pyproject = mini_repo / "pyproject.toml"
    text = pyproject.read_text().replace("\nversion = ", '\nversion = "9.9.9"  # ', 1)
    pyproject.write_text(text)

    result = _run(str(mini_repo / "scripts" / SCRIPT.name), str(tmp_path / "tree"))

    assert result.returncode != 0
    assert "версии выпуска" in result.stderr


def test_a_commit_per_release_on_top_of_the_branch_and_none_for_the_same_tree(
    mini_repo: Path, tmp_path: Path
) -> None:
    script = str(mini_repo / "scripts" / SCRIPT.name)
    first = _run(script, "--commit", "v1.0.0", str(tmp_path / "t1")).stdout.splitlines()[-1]
    _git(mini_repo, "update-ref", "refs/remotes/origin/plugin", first)

    parent = ("--parent", "refs/remotes/origin/plugin")
    same = _run(script, "--commit", "v1.0.1", *parent, str(tmp_path / "t2"))
    (mini_repo / "README.md").write_text("changed\n")
    second = _run(script, "--commit", "v1.1.0", *parent, str(tmp_path / "t3"))

    assert same.stdout.splitlines()[-1] == first
    commit = second.stdout.splitlines()[-1]
    assert _git(mini_repo, "rev-parse", f"{commit}^") == first
    assert _git(mini_repo, "log", "-1", "--format=%s", commit) == "release v1.1.0: plugin files"
    names = set(_git(mini_repo, "ls-tree", "-r", "--name-only", commit).splitlines())
    assert names == _files(tmp_path / "t3")
    assert not any(n.startswith("app/") or n == "pyproject.toml" for n in names)
    assert _git(mini_repo, "rev-list", "--count", first) == "1"


def _channel_steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["channel"]["steps"]


def test_the_plugin_branch_step_goes_after_stable_on_the_same_release_tag() -> None:
    steps = _channel_steps()
    names = [s.get("name", "") for s in steps]
    stable = next(s for s in steps if s.get("id") == "stable")
    plugin = steps[names.index("Add the plugin files of the release to the plugin branch")]

    assert names.index(stable["name"]) < steps.index(plugin)
    assert plugin["if"] == "steps.stable.outputs.tag != ''"
    assert plugin["env"]["TAG"] == "${{ steps.stable.outputs.tag }}"
    # Тег в вывод шага пишется только после успешного пуша `stable`: образы зелёные, сверка прошла.
    assert stable["run"].index("refs/heads/stable") < stable["run"].index("GITHUB_OUTPUT")
    assert "scripts/build-plugin-branch.sh --commit" in plugin["run"]
    assert 'refs/heads/plugin"' in plugin["run"]
    assert "--force" not in plugin["run"] and "-f " not in plugin["run"]


def test_the_channel_job_runs_on_main_only_with_full_history() -> None:
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["channel"]

    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["steps"][0]["with"]["fetch-depth"] == 0
