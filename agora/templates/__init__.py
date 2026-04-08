"""Template catalog for agora init."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent


def list_templates() -> dict:
    """Return template metadata from manifest.json."""
    manifest = TEMPLATES_DIR / "manifest.json"
    with open(manifest) as f:
        return json.load(f)["templates"]


def get_template_dir(name: str) -> Path:
    """Return the path to a template directory. Raises ValueError if not found."""
    templates = list_templates()
    if name not in templates:
        available = ", ".join(sorted(templates))
        raise ValueError(f"Unknown template '{name}'. Available: {available}")
    path = TEMPLATES_DIR / name
    if not path.is_dir():
        raise ValueError(f"Template '{name}' directory missing at {path}")
    return path


def copy_template(
    template_name: str,
    dest: Path,
    substitutions: dict[str, str],
    from_path: Path | None = None,
) -> None:
    """Copy a template directory to dest, applying string substitutions.

    Args:
        template_name: Name of the built-in template (ignored if from_path set).
        dest: Destination directory (must not exist).
        substitutions: Mapping of {{key}} -> value for template variables.
        from_path: Optional custom template directory (overrides template_name).
    """
    src = from_path if from_path else get_template_dir(template_name)

    if dest.exists():
        raise FileExistsError(f"Directory '{dest}' already exists")

    dest.mkdir(parents=True)

    for item in src.iterdir():
        if item.name == "__pycache__":
            continue

        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            content = item.read_text()
            for key, value in substitutions.items():
                content = content.replace("{{" + key + "}}", value)
            target.write_text(content)
