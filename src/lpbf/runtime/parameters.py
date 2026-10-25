"""Current fixed-time LPBF runtime parameter construction and stability checks."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from lpbf.data.coupon_inputs import CouponCondition
from lpbf.runtime.configuration import (
    apply_frozen_experiment_configuration,
    load_frozen_experiment_configuration,
)
from lpbf.model.parameters import get_model_parameters


DEVELOPMENT_LAYER_NAME = "layer53"
ALPHA_BASE = 0.565625
M_TED = 1.0
DAQ_DT_S = 5.0e-6
THERMAL_DT_S = 2.5e-6
THERMAL_SUBSTEPS_PER_DAQ = 2
FIXED_DT_S = DAQ_DT_S
CLOCK_TOL_S = 2.0e-15
ENERGY_TOL_J = 2.0e-12


class RuntimeParameterConstructionError(RuntimeError):
    """Fail-closed runtime construction error for dataset/process metadata."""


def base_runtime_params(path: str | Path, condition: CouponCondition):
    """Construct current runtime parameters before the fixed thermal timestep override."""
    h5_path = Path(path)
    base = get_model_parameters()
    runtime = replace(
        base,
        input=replace(base.input, h5_path_select=h5_path, h5_use_file_dialog=False),
        heat_source=replace(base.heat_source, incident_power_W=condition.power_W),
        comparison=replace(base.comparison, layer_name=condition.layer_name or DEVELOPMENT_LAYER_NAME),
    )
    frozen = apply_frozen_experiment_configuration(
        runtime, load_frozen_experiment_configuration()
    )
    supplied_spot_um = float(condition.spot_diameter_mm) * 1000.0
    frozen_spot_um = float(frozen.input.default_spot_size_um)
    if supplied_spot_um != frozen_spot_um:
        raise RuntimeParameterConstructionError(
            "Patch 20.8 may only plumb the accepted 0.08 mm spot diameter without "
            f"changing physics: supplied={supplied_spot_um} um, frozen={frozen_spot_um} um"
        )
    # Explicitly carry the manifest value into runtime construction.  For the
    # supplied 0.08 mm campaign this replacement is byte-for-value neutral.
    return replace(
        frozen,
        input=replace(frozen.input, default_spot_size_um=supplied_spot_um),
    )


def exact_fixed_time_params(path: str | Path, condition: CouponCondition):
    """Return runtime parameters with the frozen 2.5 us thermal timestep."""
    params = base_runtime_params(path, condition)
    return replace(params, time=replace(params.time, dt_s=THERMAL_DT_S))


def explicit_stability_record(params: Any) -> dict[str, Any]:
    """Report the exact explicit stability quantities used by the accepted model."""
    raw = float(
        params.time.explicit_stability_limit_s(
            params.material, params.geometry, params.grid
        )
    )
    safe = float(
        params.time.explicit_stability_limit_with_safety_s(
            params.material, params.geometry, params.grid
        )
    )
    selected = float(params.time.dt_s)
    return {
        "solver_scheme": "3D forward-Euler finite-volume diffusion",
        "selected_dt_s": selected,
        "raw_explicit_limit_s": raw,
        "safe_explicit_limit_s": safe,
        "safety_factor": float(params.time.explicit_stability_safety_factor),
        "selected_over_raw_limit": selected / raw,
        "selected_over_safe_limit": selected / safe,
        "passes_raw_limit": bool(selected <= raw),
        "passes_safe_limit": bool(selected <= safe),
        "grid_spacing_um": float(
            params.grid.uniform_spacing_m(params.geometry) * 1.0e6
        ),
        "liquid_conductivity_enhancement_factor": float(
            params.material.liquid_conductivity_enhancement_factor
        ),
        "effective_liquid_conductivity_W_mK": float(
            params.material.k_liquid_effective_W_mK
        ),
        "alpha_liquid_effective_m2_s": float(params.material.alpha_liquid_effective_m2_s),
        "status": "PASS" if selected <= safe else "FAIL_CLOSED_NUMERICAL_STABILITY",
    }
