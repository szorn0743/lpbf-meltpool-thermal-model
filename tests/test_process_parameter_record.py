"""Guards the read-only experimental process-parameter record (docs/reference/LPBF_Process_Parameters.csv).

The experiments were run with these values; the record must never change. Any edit fails the hash test.
The cross-checks keep the code-side copies of the same values (the Patch 21.0 contract and the canonical
coupon manifest) consistent with the experimental record.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "reference" / "LPBF_Process_Parameters.csv"
RECORD_SHA256 = "15faa033e51025698ccf138db760fa6e80e8ecce9e5389016dc4d440d602f304"
COLUMNS = [
    "Part Number",
    "Power (W)",
    "Travel Speed (mm/s)",
    "Spot Size (mm)",
    "Area Power Density (J/mm2)",
    "Volumetric Power Density (J/mm3)",
    "Date",
]
# Same for all 24 coupons (owner); values from Satterlee dissertation draft (2026-07-20) section 4.2.
HATCH_SPACING_MM = Decimal("0.080")
LAYER_THICKNESS_MM = Decimal("0.030")
MANIFEST_FIELDS = {
    "Power (W)": "nominal_power_W",
    "Travel Speed (mm/s)": "nominal_speed_mm_s",
    "Spot Size (mm)": "spot_diameter_mm",
    "Area Power Density (J/mm2)": "supplied_power_density_J_mm2",
    "Volumetric Power Density (J/mm3)": "supplied_power_density_J_mm3",
}


def _record_rows() -> dict[tuple[str, int], dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(RECORD.read_bytes().decode("utf-8"))))
    keyed = {}
    for row in rows:
        month, day, year = row["Date"].split("/")
        keyed[(f"{year}{int(month):02d}{int(day):02d}", int(row["Part Number"]))] = row
    assert len(keyed) == len(rows), "duplicate (date, part) rows in the process-parameter record"
    return keyed


def test_process_parameter_record_is_unchanged():
    assert hashlib.sha256(RECORD.read_bytes()).hexdigest() == RECORD_SHA256


def test_process_parameter_record_shape():
    rows = list(csv.DictReader(io.StringIO(RECORD.read_bytes().decode("utf-8"))))
    assert len(rows) == 24
    assert list(rows[0]) == COLUMNS
    assert len(_record_rows()) == 24


def test_record_energy_densities_follow_from_hatch_and_layer_thickness():
    # P_C = P / (v d) and P_E = P / (v h t), rounded half-up as recorded (e.g. 2.125 -> 2.13).
    for key, row in _record_rows().items():
        power, speed, spot = (Decimal(row[c]) for c in ("Power (W)", "Travel Speed (mm/s)", "Spot Size (mm)"))
        areal = (power / (speed * spot)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        volumetric = (power / (speed * HATCH_SPACING_MM * LAYER_THICKNESS_MM)).quantize(Decimal("0.1"), ROUND_HALF_UP)
        assert areal == Decimal(row["Area Power Density (J/mm2)"]), key
        assert volumetric == Decimal(row["Volumetric Power Density (J/mm3)"]), key


def test_calibration_contract_power_speed_match_record():
    record = _record_rows()
    partition = json.loads((ROOT / "src/lpbf/data/patch21_0_calibration_contract.json").read_text())["data_partition"]
    members = partition["calibration_members"] + partition["validation_members"]
    assert {(m["acquisition_set_id"], m["part_number"]) for m in members} == set(record)
    for m in members:
        row = record[(m["acquisition_set_id"], m["part_number"])]
        assert float(row["Power (W)"]) == m["power_W"]
        assert float(row["Travel Speed (mm/s)"]) == m["speed_mm_s"]


def test_campaign_execution_process_conditions_match_record():
    from lpbf.patch22_4_3_parallel_coarse_calibration_execution import EXPECTED_PROCESS_CONDITIONS

    record = _record_rows()
    from_code = {
        (set_id, part): condition
        for set_id, conditions in EXPECTED_PROCESS_CONDITIONS.items()
        for part, condition in enumerate(conditions, start=1)
    }
    assert set(from_code) == set(record)
    for key, (power, speed) in from_code.items():
        assert (float(record[key]["Power (W)"]), float(record[key]["Travel Speed (mm/s)"])) == (power, speed), key


def test_coupon_manifest_process_conditions_match_record():
    record = _record_rows()
    members = json.loads((ROOT / "src/lpbf/data/full_coupon_dataset_manifest.json").read_text())["members"]
    assert {(m["acquisition_set_id"], m["part_number"]) for m in members} == set(record)
    for m in members:
        row = record[(m["acquisition_set_id"], m["part_number"])]
        for column, field in MANIFEST_FIELDS.items():
            assert float(row[column]) == float(m[field]), (m["acquisition_set_id"], m["part_number"], column)
