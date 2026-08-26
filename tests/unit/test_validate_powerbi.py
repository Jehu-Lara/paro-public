"""Structural validation for Power BI source artifacts."""

from pathlib import Path

import pytest
import scripts.validate_powerbi as validator


def test_current_powerbi_tree_passes_structural_validation() -> None:
    assert validator.run(Path("PowerBi")) == []


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("broken.pbir", b"{"),
        ("broken.PBIP", b"{"),
        ("empty.tmdl", b""),
        ("nul.tmdl", b"model\x00truncated"),
        ("bad-utf8.tmdl", b"\xff"),
        ("json-disguised.tmdl", b'{"model": "not-tmdl"}'),
        ("open-paren.tmdl", b"measure X = SUM("),
        ("open-quote.tmdl", b"table 'Broken"),
    ],
)
def test_invalid_powerbi_source_exits_nonzero_and_names_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    filename: str,
    payload: bytes,
) -> None:
    powerbi_dir = tmp_path / "PowerBi"
    powerbi_dir.mkdir()
    invalid_file = powerbi_dir / filename
    invalid_file.write_bytes(payload)
    monkeypatch.setattr(validator, "POWERBI_DIR", powerbi_dir)

    with pytest.raises(SystemExit) as exc_info:
        validator.main()

    assert exc_info.value.code == 1
    assert filename in capsys.readouterr().out


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("balanced-paren.tmdl", b"measure X = SUM(1)"),
        ("balanced-quote.tmdl", b"table 'Ok'"),
        ("escaped-quote.tmdl", b"table 'It''s Ok'"),
    ],
)
def test_balanced_tmdl_source_passes(
    tmp_path: Path,
    filename: str,
    payload: bytes,
) -> None:
    valid_file = tmp_path / filename
    valid_file.write_bytes(payload)

    assert validator.run(tmp_path) == []
