"""Read-only live demo API and HTML shell."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine, ProductionRecord


def _closed_bucket() -> tuple[datetime, datetime]:
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    end = end.replace(minute=end.minute - end.minute % 15)
    return end - timedelta(minutes=15), end


def test_demo_returns_503_until_live_source_exists(client: TestClient) -> None:
    assert client.get("/api/v1/demo/overview").status_code == 503


def test_demo_overview_uses_exact_oee_service(client: TestClient, migrated_engine: Engine) -> None:
    start, end = _closed_bucket()
    with Session(migrated_engine) as session:
        line = ProductionLine(code="SIM-L1", name="Synthetic Line 1", timezone="America/Monterrey")
        session.add(line)
        session.flush()
        reason = DowntimeReason(code="TEST-U", name="Test stop", default_is_planned=False)
        historical_reason = DowntimeReason(
            code="OLD-U", name="Historical stop", default_is_planned=False
        )
        session.add_all([reason, historical_reason])
        session.flush()
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=start,
                interval_end=end,
                total_count=25,
                good_count=24,
                ideal_cycle_time_seconds=Decimal("30.000"),
                source="simulator-live-v1",
                external_id="demo-bucket",
            )
        )
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=start,
                interval_end=end,
                total_count=999,
                good_count=0,
                ideal_cycle_time_seconds=Decimal("30.000"),
                source="simulator",
                external_id="historical-bucket-must-not-contaminate-demo",
            )
        )
        session.add(
            DowntimeEvent(
                line_id=line.id,
                started_at=start,
                ended_at=start + timedelta(minutes=5),
                reason_id=reason.id,
                is_planned=False,
                source="simulator-live-v1",
                external_id="demo-stop",
            )
        )
        session.add(
            DowntimeEvent(
                line_id=line.id,
                started_at=start,
                ended_at=start + timedelta(minutes=10),
                reason_id=historical_reason.id,
                is_planned=False,
                source="simulator",
                external_id="historical-stop-must-not-contaminate-demo",
            )
        )
        session.commit()

    response = client.get("/api/v1/demo/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["synthetic"] is True
    assert body["refresh_cadence_minutes"] == 15
    assert body["line"]["code"] == "SIM-L1"
    assert body["data_through"] == end.isoformat().replace("+00:00", "Z")
    assert body["total_count"] == 25
    assert body["good_count"] == 24
    assert body["rejected_count"] == 1
    assert isinstance(body["oee"], str)
    assert body["downtime_total_events"] == 1
    assert [item["reason"] for item in body["top_reasons"]] == ["Test stop"]
    assert body["top_reasons"][0]["cumulative_share"] == "1"


def test_demo_page_and_assets_are_public(client: TestClient) -> None:
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/demo"
    page = client.get("/demo")
    assert page.status_code == 200
    assert "Live-updating OEE" in page.text
    assert "Synthetic portfolio data" in page.text
    assert client.get("/demo-assets/demo.css").status_code == 200
    assert client.get("/demo-assets/demo.js").status_code == 200
