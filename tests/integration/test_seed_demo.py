"""``scripts/seed_demo.py`` es determinista y seguro de correr dos veces.

Corre ``run()`` (la funcion principal del script, no via subprocess) dos veces
consecutivas sobre el mismo archivo SQLite temporal migrado y compara los
conteos por tabla.
"""

from __future__ import annotations

from scripts.seed_demo import run
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason


def test_running_seed_twice_produces_identical_counts(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        counts_first_run = run(session)

    with Session(migrated_engine) as session:
        counts_second_run = run(session)

    assert counts_first_run == counts_second_run
    assert counts_first_run["downtime_event"] == 4
    assert counts_first_run["production_record"] == 1
    assert counts_first_run["downtime_reason"] == 9


def test_seed_contains_the_full_downtime_reason_catalog(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        run(session)

        rows = session.execute(select(DowntimeReason.code, DowntimeReason.default_is_planned)).all()
        codes_and_planned = {row.code: row.default_is_planned for row in rows}

    assert codes_and_planned == {
        "MTN-P": True,
        "CHG-P": True,
        "FLA-M": False,
        "FLA-E": False,
        "FLA-N": False,
        "FLA-S": False,
        "ATC-M": False,
        "DES-M": False,
        "AJT-M": False,
    }


def test_seed_contains_an_open_downtime_event(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        run(session)

        open_events = (
            session.execute(select(DowntimeEvent).where(DowntimeEvent.ended_at.is_(None)))
            .scalars()
            .all()
        )

    assert len(open_events) == 1


def test_seed_contains_two_overlapping_downtime_events(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        run(session)

        events = (
            session.execute(
                select(DowntimeEvent).where(DowntimeEvent.external_id.like("downtime-overlap-%"))
            )
            .scalars()
            .all()
        )

    assert len(events) == 2
    first, second = sorted(events, key=lambda event: event.started_at)
    assert first.ended_at is not None
    assert second.started_at < first.ended_at  # se solapan de verdad
