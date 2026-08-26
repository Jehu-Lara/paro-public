"""Valida que todos los .json bajo PowerBi/ tengan sintaxis valida.

Corre identico en local (`python scripts/validate_powerbi.py`) y en CI
(`powerbi-validate` en `.github/workflows/ci.yml`): sin dependencias de
terceros, solo stdlib, asi ninguno de los dos entornos necesita `uv sync`
para ejecutarlo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

__all__ = ["main", "run"]

POWERBI_DIR = Path("PowerBi")


def run(root: Path) -> list[tuple[Path, json.JSONDecodeError]]:
    """Valida cada .json bajo ``root`` y devuelve los que fallaron."""
    failures = []
    for path in sorted(root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append((path, exc))
    return failures


def _print_failures(failures: list[tuple[Path, json.JSONDecodeError]]) -> None:
    for path, exc in failures:
        print(f"[validate_powerbi] {path}:{exc.lineno}:{exc.colno}: {exc.msg}")


def main() -> None:
    if not POWERBI_DIR.is_dir():
        print(f"[validate_powerbi] no existe {POWERBI_DIR}/, nada que validar")
        return

    failures = run(POWERBI_DIR)
    if failures:
        _print_failures(failures)
        print(f"[validate_powerbi] {len(failures)} archivo(s) invalido(s)")
        sys.exit(1)

    print("[validate_powerbi] todos los .json bajo PowerBi/ son validos")


if __name__ == "__main__":
    main()
