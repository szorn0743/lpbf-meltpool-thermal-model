from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from lpbf.model.laser_component_association import CONTINUOUS_DISTANCE_METRIC
from lpbf.patch22_3_5_1_frozen_revalidation import (
    EXPECTED_DISTANCE_BINS,
    FROZEN_AUDIT_STATUS,
    classify_replay_observation,
    freeze_historical_audit,
    run_frozen_revalidation,
    summarize_reclassification,
)


def _result_payload(observations: list[dict], *, candidate: str = "anchor_center") -> dict:
    return {
        "payload": {
            "candidate_id": candidate,
            "member_identity": "20260730:part_1",
            "work_unit_id": f"test-{candidate}",
            "production_hw_semantics_version": "22.3.4",
            "production_hw_association_policy_version": "22.3.3",
            "atomic_failure_evaluation": {"observations": observations},
        }
    }


def _historical_observation(frame: int, distance: float) -> dict:
    return {
        "frame_index": frame,
        "mapped_process_row": frame + 1000,
        "observation_diagnostics": {
            "production_hw_association_status": FROZEN_AUDIT_STATUS,
            "production_hw_association_min_distance_cells": distance,
            "cell_spacing_um": 16.0,
            "source_center_local_x_mm": 0.8,
            "source_center_local_y_mm": 0.8,
            "peak_surface_radial_distance_from_laser_mm": 0.02,
            "liquidus_component_count": 1,
            "liquidus_contour_boundary_contact": False,
        },
    }


def _complete_frozen_fixture() -> list[dict]:
    rows: list[dict] = []
    frame = 1
    for _ in range(EXPECTED_DISTANCE_BINS["exact_sqrt2"]):
        rows.append(_historical_observation(frame, 2.0**0.5))
        frame += 1
    for _ in range(EXPECTED_DISTANCE_BINS["exact_two"]):
        rows.append(_historical_observation(frame, 2.0))
        frame += 1
    for offset in range(EXPECTED_DISTANCE_BINS["between_two_and_five"]):
        rows.append(_historical_observation(frame, 2.5 + 0.1 * offset))
        frame += 1
    for offset in range(EXPECTED_DISTANCE_BINS["greater_than_five"]):
        rows.append(_historical_observation(frame, 6.0 + offset))
        frame += 1
    return rows


def test_freeze_historical_audit_accepts_the_authoritative_516_population(tmp_path: Path):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(_result_payload(_complete_frozen_fixture())), encoding="utf-8"
    )

    frozen = freeze_historical_audit(result_path.parent)

    assert frozen["status"] == "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
    assert frozen["observed_unique_failure_count"] == 516
    assert frozen["observed_distance_bins"] == {
        **EXPECTED_DISTANCE_BINS,
        "other": 0,
    }
    assert frozen["calibration_search_authorized"] is False
    assert frozen["parameter_fitting_performed"] is False
    assert frozen["full_campaign_dispatched"] is False


def test_freeze_historical_audit_rejects_the_earlier_incomplete_snapshot(tmp_path: Path):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(_result_payload(_complete_frozen_fixture()[:366])), encoding="utf-8"
    )

    frozen = freeze_historical_audit(result_path.parent)

    assert frozen["status"] == "FAIL_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
    assert frozen["observed_unique_failure_count"] == 366
    assert any("516" in message for message in frozen["failures"])


def test_freeze_historical_audit_reads_windows_style_zip_entries(tmp_path: Path):
    archive_path = tmp_path / "partial.zip"
    content = json.dumps(_result_payload(_complete_frozen_fixture())).encode("utf-8")
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            r"run_20261013_115118\work_units\candidate\result.json", content
        )

    frozen = freeze_historical_audit(archive_path)

    assert frozen["status"] == "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
    assert frozen["source_result_file_count"] == 1


def _historical_row(old_bin: str = "exact_sqrt2") -> dict:
    return {
        "candidate_id": "anchor_center",
        "member_identity": "20260730:part_1",
        "frame_index": 13768,
        "mapped_process_row": 37330,
        "old_distance_cells": 2.0**0.5,
        "old_distance_bin": old_bin,
    }


