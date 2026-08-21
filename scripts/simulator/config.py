"""Confirmed simulator constants (docs/simulator-spec.md section 10).

Single source of truth: both the generator and any future QA-Agent check
code import from here -- no numeric parameter from simulator-spec.md
section 4 is duplicated anywhere else. Values are ``float``, not
``Decimal``: they feed ``random.gauss``/lognormal sampling, which is
float-native in the stdlib -- there's no Decimal-typed distribution
sampler to use instead. The one simulator output that must stay Decimal
end-to-end (``ideal_cycle_time_seconds``) never derives from these
constants: it's supplied directly as ``Decimal`` by the caller via
``LineConfig`` (see ``model.py``) and passed through unchanged.
"""

from __future__ import annotations

from datetime import time

MASTER_SEED = 42

CYCLE_TIME_MEAN_MULTIPLIER = 1.11
CYCLE_TIME_SD_MULTIPLIER = 0.09
CYCLE_TIME_TRUNC_MIN_MULTIPLIER = 0.95
CYCLE_TIME_TRUNC_MAX_MULTIPLIER = 1.60

MICRO_STOP_LAMBDA_PER_RUN_HOUR = 3.2432
MICRO_STOP_DURATION_MU = 4.0943  # ln(60)
MICRO_STOP_DURATION_SIGMA = 0.5552
MICRO_STOP_DURATION_MIN_SECONDS = 20
MICRO_STOP_DURATION_MAX_SECONDS = 299

FAILURE_LAMBDA_PER_RUN_HOUR = 0.1946
FAILURE_DURATION_MU = 7.3132  # ln(1500)
FAILURE_DURATION_SIGMA = 0.7028
FAILURE_DURATION_MIN_SECONDS = 300
FAILURE_DURATION_MAX_SECONDS = 14400

MICRO_STOP_FAILURE_BOUNDARY_SECONDS = 300

PLANNED_CHANGEOVERS_PER_SHIFT = 1
PLANNED_CHANGEOVER_DURATION_MIN_MINUTES = 20
PLANNED_CHANGEOVER_DURATION_MAX_MINUTES = 40

SCRAP_PROBABILITY_BY_SHIFT: dict[str, float] = {"A": 0.024, "B": 0.028, "C": 0.038}

SHIFT_C_MICRO_STOP_RATE_MULTIPLIER = 1.35
WARMUP_CYCLE_COUNT = 15
WARMUP_SCRAP_MULTIPLIER = 2.5
WARMUP_CYCLE_TIME_MULTIPLIER = 1.15
BOTTLENECK_FAILURE_RATE_MULTIPLIER = 1.8
BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER = 1.4
# Component hazards are divided across machines on a serial line. This
# calibration keeps line-level availability in the documented acceptance
# range after interval-union semantics and boundary-cycle losses are applied.
SERIAL_LINE_EVENT_RATE_FACTOR = 0.8

REASON_MIX_FAILURE_CLASS: dict[str, float] = {
    "mechanical": 0.55,
    "electrical": 0.20,
    "pneumatic": 0.15,
    "sensor": 0.10,
}
REASON_MIX_MICRO_STOP_CLASS: dict[str, float] = {
    "material_jam": 0.55,
    "starvation": 0.30,
    "minor_adjustment": 0.15,
}

PRODUCTION_BUCKET_MINUTES = 15
ACCEPTANCE_DURATION_DAYS = 14
ACCEPTANCE_MACHINE_COUNT = 8
SMOKE_DURATION_DAYS = 1
SMOKE_MACHINE_COUNT = 2

ACCEPTANCE_BAND_SCRAP_PP = 0.005  # absolute
ACCEPTANCE_BAND_MICRO_STOP_RELATIVE = 0.15
ACCEPTANCE_BAND_FAILURE_RELATIVE = 0.25
ACCEPTANCE_BAND_CYCLE_TIME_RELATIVE = 0.03
ACCEPTANCE_BAND_OEE_MIN = 0.70
ACCEPTANCE_BAND_OEE_MAX = 0.80
ACCEPTANCE_BAND_REASON_MIX_RELATIVE = 0.20

# Not in simulator-spec.md section 10 -- the spec never fixes shift A/B/C
# boundaries (see the implementation plan's resolved gap). Shift is pure
# time-of-day arithmetic, never a DB `Shift` lookup: the core generator has
# no I/O.
SHIFT_TIMEZONE = "America/Monterrey"
SHIFT_BOUNDARIES_LOCAL: dict[str, time] = {
    "A": time(6, 0),
    "B": time(14, 0),
    "C": time(22, 0),
}

# `source` for every row the generator emits (idempotency key half, see
# paro.db.repositories). Not in section 10 either; matches the convention
# scripts/seed_demo.py already uses (SOURCE = "seed_demo").
SOURCE = "simulator"
LIVE_SOURCE = "simulator-live-v1"
LIVE_ID_NAMESPACE = "sim-live-v1"

# Downtime-reason catalog codes the generator emits (simulator-spec.md
# section 4.6's table). Same naming convention as scripts/seed_demo.py,
# redefined here (not imported) since that script is a one-off dev seed,
# not a canonical source for these constants.
REASON_PLANNED_CHANGEOVER_CODE = "CHG-P"
REASON_FAILURE_MECHANICAL_CODE = "FLA-M"
REASON_FAILURE_ELECTRICAL_CODE = "FLA-E"
REASON_FAILURE_PNEUMATIC_CODE = "FLA-N"
REASON_FAILURE_SENSOR_CODE = "FLA-S"
REASON_MICRO_STOP_MATERIAL_JAM_CODE = "ATC-M"
REASON_MICRO_STOP_STARVATION_CODE = "DES-M"
REASON_MICRO_STOP_MINOR_ADJUSTMENT_CODE = "AJT-M"

REASON_CODES_BY_FAILURE_CLASS: dict[str, str] = {
    "mechanical": REASON_FAILURE_MECHANICAL_CODE,
    "electrical": REASON_FAILURE_ELECTRICAL_CODE,
    "pneumatic": REASON_FAILURE_PNEUMATIC_CODE,
    "sensor": REASON_FAILURE_SENSOR_CODE,
}
REASON_CODES_BY_MICRO_STOP_CLASS: dict[str, str] = {
    "material_jam": REASON_MICRO_STOP_MATERIAL_JAM_CODE,
    "starvation": REASON_MICRO_STOP_STARVATION_CODE,
    "minor_adjustment": REASON_MICRO_STOP_MINOR_ADJUSTMENT_CODE,
}

# Catalog rows required by every simulator run. Keeping their labels and
# planned/unplanned classification beside the canonical codes prevents the
# production bootstrap and the development seed from drifting apart.
REQUIRED_REASON_CATALOG: dict[str, tuple[str, bool]] = {
    REASON_PLANNED_CHANGEOVER_CODE: ("Cambio de formato", True),
    REASON_FAILURE_MECHANICAL_CODE: ("Falla mecanica", False),
    REASON_FAILURE_ELECTRICAL_CODE: ("Falla electrica", False),
    REASON_FAILURE_PNEUMATIC_CODE: ("Falla neumatica", False),
    REASON_FAILURE_SENSOR_CODE: ("Falla de sensor", False),
    REASON_MICRO_STOP_MATERIAL_JAM_CODE: ("Atasco de material", False),
    REASON_MICRO_STOP_STARVATION_CODE: ("Desabasto de material", False),
    REASON_MICRO_STOP_MINOR_ADJUSTMENT_CODE: ("Ajuste menor", False),
}
