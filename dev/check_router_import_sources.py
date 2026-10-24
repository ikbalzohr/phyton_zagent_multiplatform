"""AST-only startup regression guard; never imports or runs product code.

Run with Python 3.11+: python dev/check_router_import_sources.py
This verifies source contracts, NOT Windows startup or workflow behavior.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "agents/tunnel/engine/router"
ENGINE = ROOT / "agents/arcmap/engine"


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def eager_imports(node):
    """Include module/class/conditional imports, excluding deferred bodies."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child
        yield from eager_imports(child)


def module_path(name):
    base = ROUTER.parent if name.split(".")[0] == "router" else ENGINE
    path = base.joinpath(*name.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    if (path / "__init__.py").is_file():
        return path / "__init__.py"
    return None


def startup_graph_errors(seed="router.server", include_deferred=False):
    pending = [seed]
    seen = set()
    errors = []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        path = module_path(name)
        if path is None:
            errors.append("missing startup source: " + name)
            continue
        # Python initializes parent packages before loading their submodules.
        if "." in name:
            pending.append(name.rsplit(".", 1)[0])
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        imports = (n for n in ast.walk(tree(path)) if isinstance(n, (ast.Import, ast.ImportFrom))) if include_deferred else eager_imports(tree(path))
        for node in imports:
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                if node.level:
                    parts = package.split(".")
                    prefix = parts[:len(parts) - node.level + 1]
                    target = ".".join(prefix + ([node.module] if node.module else []))
                else:
                    target = node.module or ""
                targets = [target]
                # `from package import submodule` also loads source submodules.
                targets += [target + "." + alias.name for alias in node.names
                            if module_path(target + "." + alias.name)]
            pending.extend(target for target in targets
                           if target.split(".")[0] in {"router", "orchestrator", "mcp_server"})
    return errors, seen


def check():
    errors, seen = startup_graph_errors()
    deferred_errors, deferred_seen = startup_graph_errors("router.workflow_executor", include_deferred=True)
    # Recovered source is mandatory in the distributed checkout, including deferred imports.
    errors.extend(deferred_errors)
    executor = tree(ROUTER / "workflow_executor.py")
    eager = [n.module for n in eager_imports(executor) if isinstance(n, ast.ImportFrom)]
    if "orchestrator.artifacts" in eager:
        errors.append("Publisher must be deferred, not imported at router startup")
    executor_class = next(n for n in executor.body if isinstance(n, ast.ClassDef)
                          and n.name == "ConcreteWorkflowExecutor")
    constructor = next(n for n in executor_class.body if isinstance(n, ast.FunctionDef)
                       and n.name == "__init__")
    first = constructor.body[0]
    if not (isinstance(first, ast.If)
            and isinstance(first.test, ast.Call)
            and isinstance(first.test.func, ast.Name)
            and first.test.func.id == "workflow_execution_unavailable"
            and any(isinstance(n, ast.Raise) for n in first.body)):
        errors.append("executor constructor must fail before any imports or mutation")
    runtime = (ROUTER / "workflow_runtime.py").read_text(encoding="utf-8")
    if "if workflow_execution_unavailable() is None:" not in runtime:
        errors.append("startup must not construct the unavailable optional executor")
    for method, mutation in [("submit", "self.journal.submit_run("),
                             ("execute_internal", "asyncio.to_thread("),
                             ("resume", "self.journal.transition(")]:
        node = next(n for n in ast.walk(tree(ROUTER / "workflow_runtime.py"))
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method)
        source = ast.get_source_segment(runtime, node) or ""
        if "self.execution_unavailable()" not in source or source.index("self.execution_unavailable()") > source.index(mutation):
            errors.append(method + " must reject missing executor before mutation/dispatch")
    server = (ROUTER / "server.py").read_text(encoding="utf-8")
    if "workflow_runtime.execution_unavailable()" not in server or "_WORKFLOW_EXECUTION_TOOLS" not in server:
        errors.append("public discovery must hide unavailable workflow execution tools")
    if "mapping = registry.tool_index.get(name)" not in server:
        errors.append("management discovery must tolerate tools without upstream mappings")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    if "/agents/arcmap/engine/orchestrator/artifacts/\n" in ignore:
        errors.append("Git must not ignore the whole artifacts source directory")
    if "!/agents/arcmap/engine/orchestrator/artifacts/*.py" not in ignore:
        errors.append("artifacts source-only Python allowlist required")
    if errors:
        for error in errors:
            print("SOURCE_GUARD_FAIL:", error)
        return 1
    print(f"SOURCE_GUARD_PASS: {len(seen)} startup source modules resolved; optional execution gates present")
    print(f"Deferred workflow graph: {len(deferred_seen)} local modules; missing sources: {deferred_errors}")
    print("Windows imports, behavioral tests, and ArcMap execution: NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
