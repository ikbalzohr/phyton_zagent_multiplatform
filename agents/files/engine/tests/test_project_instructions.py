"""Project instructions: project isolation, exclusive create and hot reload."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.core import project_instructions as project


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    approved.mkdir()

    def scoped(path):
        requested = Path(path)
        candidate = (requested if requested.is_absolute() else approved / requested).resolve()
        if candidate != approved and approved not in candidate.parents:
            raise PermissionError("OUTSIDE_PROFILE")
        return candidate

    monkeypatch.setattr(project.fsops, "resolve", scoped)
    monkeypatch.setattr(project.fsops, "root", lambda: approved)
    monkeypatch.setattr(project.fsops, "rel", lambda path: str(path.relative_to(approved)))
    monkeypatch.setattr(project.fsops, "require_write", lambda: None)
    monkeypatch.setattr(project.fsops, "guard_no_links", lambda path: None)
    return approved


def recognized(root, name):
    folder = root / name
    folder.mkdir()
    (folder / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return folder


def test_read_only_operation_never_creates(workspace, monkeypatch):
    root = recognized(workspace, "read-only")
    monkeypatch.setattr(project.fsops, "require_write",
                        lambda: (_ for _ in ()).throw(PermissionError("read-only")))
    context = project.instructions("read-only")
    assert context["status"] == "missing"
    assert context["created"] is False
    assert not (root / "ZAGENT.md").exists()
    with pytest.raises(PermissionError):
        project.open_project("read-only")
    assert not (root / "ZAGENT.md").exists()


def test_explicit_open_creates_once_and_keeps_user_edits(workspace):
    root = recognized(workspace, "alpha")
    first = project.open_project("alpha")
    assert first["status"] == "available" and first["created"] is True
    assert (root / "ZAGENT.md").is_file()
    (root / "ZAGENT.md").write_text("# Custom rules\n", encoding="utf-8")
    again = project.open_project("alpha")
    assert again["created"] is False
    assert again["content"].replace("\r\n", "\n") == "# Custom rules\n"


def test_concurrent_open_has_one_creator(workspace):
    recognized(workspace, "shared")
    with ThreadPoolExecutor(max_workers=6) as executor:
        values = list(executor.map(lambda _: project.open_project("shared"), range(6)))
    assert sum(1 for value in values if value["created"]) == 1
    assert all(value["status"] == "available" for value in values)


def test_change_appears_on_next_operation_and_projects_do_not_mix(workspace):
    alpha = recognized(workspace, "alpha")
    beta = recognized(workspace, "beta")
    project.open_project("alpha")
    project.open_project("beta")
    before = project.for_operation("list", {"path": "alpha"}, can_create=False)
    (alpha / "ZAGENT.md").write_text("Rule v2", encoding="utf-8")
    after = project.for_operation("list", {"path": "alpha"}, can_create=False)
    other = project.for_operation("list", {"path": "beta"}, can_create=False)
    assert before["sha256"] != after["sha256"]
    assert after["content"] == "Rule v2"
    assert after["project_root"] == "alpha"
    assert other["project_root"] == "beta"
    assert other["content"] != "Rule v2"


def test_first_authorized_write_bootstraps_but_read_does_not(workspace):
    root = recognized(workspace, "alpha")
    (root / "module.py").write_text("pass\n", encoding="utf-8")
    context = project.for_operation("read", {"path": "alpha/module.py"}, can_create=False)
    assert context["status"] == "missing"
    assert not (root / "ZAGENT.md").exists()
    context = project.for_operation("write", {"path": "alpha/module.py"}, can_create=True)
    assert context["status"] == "available"
    assert context["created"] is True
    assert project.for_operation("write", {"path": "alpha/ZAGENT.md"}, can_create=True)["created"] is False


def test_unmarked_directory_needs_explicit_confirmation(workspace):
    empty = workspace / "empty"
    empty.mkdir()
    assert project.instructions("empty")["status"] == "unrecognized"
    assert project.open_project("empty")["status"] == "unrecognized"
    assert not (empty / "ZAGENT.md").exists()
    assert project.open_project("empty", allow_unmarked=True)["created"] is True


def test_parent_profile_not_implicitly_selected(workspace):
    alpha = recognized(workspace, "alpha")
    assert project.detect(".") is None
    assert project.detect("alpha/pyproject.toml") == alpha
    assert project.for_operation("list", {"path": "."}, can_create=True) is None
    assert not (workspace / "ZAGENT.md").exists()


def test_outside_profile_rejected(workspace):
    with pytest.raises(PermissionError):
        project.open_project("../outside", allow_unmarked=True)


def test_oversized_file_not_injected(workspace):
    folder = recognized(workspace, "big")
    (folder / "ZAGENT.md").write_bytes(b"X" * (project.MAX_BYTES + 1))
    response = project.instructions("big")
    assert response["status"] == "too_large"
    assert "content" not in response


def test_read_only_filesystem_skips_automatic_create(workspace, monkeypatch):
    recognized(workspace, "alpha")
    def deny(_folder):
        raise OSError(30, "filesystem read-only")
    monkeypatch.setattr(project, "_create", deny)
    response = project.for_operation("write", {"path": "alpha/source.py"}, can_create=True)
    assert response["status"] == "missing"
    assert response["creation_skipped"] == "filesystem_read_only"



def test_profile_container_generic_manifest_not_auto_bootstrapped(workspace):
    # A multi-project profile like Programming may contain shared config.
    (workspace / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    alpha = recognized(workspace, "alpha")
    assert project.detect("alpha/source.py") == alpha
    assert project.detect("loose.py") is None
    assert project.for_operation("write", {"path": "loose.py"}, can_create=True) is None
    assert not (workspace / "ZAGENT.md").exists()


def test_repository_profile_root_is_a_project(workspace):
    # agent-dev points directly at a Git repository, unlike Programming.
    (workspace / ".git").mkdir()
    assert project.detect("README.md") == workspace
    context = project.for_operation("write", {"path": "README.md"}, can_create=True)
    assert context["status"] == "available"
    assert context["created"] is True
    assert context["project_root"] == "."
    assert (workspace / "ZAGENT.md").is_file()


def test_existing_profile_root_instructions_are_respected(workspace):
    (workspace / "ZAGENT.md").write_text("# Existing instructions\n", encoding="utf-8")
    assert project.detect("README.md") == workspace
    context = project.for_operation("read", {"path": "README.md"}, can_create=False)
    assert context["content"].replace("\r\n", "\n") == "# Existing instructions\n"
    assert context["created"] is False