def _replayed_observation(
    status: str,
    *,
    metric: str | None = CONTINUOUS_DISTANCE_METRIC,
    boundary: bool = False,
    finite_hw: bool = True,
) -> dict:
    return {
        "simulated_H_pixels": 12.0 if finite_hw else None,
        "simulated_W_pixels": 6.0 if finite_hw else None,
        "observation_diagnostics": {
            "production_hw_association_status": status,
            "production_hw_association_distance_metric": metric,
            "production_hw_association_min_distance_cells": 0.85,
            "production_hw_association_min_distance_mm": 0.0136,
            "production_hw_association_mode": "unique_nearest_fallback",
            "production_hw_component_status": "SELECTED" if status == "SELECTED" else status,
            "production_hw_simulated_H_pixels": 12.0 if finite_hw else None,
            "production_hw_simulated_W_pixels": 6.0 if finite_hw else None,
            "liquidus_contour_boundary_contact": boundary,
        },
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("FAIL_CLOSED_DISTANCE_EXCEEDED", "STILL_OUTSIDE_PHYSICAL_TOLERANCE"),
        ("FAIL_CLOSED_TIED_NEAREST", "AMBIGUOUS_TIED"),
        ("ZERO_FOOTPRINT", "OTHER_FAILURE"),
    ],
)
def test_replay_reclassification_preserves_remote_and_ambiguous_fail_closed_states(
    status: str, expected: str
):
    result = classify_replay_observation(
        _replayed_observation(status), historical_row=_historical_row()
    )
    assert result["reclassification"] == expected


def test_replay_reclassification_accepts_only_finite_enclosed_continuous_selection():
    corrected = classify_replay_observation(
        _replayed_observation("SELECTED"), historical_row=_historical_row()
    )
    boundary = classify_replay_observation(
        _replayed_observation("SELECTED", boundary=True), historical_row=_historical_row()
    )
    nonfinite = classify_replay_observation(
        _replayed_observation("SELECTED", finite_hw=False), historical_row=_historical_row()
    )

    assert corrected["reclassification"] == "CORRECTED_BY_CONTINUOUS_DISTANCE"
    assert boundary["reclassification"] == "OTHER_FAILURE"
    assert nonfinite["reclassification"] == "OTHER_FAILURE"


def test_replay_reclassification_requires_the_continuous_metric():
    result = classify_replay_observation(
        _replayed_observation("SELECTED", metric="cell_center_index_compatibility"),
        historical_row=_historical_row(),
    )
    assert result["reclassification"] == "OTHER_FAILURE"


def test_missing_replay_frame_is_not_silently_counted_as_corrected():
    result = classify_replay_observation(None, historical_row=_historical_row())
    assert result["reclassification"] == "REPLAY_INCOMPLETE"


def test_reclassification_summary_separates_diagonal_population():
    rows = [
        {
            "old_distance_bin": "exact_sqrt2",
            "reclassification": "CORRECTED_BY_CONTINUOUS_DISTANCE",
        },
        {
            "old_distance_bin": "exact_sqrt2",
            "reclassification": "STILL_OUTSIDE_PHYSICAL_TOLERANCE",
        },
        {
            "old_distance_bin": "greater_than_five",
            "reclassification": "STILL_OUTSIDE_PHYSICAL_TOLERANCE",
        },
    ]
    summary = summarize_reclassification(rows)
    assert summary["total_reclassified_rows"] == 3
    assert summary["sqrt2_total"] == 2
    assert summary["sqrt2_counts"]["CORRECTED_BY_CONTINUOUS_DISTANCE"] == 1
    assert summary["sqrt2_counts"]["STILL_OUTSIDE_PHYSICAL_TOLERANCE"] == 1


def test_input_only_run_writes_a_non_campaign_report(tmp_path: Path):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(_result_payload(_complete_frozen_fixture())), encoding="utf-8"
    )
    output = tmp_path / "output"

    report = run_frozen_revalidation(
        partial_run_input=result_path.parent,
        output_directory=output,
        run_live=False,
    )

    assert report["status"] == "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
    assert report["full_campaign_dispatched"] is False
    assert (output / "PATCH_22_3_5_1_FROZEN_FAILURE_MANIFEST.json").is_file()
    assert (output / "PATCH_22_3_5_1_FROZEN_REVALIDATION_REPORT.json").is_file()
