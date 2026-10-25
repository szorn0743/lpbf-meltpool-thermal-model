"""Patch 22.3.5.2: the 272-work-unit campaign cannot be dispatched until Patch 22.4.3.2 lifts the lock."""
from __future__ import annotations

import pytest

from lpbf import patch22_4_3_parallel_coarse_calibration_execution as execution
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    CAMPAIGN_DISPATCH_LOCKED_STATUS,
    CAMPAIGN_DISPATCH_REQUIRED_AUTHORIZER,
    CampaignDispatchLocked,
    Patch2243Error,
    _require_campaign_dispatch_authorized,
    _thermal_worker,
    run_search,
)


def test_campaign_dispatch_is_locked_by_default():
    assert execution.CAMPAIGN_DISPATCH_AUTHORIZED_BY is None
    assert CAMPAIGN_DISPATCH_REQUIRED_AUTHORIZER == "22.4.3.2"
    with pytest.raises(CampaignDispatchLocked, match=CAMPAIGN_DISPATCH_LOCKED_STATUS):
        _require_campaign_dispatch_authorized()


def test_lock_is_fail_closed_patch_error():
    assert issubclass(CampaignDispatchLocked, Patch2243Error)


def test_run_search_refuses_before_any_side_effect(tmp_path):
    output = tmp_path / "campaign_output"
    with pytest.raises(CampaignDispatchLocked):
        run_search(
            data_directory=tmp_path / "missing_data",
            characterization_directory=tmp_path / "missing_characterization",
            output_directory=output,
        )
    assert not output.exists()


def test_run_search_resume_is_also_locked(tmp_path):
    output = tmp_path / "campaign_output"
    with pytest.raises(CampaignDispatchLocked):
        run_search(
            data_directory=tmp_path / "missing_data",
            characterization_directory=tmp_path / "missing_characterization",
            output_directory=output,
            resume=True,
        )
    assert not output.exists()


def test_thermal_worker_refuses_before_reading_the_job():
    with pytest.raises(CampaignDispatchLocked):
        _thermal_worker(object())


@pytest.mark.parametrize("other_patch", ["22.4.2", "22.4.3", "22.4.3.1", "22.3.6", ""])
def test_only_patch_22_4_3_2_can_lift_the_lock(monkeypatch, other_patch):
    monkeypatch.setattr(execution, "CAMPAIGN_DISPATCH_AUTHORIZED_BY", other_patch)
    with pytest.raises(CampaignDispatchLocked):
        _require_campaign_dispatch_authorized()
    monkeypatch.setattr(execution, "CAMPAIGN_DISPATCH_AUTHORIZED_BY", "22.4.3.2")
    _require_campaign_dispatch_authorized()
