"""离线检查包内依赖方向和模块循环；不导入业务或原生设备。"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "bd2_fishing"

# 当前采用功能模块化结构：game 的动作/观察器允许使用具体适配器；纯规则另行收紧。
ALLOWED = {
    "runtime": {"runtime"},
    "perception": {"perception", "runtime"},
    "infrastructure": {"infrastructure", "perception", "runtime"},
    "game": {"game", "perception", "runtime", "infrastructure"},
    "app": {"app", "game", "perception", "runtime", "infrastructure"},
    "ui": {"ui", "app", "runtime"},
    "bootstrap": {"app", "ui", "infrastructure"},
}
PURE = {
    "feedback_rules",
    "settlement_rules",
    "cast_feedback",
    "recognition",
    "catalog",
    "pointer",
    "scene_signals",
    "hook",
    "scene",
    "page",
    "panels",
    "templates",
    "trigger_rules",
    "voyage_reading",
    "dialogs",
}
MECHANICS = "bd2_fishing.game.fishing.mechanics"


def module_imports(path, module):
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            yield base
            yield from (f"{base}.{alias.name}" for alias in node.names if alias.name != "*")


def check_package(package=PACKAGE):
    modules = {}
    for path in package.rglob("*.py"):
        name = ".".join(path.relative_to(package.parent).with_suffix("").parts)
        modules[name.removesuffix(".__init__")] = path
    graph = {name: set() for name in modules}
    errors = set()
    for name, path in modules.items():
        layer = name.split(".")[1] if "." in name else ""
        for imported in module_imports(path, name):
            if imported.split(".")[0] in {"scripts", "tests", "tools"}:
                errors.add(f"Production imports development code: {name} -> {imported}")
            if not imported.startswith("bd2_fishing."):
                continue
            target_layer = imported.split(".")[1]
            if target_layer not in ALLOWED.get(layer, set()):
                errors.add(f"Forbidden dependency: {name} -> {imported}")
            pure = path.stem in PURE or name == MECHANICS or name.startswith(MECHANICS + ".")
            if pure and target_layer in {"infrastructure", "app", "ui"}:
                errors.add(f"Pure recognition/rule imports implementation: {name} -> {imported}")
            if (name == MECHANICS or name.startswith(MECHANICS + ".")) and target_layer == "game":
                if not (
                    imported == MECHANICS
                    or imported.startswith(MECHANICS + ".")
                    or imported == "bd2_fishing.game.fishing.trigger_rules"
                    or imported.startswith("bd2_fishing.game.fishing.trigger_rules.")
                ):
                    errors.add(f"Mechanics imports game execution: {name} -> {imported}")
            target = imported
            while target not in modules and "." in target:
                target = target.rpartition(".")[0]
            if target in modules and target != name:
                graph[name].add(target)
    visited, active = set(), []

    def visit(name):
        if name in active:
            errors.add("Import cycle: " + " -> ".join(active[active.index(name) :] + [name]))
            return
        if name in visited:
            return
        active.append(name)
        for dependency in sorted(graph[name]):
            visit(dependency)
        active.pop()
        visited.add(name)

    for name in sorted(graph):
        visit(name)
    return sorted(errors), len(modules)


def main():
    errors, count = check_package()
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {count} modules, dependency boundaries and static import graph are valid.")


if __name__ == "__main__":
    main()
