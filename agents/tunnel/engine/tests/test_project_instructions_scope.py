"""Project instruction scopes are exact and cannot be downgraded by MCP policy."""
import pytest

from router.access import AuthorizationError
from router.files_policy import scope_for_files_tool, validate_files_tool_scope


def test_read_context_requires_read_scope():
    assert scope_for_files_tool("files_project_instructions") == "files:read"
    assert validate_files_tool_scope("files_project_instructions", "files:read",
                                    ["files:read"]) == "read"
    with pytest.raises(AuthorizationError):
        validate_files_tool_scope("files_project_instructions", "files:write",
                                 ["files:read", "files:write"])


def test_project_open_requires_write_scope_even_for_existing_file():
    assert scope_for_files_tool("files_project_open") == "files:write"
    assert validate_files_tool_scope("files_project_open", "files:write",
                                    ["files:write"]) == "write"
    with pytest.raises(AuthorizationError):
        validate_files_tool_scope("files_project_open", "files:read",
                                 ["files:read", "files:write"])
    with pytest.raises(AuthorizationError):
        validate_files_tool_scope("files_project_open", "files:write",
                                 ["files:read"])
