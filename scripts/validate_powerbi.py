"""Valida estructuralmente las fuentes editables bajo PowerBi/.

Corre identico en local (`python scripts/validate_powerbi.py`) y en CI
(`powerbi-validate` en `.github/workflows/ci.yml`): sin dependencias de
terceros, solo stdlib, asi ninguno de los dos entornos necesita `uv sync`
para ejecutarlo. JSON/PBIR/PBISM/PBIP deben ser JSON valido; TMDL recibe
comprobaciones conservadoras de integridad, no compilacion semantica.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["main", "run"]

POWERBI_DIR = Path("PowerBi")
JSON_SUFFIXES = frozenset({".json", ".pbir", ".pbism", ".pbip"})
VALIDATED_SUFFIXES = JSON_SUFFIXES | {".tmdl"}


@dataclass(frozen=True)
class ValidationFailure:
    """One source artifact that failed structural validation."""

    path: Path
    detail: str


def _read_utf8(path: Path) -> tuple[str | None, ValidationFailure | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return None, ValidationFailure(path, f"UTF-8 invalido en byte {exc.start}")


def _validate_json(path: Path) -> ValidationFailure | None:
    text, failure = _read_utf8(path)
    if failure is not None:
        return failure
    assert text is not None
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return ValidationFailure(path, f"{exc.lineno}:{exc.colno}: {exc.msg}")
    return None


def _has_unclosed_single_quote(text: str) -> bool:
    """Checks quoted TMDL identifiers without parsing TMDL semantics.

    Two adjacent quotes (``''``) are one escaped quote and never toggle
    identifier state. Every other quote opens or closes the current
    identifier, so an active state at EOF is an obvious truncation.
    """
    in_quote = False
    index = 0
    while index < len(text):
        if text[index] != "'":
            index += 1
        elif index + 1 < len(text) and text[index + 1] == "'":
            index += 2
        else:
            in_quote = not in_quote
            index += 1
    return in_quote


def _validate_tmdl(path: Path) -> ValidationFailure | None:
    raw = path.read_bytes()
    if not raw:
        return ValidationFailure(path, "TMDL vacio")
    if b"\x00" in raw:
        return ValidationFailure(path, "TMDL contiene bytes NUL")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ValidationFailure(path, f"UTF-8 invalido en byte {exc.start}")

    stripped = text.strip()
    if not stripped:
        return ValidationFailure(path, "TMDL vacio")
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        return ValidationFailure(path, "JSON valido no es una fuente TMDL")

    if text.count("(") > text.count(")"):
        return ValidationFailure(path, "TMDL contiene parentesis sin cerrar")
    if _has_unclosed_single_quote(text):
        return ValidationFailure(path, "TMDL contiene identificador entre comillas sin cerrar")

    last_line = stripped.splitlines()[-1].rstrip()
    if last_line.endswith((":", "=")):
        return ValidationFailure(path, "TMDL parece truncado al final")
    return None


def run(root: Path) -> list[ValidationFailure]:
    """Valida cada fuente Power BI soportada y devuelve las que fallaron."""
    failures: list[ValidationFailure] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        suffix = path.suffix.casefold()
        if suffix not in VALIDATED_SUFFIXES:
            continue
        failure = _validate_json(path) if suffix in JSON_SUFFIXES else _validate_tmdl(path)
        if failure is not None:
            failures.append(failure)
    return failures


def _print_failures(failures: list[ValidationFailure]) -> None:
    for failure in failures:
        print(f"[validate_powerbi] {failure.path}: {failure.detail}")


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
    print("[validate_powerbi] fuentes TMDL/PBIR/PBISM/PBIP estructuralmente validas")


if __name__ == "__main__":
    main()
