from collections.abc import Iterable, Mapping
from importlib import import_module
from pathlib import Path

from infra.datascript.DataScript import DataScript


def discover_scripts(package_name: str = "scripts.operations") -> dict[str, DataScript]:
    """Discover script_instance exports, including modules in namespace directories."""
    package = import_module(package_name)
    module_names = set()

    for location in package.__path__:
        root = Path(location)

        for path in root.rglob("*.py"):
            relative = path.relative_to(root).with_suffix("")
            if any(part.startswith("_") for part in relative.parts):
                continue

            module_names.add(".".join([package_name, *relative.parts]))

    scripts = {}

    for name in sorted(module_names):
        module = import_module(name)
        script = getattr(module, "script_instance", None)

        if script is None:
            continue

        if not isinstance(script, DataScript):
            raise TypeError(f"{name}.script_instance must be a DataScript")

        if script.__class__.__module__ != name:
            continue

        if script.script_id in scripts:
            raise ValueError(f"Duplicate script_id: {script.script_id} ({name})")

        scripts[script.script_id] = script

    return scripts


def resolve_scripts(
    scripts: Mapping[str, DataScript],
    script_ids: Iterable[str] | None = None,
) -> list[DataScript]:
    """Validate the selected graph before returning prerequisites ahead of consumers."""
    selected = sorted(scripts) if script_ids is None else list(script_ids)
    ordered = []
    visited = set()
    visiting = []

    def visit(script_id: str) -> None:
        if script_id not in scripts:
            context = f" (required by {visiting[-1]})" if visiting else ""
            raise ValueError(f"Unknown script_id: {script_id}{context}")

        if script_id in visiting:
            cycle = " -> ".join([*visiting, script_id])
            raise ValueError(f"Cyclic script dependencies: {cycle}")

        if script_id in visited:
            return

        visiting.append(script_id)
        script = scripts[script_id]

        for dependency in script.dependencies:
            visit(dependency)

        visiting.pop()
        visited.add(script_id)
        ordered.append(script)

    for script_id in selected:
        visit(script_id)

    return ordered
