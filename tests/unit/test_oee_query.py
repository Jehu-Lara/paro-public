"""The application layer delegates OEE math to the pure domain once."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from paro.application import oee_query
from paro.db.base import Base
from paro.db.models import ProductionLine
from paro.domain.oee import calculate_oee


def test_query_calls_domain_calculator_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    calculator = MagicMock(wraps=calculate_oee)
    monkeypatch.setattr(oee_query, "calculate_oee", calculator)
    with Session(engine) as session:
        line = ProductionLine(code="L1", name="Line 1", timezone="America/Monterrey")
        session.add(line)
        session.commit()
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        oee_query.query_line_oee(
            session, line_id=line.id, start=start, end=start + timedelta(hours=1)
        )
    assert calculator.call_count == 1
