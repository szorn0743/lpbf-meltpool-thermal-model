"""
Simulation parameters for a cell-centered explicit finite-volume 3D
transient conductive heat-transfer solver with apparent-heat-capacity
solid/mushy/liquid material properties.

Governing equation:
    rho * cp_eff(T) * dT/dt = div(k(T) grad T) + q_dot

Conventions:
    - User-facing lengths are entered in mm.
    - Internal lengths are converted to meters.
    - User-facing temperatures are entered in degC.
    - Internal temperatures are converted to Kelvin.
    - Grid is cell-centered and uniform Cartesian.
    - Temperature array shape is (Nx, Ny, Nz).
    - Every T[i, j, k] represents one physical control volume.
    - Uniform cubic cells are required: dx = dy = dz.
    - Explicit time step is checked but never auto-adjusted.

Phase-change model:
    - Solid below or at the solidus temperature.
    - Mushy strictly between solidus and liquidus.
    - Liquid at or above the liquidus temperature.
    - Latent heat of fusion is represented only through apparent heat capacity
      in the mushy interval.
    - Density is constant.
    - The fixed boiling threshold may drive an optional reduced-order top-surface
      energy-loss surrogate; there is still no mass removal, vapor phase, recoil,
      keyhole, or hard temperature cap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import isclose, isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Literal

# Absolute project paths
# This file lives in: Thesis/Source/parameters.py
# Project root is:    Thesis/
SOURCE_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
DEFAULT_INPUT_H5_PATH = SOURCE_DIRECTORY / "selected_layers_part1.h5"

# -----------------------------
# Unit conversion constants
# -----------------------------

MM_TO_M = 1.0e-3
C_TO_K = 273.15

# Patch 10.4.1: fixed LPBF machine beam geometry for the current experiment.
MACHINE_SPOT_DIAMETER_UM = 80.0
MACHINE_GAUSSIAN_RADIUS_MM = 0.040

# Patch 12.1.0: production source-calibration definitions frozen from the
# accepted Patch 10.1/10.4 state.  These constants do not change the generic
# SimulationParameters defaults; they provide an explicit contract that the
# Patch 12.1 calibration entry point can enforce without affecting synthetic or
# legacy test configurations.
SOURCE_CALIBRATION_GRID_NAME_12_1 = "16um"
SOURCE_CALIBRATION_HW_GEOMETRY_METHOD_12_1 = "interpolated_liquidus_contour"


# Patch 11.1.0: immutable provenance for the empirical polished-316L
# On-Axis TED reference-plate calibration. These values identify the raw
# calibration evidence and the analysis settings only; they do not alter
# production TED numerics or constitute a 100%-return calibration.
@dataclass(frozen=True)
class TEDEmpiricalCalibrationProvenance:
    calibration_file_name: str = "reflect_bare_plate_no_melt_3.h5"
    calibration_file_sha256: str = (
        "cfb5d9faebe716bbe4556fd2033a9ecf6354e868baaa17ac02acc7dd702d10f0"
    )
    calibration_file_relative_path: str = (
        "calibration_evidence/reflect_bare_plate_no_melt_3.h5"
    )
    calibration_analysis_utility_relative_path: str = (
        "calibration_tools/laser_h5_lookup_tool_v3.py"
    )

    ted_channel_path: str = "/LASERS/1/On-Axis TED"
    laser_drive_channel_path: str = "/LASERS/1/Laser Drive"
    x_position_channel_path: str = "/LASERS/1/X-Position"
    y_position_channel_path: str = "/LASERS/1/Y-Position"
    raw_laser_power_channel_path: str = "/LASERS/1/Laser Power"
    acquisition_sample_rate_hz: float = 100_000.0

    assigned_physical_powers_W: tuple[float, ...] = (
        190.0,
        180.0,
        170.0,
        160.0,
        150.0,
        140.0,
        130.0,
        120.0,
        110.0,
        100.0,
        90.0,
        80.0,
    )
    angular_line_count: int = 12
    power_start_high_theta_clusters: int = 3
    auto_center_policy: str = "range_midpoint"

    pulse_detection_threshold_mode: str = "auto"
    pulse_detection_threshold_algorithm: str = (
        "p05/p95 midpoint with observed-maximum fallback when p95 equals off-state"
    )
    minimum_pulse_width_ms: float = 0.50
    merge_gap_ms: float = 0.02
    pre_pulse_baseline_window_ms: float = 0.50
    post_pulse_response_window_ms: float = 3.00

    reference_plate_material: str = "316 stainless steel"
    surface_preparation_description: str = "polished"

    beam_wavelength_nm: float | None = None
    beam_wavelength_status: str = "unavailable"
    detector_acquisition_configuration: str | None = None
    detector_acquisition_configuration_status: str = "unavailable"


TED_EMPIRICAL_CALIBRATION_PROVENANCE_11_1_0 = (
    TEDEmpiricalCalibrationProvenance()
)


# Patch 11.1.1: deterministic reproduction fingerprints for the retained
# authoritative v3 calibration procedure applied to the frozen bare-plate file.
# These are extraction/assignment fingerprints only; they do not select a TED
# response statistic or fit a new plate-response model.
@dataclass(frozen=True)
class TEDEmpiricalCalibrationReproductionExpectations:
    expected_pulse_count: int = 60
    expected_registered_line_count: int = 12
    expected_shots_per_registered_line: int = 5
    expected_drive_threshold: float = 2.5
    expected_center_x: float = 0.0482177734375
    expected_center_y: float = 0.33672332763671875
    expected_power_registration_start_angle_deg: float = 269.8769858527479
    pulse_index_sha256: str = (
        "9fedb336c73a6a51d4aa80181ffaddcc4a2d9e973e50a9589a8b4851daf8c2d4"
    )
    shot_geometry_sha256: str = (
        "8f5815547aa782fc07739952825e523336db4b8a99b2beb9b084c68046a16567"
    )
    registered_power_assignment_sha256: str = (
        "4cacd98e0781d791f452e8cc7461a3e54bdad92ac8879314b974d800e23889b7"
    )
    power_level_response_statistics_sha256: str = (
        "36eefcb480c6e93b79c5253a1c85cca84995162d7663ff86113bab087812195c"
    )


TED_EMPIRICAL_CALIBRATION_REPRODUCTION_EXPECTATIONS_11_1_1 = (
    TEDEmpiricalCalibrationReproductionExpectations()
)


# Patch 11.1.2: TED-only response-statistic comparison settings.  The robust
# steady-pulse candidate uses the central portion of each detected pulse, well
# away from turn-on/turn-off transients, and is admitted only when a common
# power-level temporal-stability screen is met.  These settings do not use
# process-build H/W data and do not define the final TED plate-response fit.
@dataclass(frozen=True)
class TEDEmpiricalResponseStatisticComparisonSettings:
    steady_pulse_phase_start: float = 0.35
    steady_pulse_phase_end: float = 0.65
    steady_profile_points: int = 61
    steady_max_relative_end_to_end_drift: float = 0.20
    steady_min_power_level_pass_fraction: float = 0.90


TED_EMPIRICAL_RESPONSE_STATISTIC_COMPARISON_SETTINGS_11_1_2 = (
    TEDEmpiricalResponseStatisticComparisonSettings()
)

# Frozen Patch 11.1.2 statistic identity.  The analysis report must reproduce
# this TED-evidence-only decision before later empirical calibration patches may
# consume it.
TED_EMPIRICAL_SELECTED_RESPONSE_STATISTIC_11_1_2 = "peak_minus_local_baseline"

# Patch 11.1.4 model-form selection identity. The coefficients remain computed
# from the authoritative bare-plate evidence; Patch 11.1.5 is responsible for
# freezing the complete empirical calibration record.
TED_EMPIRICAL_SELECTED_PLATE_RESPONSE_MODEL_11_1_4 = "unconstrained_linear"

# Patch 11.1.5 immutable empirical 316L calibration identity.  The analysis
# procedure hash refers to the retained standalone calibration utility frozen in
# Patch 11.1.0; the canonical calibration-record hash is populated from the
# reproducible Patch 11.1 analysis, never from manual transcription.
TED_EMPIRICAL_ANALYSIS_CODE_SHA256_11_1_5 = (
    "6e7ca084f4b8bed4957c15d2867d4b90807146bdfbb70ef05ff303a11a301b56"
)
TED_EMPIRICAL_CALIBRATION_RECORD_RELATIVE_PATH_11_1_5 = (
    "validated_baselines/lpbf_11_1_5_empirical_ted_calibration.json"
)
TED_EMPIRICAL_CALIBRATION_RECORD_SHA256_11_1_5 = (
    "71e3d8cc6516781650b50066ac720d3486f8aa84c529b201333784d3ce570e52"
)


# Patch 11.2.0: predeclared effective-reflectivity sensitivity study for the
# polished 316L TED reference plate.  These are upstream optical-calibration
# assumptions only.  Patch 11.2.0 intentionally does not apply them to process
# TED numerics or use process-build H/W evidence.
@dataclass(frozen=True)
class TEDReferencePlateReflectivityStudySettings:
    candidate_effective_reflectivities: tuple[float, ...] = (
        0.50,
        0.55,
        0.60,
        0.65,
        0.70,
    )
    nominal_effective_reflectivity: float = 0.60
    required_nominal_neighborhood: tuple[float, ...] = (0.55, 0.60, 0.65)
    physical_lower_bound_exclusive: float = 0.0
    physical_upper_bound_inclusive: float = 1.0


TED_REFERENCE_PLATE_REFLECTIVITY_STUDY_SETTINGS_11_2_0 = (
    TEDReferencePlateReflectivityStudySettings()
)

# Patch 11.2.1 reruns the reflectivity-aware physicality gate against the
# active source-driving TED baseline retained by Patch 10.2.5.  The
# TED-evidence-selected local-time repair was not adopted because it failed the
# existing material-violation gate, so changing baseline model here would add a
# second optical-calibration degree of freedom beyond the predeclared plate
# reflectivity assumption.
TED_REFLECTIVITY_PHYSICALITY_BASELINE_MODEL_11_2_1 = "global_laser_off_median"

# Patch 11.2.2 freezes the pre-existing material-violation uncertainty logic
# used by the TED physicality gate. The absolute TED uncertainty remains
# data-derived from the selected laser-off residuals; only the historical
# estimator constants and the exact physical reflected-fraction interval are
# frozen here so they cannot be widened or tuned during the reflectivity study.
TED_UNCERTAINTY_ROBUST_SIGMA_SCALE_11_2_2 = 1.4826
TED_UNCERTAINTY_SIGMA_MULTIPLIER_11_2_2 = 3.0
TED_PHYSICAL_REFLECTED_FRACTION_INTERVAL_11_2_2 = (0.0, 1.0)


def _mm_to_m(value_mm: float) -> float:
    return value_mm * MM_TO_M


def _celsius_to_kelvin(value_C: float) -> float:
    return value_C + C_TO_K


# -----------------------------
# Parameter data structures
# -----------------------------

@dataclass(frozen=True)
class InputControls:
    """
    External data inputs for the moving-window simulation.

    HDF5 is the production input path. Edit h5_path_select here, or set
    h5_use_file_dialog=True to choose an HDF5 file in a file-explorer dialog
    when the workflow starts.
    """

    h5_path_select: Path = DEFAULT_INPUT_H5_PATH
    h5_use_file_dialog: bool = False
    h5_fallback_fs_hz: float | None = None
    default_spot_size_um: float = MACHINE_SPOT_DIAMETER_UM
    laser_drive_threshold: float | None = None
    ted_reference_slope: float = 0.001547
    ted_reference_intercept: float = -0.0341
    # Patch 11.2.0 nominal upstream optical-calibration assumption.  The
    # value is exercised by the Patch 11.2 diagnostic/gating analyses but does
    # not become an adopted source-driving TED calibration unless the Patch
    # 11.2.5 adoption gate passes.
    ted_reference_plate_effective_reflectivity: float = 0.60
    ted_baseline_policy: str = "global_laser_off_median"
    ted_baseline_evidence_policy: str = "robust_laser_off_segments"
    ted_off_segment_outlier_sigma_multiplier: float = 3.0
    h5_baseline_max_samples: int = 2_000_000

    # Patch 9.6.5 diagnostic acceptance band, explicitly preserved by Patch
    # 11.2.2. Raw TED reflection values may cross the physical [0, 1] interval
    # by this many robust off-state noise sigmas before the excursion is
    # classified as a material calibration violation. The physical interval
    # itself is not widened, and this does not change source-driving clipping
    # behavior.
    ted_clip_acceptance_sigma_multiplier: float = 3.0


@dataclass(frozen=True)
class HeatSourceParameters:
    """
    User-facing heat-source inputs.

    Length inputs are in mm and converted internally to meters. During an HDF5
    moving-window run, TED supplies row-specific absorptivity modulation while
    the physical incident power and deposition depth remain configured here.
    """

    # Manual physical laser power for production HDF5 input. Do not use the
    # HDF5 "Laser Power" channel as physical watts; that channel is raw analog.
    incident_power_W: float = 150.0

    # Static/default absorptivity for direct heat-source construction. In the
    # HDF5 moving-window workflow this value is replaced row-by-row by the
    # TED-derived effective_absorptivity after applying calibration_factor.
    absorptivity: float = 0.35

    # Absolute deposited-power scale for production HDF5/TED modulation.
    # The TED signal still determines row-to-row modulation; this multiplier
    # prevents the diagnostic TED-derived value from being treated as a fully
    # calibrated physical absorptivity by itself.
    calibration_factor: float = 0.35

    # Fallback Gaussian radius in mm. In HDF5 production runs the moving-window
    # workflow computes this from InputControls.default_spot_size_um. With
    # the default 80 um diameter and spot_size_um_is_diameter=True, R = 0.04 mm.
    gaussian_radius_mm: float = MACHINE_GAUSSIAN_RADIUS_MM

    # Depth below the top surface over which energy is deposited.
    depth_mm: float = 0.10

    # Optional center override. Moving-window production runs normally keep
    # these as None and let the driver center/offset the source row-by-row.
    center_x_mm: float | None = None
    center_y_mm: float | None = None

    @property
    def deposited_power_W(self) -> float:
        return self.incident_power_W * self.absorptivity

    @property
    def gaussian_radius_m(self) -> float:
        return self.gaussian_radius_mm * MM_TO_M

    @property
    def depth_m(self) -> float:
        return self.depth_mm * MM_TO_M

    def center_x_m(self, params: "SimulationParameters") -> float:
        if self.center_x_mm is None:
            return 0.5 * params.geometry.Lx_m
        return self.center_x_mm * MM_TO_M

    def center_y_m(self, params: "SimulationParameters") -> float:
        if self.center_y_mm is None:
            return 0.5 * params.geometry.Ly_m
        return self.center_y_mm * MM_TO_M

    def validate(self, params: "SimulationParameters") -> None:
        if self.incident_power_W < 0.0:
            raise ValueError("incident_power_W must be nonnegative.")

        if not (0.0 <= self.absorptivity <= 1.0):
            raise ValueError("absorptivity must be between 0 and 1.")

        if not (0.0 <= self.calibration_factor <= 1.0):
            raise ValueError("calibration_factor must be between 0 and 1.")

        if self.gaussian_radius_mm <= 0.0:
            raise ValueError("gaussian_radius_mm must be positive.")

        if self.depth_mm <= 0.0:
            raise ValueError("depth_mm must be positive.")

        if self.depth_m > params.geometry.Lz_m:
            raise ValueError(
                "Heat-source depth exceeds the simulation-domain thickness.\n"
                f"  depth = {self.depth_m:.6e} m\n"
                f"  Lz    = {params.geometry.Lz_m:.6e} m"
            )

        cx = self.center_x_m(params)
        cy = self.center_y_m(params)

        if not (0.0 <= cx <= params.geometry.Lx_m):
            raise ValueError("Heat-source center_x_mm lies outside the domain.")

        if not (0.0 <= cy <= params.geometry.Ly_m):
            raise ValueError("Heat-source center_y_mm lies outside the domain.")


@dataclass(frozen=True)
class MovingWindowControls:
    """Numerical controls specific to the moving-window behavior.

    ``reset_distance_threshold_mm`` marks a machine-coordinate jump large
    enough that the local computational window is treated as having moved to
    a physically remote region. ``large_jump_policy`` makes the resulting
    action explicit: because this model has no larger/global thermal-history
    field from which to initialize a remote window, the supported policy is to
    reset the local field to bulk temperature rather than transplanting the
    prior local thermal state.

    ``reset_on_new_powered_scan_after_off`` is a separate legacy opt-in; the
    production default keeps ordinary laser-off intervals from being treated
    as spatial discontinuities.
    """

    reset_distance_threshold_mm: float = 0.168
    large_jump_policy: Literal["reset_to_bulk"] = "reset_to_bulk"
    reset_on_new_powered_scan_after_off: bool = False
    spot_size_um_is_diameter: bool = True


@dataclass(frozen=True)
class MaterialProperties:
    """
    First-pass engineering material properties for 316L stainless steel.

    These values are intended as defensible starting points, not calibrated
    LPBF material data. They should be tuned later against melt-pool geometry,
    pyrometer observations, absorptivity calibration, and post-print etching.

    The solver currently treats powder and re-solidified/refused metal as the
    same solid phase. Density is constant across all regimes.
    """

    name: str = "316L stainless steel, phase-aware first-pass engineering model"

    # Constant density for all phases, kg/m^3.
    density_kg_m3: float = 7950.0

    # Approximate 316L melting interval. User-facing values remain in Celsius;
    # solver code reads the Kelvin properties below.
    T_solidus_C: float = 1375.0
    T_liquidus_C: float = 1400.0

    # Fixed approximate boiling threshold for stainless steel/316L. Historically
    # diagnostic-only; Patch 16.5.3 also uses this same non-fitted threshold to
    # activate an optional reduced-order top-surface energy-loss surrogate. It
    # still does not trigger mass loss, vapor dynamics, recoil, or temperature capping.
    T_boiling_C: float = 2860.0

    # Latent heat of fusion, J/kg. First-pass literature/engineering value.
    latent_heat_fusion_J_kg: float = 260000.0

    # Three-regime sensible heat capacities, J/(kg*K).
    cp_solid_J_kgK: float = 500.0
    cp_mushy_J_kgK: float = 650.0
    cp_liquid_J_kgK: float = 820.0

    # Physical three-regime thermal conductivities, W/(m*K).
    # Naming convention: ``k_<phase>_W_mK`` denotes a material-property input.
    # Do not fold reduced-order transport corrections into these base values.
    k_solid_W_mK: float = 15.0
    k_mushy_W_mK: float = 22.0
    k_liquid_W_mK: float = 30.0

    # Dimensionless reduced-order closure for unresolved liquid-metal convection.
    # Ck = 1 disables the closure. Ck > 1 enhances conduction only in cells at
    # or above liquidus. The scalar multiplier is intentionally isotropic: the
    # same effective liquid conductivity is used for x-, y-, and z-face fluxes.
    # Keep this factor separate from k_liquid_W_mK so calibration remains auditable.
    liquid_conductivity_enhancement_factor: float = 2.0

    @property
    def T_solidus_K(self) -> float:
        return _celsius_to_kelvin(self.T_solidus_C)

    @property
    def T_liquidus_K(self) -> float:
        return _celsius_to_kelvin(self.T_liquidus_C)

    @property
    def T_boiling_K(self) -> float:
        return _celsius_to_kelvin(self.T_boiling_C)

    @property
    def mushy_temperature_interval_K(self) -> float:
        return self.T_liquidus_K - self.T_solidus_K

    @property
    def cp_eff_mushy_J_kgK(self) -> float:
        """Mushy apparent heat capacity including latent heat of fusion."""
        return (
            self.cp_mushy_J_kgK
            + self.latent_heat_fusion_J_kg / self.mushy_temperature_interval_K
        )

    @property
    def alpha_solid_m2_s(self) -> float:
        return self.k_solid_W_mK / (self.density_kg_m3 * self.cp_solid_J_kgK)

    @property
    def alpha_mushy_m2_s(self) -> float:
        return self.k_mushy_W_mK / (self.density_kg_m3 * self.cp_eff_mushy_J_kgK)

    @property
    def k_liquid_effective_W_mK(self) -> float:
        """Solver liquid conductivity including the isotropic Ck closure."""
        return self.k_liquid_W_mK * self.liquid_conductivity_enhancement_factor

    @property
    def alpha_liquid_effective_m2_s(self) -> float:
        """Effective liquid diffusivity used by the solver and stability check."""
        return self.k_liquid_effective_W_mK / (
            self.density_kg_m3 * self.cp_liquid_J_kgK
        )

    @property
    def maximum_thermal_diffusivity_m2_s(self) -> float:
        """
        Conservative maximum diffusivity used for explicit stability checks.
        """
        return max(
            self.alpha_solid_m2_s,
            self.alpha_mushy_m2_s,
            self.alpha_liquid_effective_m2_s,
        )


@dataclass(frozen=True)
class Geometry:
    """
    Rectangular physical domain dimensions.

    User enters dimensions in mm. Solver uses meters internally.
    """

    Lx_mm: float = 0.624
    Ly_mm: float = 0.624
    Lz_mm: float = 0.336

    @property
    def Lx_m(self) -> float:
        return _mm_to_m(self.Lx_mm)

    @property
    def Ly_m(self) -> float:
        return _mm_to_m(self.Ly_mm)

    @property
    def Lz_m(self) -> float:
        return _mm_to_m(self.Lz_mm)


@dataclass(frozen=True)
class Grid:
    """
    Cell-centered uniform Cartesian grid.

    Cell-centered finite-volume spacing:
        dx = Lx / Nx
        dy = Ly / Ny
        dz = Lz / Nz

    The solver requires dx = dy = dz.
    """

    Nx: int = 39
    Ny: int = 39
    Nz: int = 21

    def dx_m(self, geometry: Geometry) -> float:
        return geometry.Lx_m / self.Nx

    def dy_m(self, geometry: Geometry) -> float:
        return geometry.Ly_m / self.Ny

    def dz_m(self, geometry: Geometry) -> float:
        return geometry.Lz_m / self.Nz

    def uniform_spacing_m(self, geometry: Geometry) -> float:
        dx = self.dx_m(geometry)
        dy = self.dy_m(geometry)
        dz = self.dz_m(geometry)

        if not (
            isclose(dx, dy, rel_tol=1.0e-12, abs_tol=1.0e-15)
            and isclose(dx, dz, rel_tol=1.0e-12, abs_tol=1.0e-15)
        ):
            raise ValueError(
                "Grid spacing is not uniform. The solver requires dx = dy = dz.\n"
                "For the cell-centered finite-volume grid, spacing is:\n"
                "    dx = Lx / Nx\n"
                "    dy = Ly / Ny\n"
                "    dz = Lz / Nz\n\n"
                f"Computed spacing:\n"
                f"  dx = {dx:.6e} m\n"
                f"  dy = {dy:.6e} m\n"
                f"  dz = {dz:.6e} m\n\n"
                "Adjust Lx_mm, Ly_mm, Lz_mm, Nx, Ny, and Nz so that "
                "Lx/Nx = Ly/Ny = Lz/Nz."
            )

        return dx

    def cell_center_coordinates_m(self, geometry: Geometry) -> tuple:
        import numpy as np

        dx = self.uniform_spacing_m(geometry)
        x = (np.arange(self.Nx, dtype=float) + 0.5) * dx
        y = (np.arange(self.Ny, dtype=float) + 0.5) * dx
        z = (np.arange(self.Nz, dtype=float) + 0.5) * dx
        return x, y, z


# Named grid configurations for Patch 9.5 convergence studies. The physical
# domain remains Geometry() = 0.624 x 0.624 x 0.336 mm; only cell counts change.
# Both configurations therefore retain uniform cubic cells exactly.
GRID_CONFIGURATION_16_UM = Grid(Nx=39, Ny=39, Nz=21)
GRID_CONFIGURATION_8_UM = Grid(Nx=78, Ny=78, Nz=42)

GRID_CONFIGURATIONS = MappingProxyType(
    {
        "16um": GRID_CONFIGURATION_16_UM,
        "8um": GRID_CONFIGURATION_8_UM,
    }
)


def get_grid_configuration(name: str) -> Grid:
    """Return a reproducible named grid for the fixed production domain."""

    try:
        return GRID_CONFIGURATIONS[name]
    except KeyError as exc:
        available = ", ".join(sorted(GRID_CONFIGURATIONS))
        raise ValueError(
            f"Unknown grid configuration {name!r}. Available configurations: {available}."
        ) from exc


@dataclass(frozen=True)
class BoundaryConditions:
    """
    Finite-volume boundary-condition configuration.

    Boundary modes are implemented as external face fluxes into or out of
    boundary control volumes. Boundary temperatures are not overwritten. The
    fixed-temperature mode is represented as a half-cell conductive face flux.
    """

    top_surface_mode: Literal[
        "adiabatic",
        "convection",
        "convection_radiation",
        "fixed_temperature",
    ] = "convection"

    side_boundary_mode: Literal[
        "zero_flux",
        "fixed_far_field",
        "solid_absorbing",
    ] = "solid_absorbing"

    bottom_boundary_mode: Literal[
        "zero_flux",
        "fixed_far_field",
        "solid_absorbing",
    ] = "solid_absorbing"

    ambient_temperature_C: float = 25.0
    far_field_temperature_C: float = 25.0

    convection_coefficient_W_m2K: float = 10.0
    emissivity: float = 0.35
    stefan_boltzmann_W_m2K4: float = 5.670374419e-8

    # Patch 16.5.3 reduced-order high-temperature top-surface sink. The default
    # is explicit OFF and therefore preserves the accepted pre-patch boundary
    # behavior. The threshold itself remains MaterialProperties.T_boiling_K.
    boiling_damper_strength: float = 0.0
    boiling_transition_width_K: float = 250.0
    boiling_max_conductance_W_m2K: float = 8.0e6
    # Patch 16.5.5 adds one separately frozen alternate high-superheat law.
    # The default remains the accepted Patch 16.5.3 smoothed-linear tail.
    boiling_loss_law: Literal["smoothstep_linear", "smoothstep_quadratic"] = "smoothstep_linear"
    boiling_reference_superheat_K: float = 1000.0

    # Tunable approximation, not a true semi-infinite solid solution.
    h_solid_W_m2K: float = 1000.0

    @property
    def ambient_temperature_K(self) -> float:
        return _celsius_to_kelvin(self.ambient_temperature_C)

    @property
    def far_field_temperature_K(self) -> float:
        return _celsius_to_kelvin(self.far_field_temperature_C)


@dataclass(frozen=True)
class InitialCondition:
    """Uniform initial temperature."""

    initial_temperature_C: float = 25.0

    @property
    def initial_temperature_K(self) -> float:
        return _celsius_to_kelvin(self.initial_temperature_C)


@dataclass(frozen=True)
class TimeControls:
    """
    Explicit forward-Euler time-integration settings.

    For 3D diffusion on a uniform Cartesian grid:
        dt <= dx^2 / (6 * alpha_max)

    A safety factor is applied to the validation limit:
        dt <= safety_factor * dx^2 / (6 * alpha_max)

    The timestep is not auto-adjusted.
    """

    # Patch 16.0 changes the production DAQ row clock to 5 us. This remains the
    # stability-limited internal FVM substep ceiling; the final substep within
    # each fixed DAQ interval is handled deterministically by the integrator.
    dt_s: float = 10.0e-6 / 3.0
    total_time_s: float = 2.0e-3
    explicit_stability_safety_factor: float = 0.90

    def explicit_stability_limit_s(
        self,
        material: MaterialProperties,
        geometry: Geometry,
        grid: Grid,
    ) -> float:
        dx = grid.uniform_spacing_m(geometry)
        alpha_max = material.maximum_thermal_diffusivity_m2_s
        return dx**2 / (6.0 * alpha_max)

    def explicit_stability_limit_with_safety_s(
        self,
        material: MaterialProperties,
        geometry: Geometry,
        grid: Grid,
    ) -> float:
        return (
            self.explicit_stability_safety_factor
            * self.explicit_stability_limit_s(material, geometry, grid)
        )

    def number_of_steps(self) -> int:
        return int(round(self.total_time_s / self.dt_s))


# Patch 9.5.2: named solver timesteps for the fixed-domain grid study.
# The 16 um case retains the production timestep. The 8 um case uses 1 us,
# which is below the phase-aware 0.90-safety-factor stability limit for the
# current material/source closure and gives ten equal substeps per 100 kHz
# process-row interval. These are explicit study choices, not an automatic
# timestep adjustment inside the solver.
GRID_CONVERGENCE_TIMESTEPS_S = MappingProxyType(
    {
        "16um": 10.0e-6 / 3.0,
        "8um": 1.0e-6,
    }
)


def get_grid_convergence_timestep_s(name: str) -> float:
    """Return the named, stability-validated timestep for a grid study case."""

    try:
        return float(GRID_CONVERGENCE_TIMESTEPS_S[name])
    except KeyError as exc:
        available = ", ".join(sorted(GRID_CONVERGENCE_TIMESTEPS_S))
        raise ValueError(
            f"Unknown grid convergence configuration {name!r}. "
            f"Available configurations: {available}."
        ) from exc


@dataclass(frozen=True)
class OutputControls:
    """HDF5 analytics output and performance settings."""

    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY
    output_h5_filename: str = "temperature_features.h5"
    use_compression: bool = False

    # HDF5 input/output buffering. Larger values reduce Python and filesystem
    # overhead without changing the temporal resolution of the output.
    input_block_rows: int = 1_000_000
    h5_buffer_rows: int = 65_536
    h5_chunk_rows: int = 65_536

    # Rolling liquid-volume variability window. Startup and post-reset values
    # use all available rows until this many records have accumulated.
    melt_pool_variability_window_rows: int = 100

    # Expensive analysis-only full-field features can be sampled deliberately.
    # 1 preserves the historical 100 kHz row cadence. Values >1 compute
    # temperature median/std/skewness/kurtosis and liquid connectivity only on
    # row_index % N == 0; their unsampled HDF5 rows remain present and store NaN.
    expensive_full_field_features_every_n_rows: int = 1

    # Full energy/phase validation is more expensive than the ML statistics.
    # It is evaluated periodically and at moving-window events.
    validation_every_n_rows: int = 1_000
    safety_check_every_n_rows: int = 10_000

    # Use the compiled finite-volume timestep when Numba is available.
    use_numba: bool = True


@dataclass(frozen=True)
class MeltPoolComparisonControls:
    """Experimental/simulated melt-pool H/W comparison settings.

    The production reference method, ``cell_footprint``, applies OpenCV
    ``minAreaRect`` to complete top-surface finite-volume footprints satisfying
    ``T >= T_liquidus``. Patch 9.5.5 adds an optional
    ``interpolated_liquidus_contour`` method that linearly interpolates the
    ``T = T_liquidus`` crossings between neighboring top-surface cell centers
    before applying the same canonical major/minor rectangle convention.
    """

    enabled: bool = True
    layer_name: str = "layer53"
    experimental_pixel_size_um: float = 8.0
    sample_frequency_hz: float = 100_000.0
    hw_geometry_method: Literal[
        "cell_footprint",
        "interpolated_liquidus_contour",
    ] = "cell_footprint"
    output_h5_filename: str = "layer53_simulation_comparison.h5"
    progress_every_rows: int = 5_000


@dataclass(frozen=True)
class SimulationParameters:
    """Top-level parameter bundle."""

    material: MaterialProperties = MaterialProperties()
    geometry: Geometry = Geometry()
    grid: Grid = GRID_CONFIGURATION_16_UM
    boundary_conditions: BoundaryConditions = BoundaryConditions()
    initial_condition: InitialCondition = InitialCondition()
    time: TimeControls = TimeControls()
    output: OutputControls = OutputControls()
    input: InputControls = InputControls()
    heat_source: HeatSourceParameters = HeatSourceParameters()
    moving_window: MovingWindowControls = MovingWindowControls()
    comparison: MeltPoolComparisonControls = MeltPoolComparisonControls()

    def validate(self) -> None:
        self._validate_positive_values()
        self._validate_phase_values()
        self._validate_modes()
        self._validate_grid()
        self._validate_explicit_stability()
        self._validate_output_controls()
        self._validate_input_controls()
        self._validate_moving_window_controls()
        self._validate_comparison_controls()
        self.heat_source.validate(self)

    def _validate_positive_values(self) -> None:
        material = self.material

        if material.density_kg_m3 <= 0.0:
            raise ValueError("density_kg_m3 must be positive.")

        if material.cp_solid_J_kgK <= 0.0:
            raise ValueError("cp_solid_J_kgK must be positive.")

        if material.cp_mushy_J_kgK <= 0.0:
            raise ValueError("cp_mushy_J_kgK must be positive.")

        if material.cp_liquid_J_kgK <= 0.0:
            raise ValueError("cp_liquid_J_kgK must be positive.")

        if material.k_solid_W_mK <= 0.0:
            raise ValueError("k_solid_W_mK must be positive.")

        if material.k_mushy_W_mK <= 0.0:
            raise ValueError("k_mushy_W_mK must be positive.")

        if material.k_liquid_W_mK <= 0.0:
            raise ValueError("k_liquid_W_mK must be positive.")

        if (
            not isfinite(material.liquid_conductivity_enhancement_factor)
            or material.liquid_conductivity_enhancement_factor < 1.0
        ):
            raise ValueError(
                "liquid_conductivity_enhancement_factor must be finite and >= 1.0. "
                "Use 1.0 to disable the reduced-order convection closure."
            )

        if material.latent_heat_fusion_J_kg < 0.0:
            raise ValueError("latent_heat_fusion_J_kg must be nonnegative.")

        if self.geometry.Lx_mm <= 0.0 or self.geometry.Ly_mm <= 0.0 or self.geometry.Lz_mm <= 0.0:
            raise ValueError("All geometry lengths must be positive.")

        if self.grid.Nx < 1 or self.grid.Ny < 1 or self.grid.Nz < 1:
            raise ValueError("Nx, Ny, and Nz must each be at least 1.")

        if self.time.dt_s <= 0.0:
            raise ValueError("dt_s must be positive.")

        if self.time.total_time_s <= 0.0:
            raise ValueError("total_time_s must be positive.")

        if not (0.0 < self.time.explicit_stability_safety_factor <= 1.0):
            raise ValueError("explicit_stability_safety_factor must be in (0, 1].")

        if self.boundary_conditions.convection_coefficient_W_m2K < 0.0:
            raise ValueError("convection_coefficient_W_m2K must be nonnegative.")

        if self.boundary_conditions.h_solid_W_m2K < 0.0:
            raise ValueError("h_solid_W_m2K must be nonnegative.")

        if not (0.0 <= self.boundary_conditions.emissivity <= 1.0):
            raise ValueError("emissivity must be between 0 and 1.")

        if self.boundary_conditions.stefan_boltzmann_W_m2K4 <= 0.0:
            raise ValueError("stefan_boltzmann_W_m2K4 must be positive.")

        boiling_strength = self.boundary_conditions.boiling_damper_strength
        if not isfinite(boiling_strength) or not (0.0 <= boiling_strength <= 1.0):
            raise ValueError("boiling_damper_strength must be finite and within [0, 1].")
        boiling_ramp = self.boundary_conditions.boiling_transition_width_K
        if not isfinite(boiling_ramp) or boiling_ramp <= 0.0:
            raise ValueError("boiling_transition_width_K must be finite and positive.")
        boiling_h = self.boundary_conditions.boiling_max_conductance_W_m2K
        if not isfinite(boiling_h) or boiling_h < 0.0:
            raise ValueError("boiling_max_conductance_W_m2K must be finite and nonnegative.")
        boiling_law = self.boundary_conditions.boiling_loss_law
        if boiling_law not in {"smoothstep_linear", "smoothstep_quadratic"}:
            raise ValueError("Unsupported boiling_loss_law.")
        boiling_ref = self.boundary_conditions.boiling_reference_superheat_K
        if not isfinite(boiling_ref) or boiling_ref <= 0.0:
            raise ValueError("boiling_reference_superheat_K must be finite and positive.")

    def _validate_phase_values(self) -> None:
        material = self.material

        if material.T_liquidus_K <= material.T_solidus_K:
            raise ValueError("T_liquidus_K must be greater than T_solidus_K.")

        if material.T_boiling_K <= material.T_liquidus_K:
            raise ValueError("Diagnostic T_boiling_K should exceed T_liquidus_K.")

        if material.cp_eff_mushy_J_kgK <= 0.0:
            raise ValueError("Mushy apparent heat capacity must be positive.")

        if material.maximum_thermal_diffusivity_m2_s <= 0.0:
            raise ValueError("maximum_thermal_diffusivity_m2_s must be positive.")

    def _validate_modes(self) -> None:
        top_modes = {
            "adiabatic",
            "convection",
            "convection_radiation",
            "fixed_temperature",
        }
        side_bottom_modes = {
            "zero_flux",
            "fixed_far_field",
            "solid_absorbing",
        }

        if self.boundary_conditions.top_surface_mode not in top_modes:
            raise ValueError(
                f"Unsupported top_surface_mode: {self.boundary_conditions.top_surface_mode}"
            )

        if self.boundary_conditions.side_boundary_mode not in side_bottom_modes:
            raise ValueError(
                f"Unsupported side_boundary_mode: {self.boundary_conditions.side_boundary_mode}"
            )

        if self.boundary_conditions.bottom_boundary_mode not in side_bottom_modes:
            raise ValueError(
                f"Unsupported bottom_boundary_mode: {self.boundary_conditions.bottom_boundary_mode}"
            )

    def _validate_grid(self) -> None:
        self.grid.uniform_spacing_m(self.geometry)

    def _validate_explicit_stability(self) -> None:
        dt_limit_raw = self.time.explicit_stability_limit_s(
            material=self.material,
            geometry=self.geometry,
            grid=self.grid,
        )
        dt_limit_safe = self.time.explicit_stability_limit_with_safety_s(
            material=self.material,
            geometry=self.geometry,
            grid=self.grid,
        )

        if self.time.dt_s > dt_limit_safe:
            dx = self.grid.uniform_spacing_m(self.geometry)
            alpha_max = self.material.maximum_thermal_diffusivity_m2_s

            raise ValueError(
                "Unstable explicit time step rejected.\n"
                "For 3D forward-Euler diffusion on a uniform grid with phase-aware material properties:\n"
                "    dt <= dx^2 / (6 * alpha_max)\n"
                "where:\n"
                "    alpha_max = max(k_solid/(rho*cp_solid), "
                "k_mushy/(rho*cp_eff_mushy), k_liquid_eff/(rho*cp_liquid))\n"
                "This code also applies:\n"
                "    dt <= safety_factor * dx^2 / (6 * alpha_max)\n\n"
                f"Computed values:\n"
                f"  dx = dy = dz = {dx:.6e} m\n"
                f"  alpha_solid = {self.material.alpha_solid_m2_s:.6e} m^2/s\n"
                f"  alpha_mushy = {self.material.alpha_mushy_m2_s:.6e} m^2/s\n"
                f"  liquid Ck = {self.material.liquid_conductivity_enhancement_factor:.6g}\n"
                f"  k_liquid physical = {self.material.k_liquid_W_mK:.6e} W/(m*K)\n"
                f"  k_liquid effective = {self.material.k_liquid_effective_W_mK:.6e} W/(m*K)\n"
                f"  alpha_liquid_effective = {self.material.alpha_liquid_effective_m2_s:.6e} m^2/s\n"
                f"  alpha_max = {alpha_max:.6e} m^2/s\n"
                f"  selected dt = {self.time.dt_s:.6e} s\n"
                f"  raw maximum stable dt = {dt_limit_raw:.6e} s\n"
                f"  safety factor = {self.time.explicit_stability_safety_factor:.3f}\n"
                f"  safe maximum dt = {dt_limit_safe:.6e} s\n\n"
                "Reduce dt_s in parameters.py. The solver will not auto-adjust it."
            )

    def _validate_output_controls(self) -> None:
        if not self.output.output_h5_filename.lower().endswith((".h5", ".hdf5")):
            raise ValueError("output_h5_filename must end with .h5 or .hdf5.")

        for name in (
            "input_block_rows",
            "h5_buffer_rows",
            "h5_chunk_rows",
            "melt_pool_variability_window_rows",
            "expensive_full_field_features_every_n_rows",
            "validation_every_n_rows",
            "safety_check_every_n_rows",
        ):
            if int(getattr(self.output, name)) <= 0:
                raise ValueError(f"output.{name} must be a positive integer.")

        n_steps = self.time.number_of_steps()
        if n_steps < 1:
            raise ValueError("total_time_s / dt_s must produce at least one time step.")

    def _validate_input_controls(self) -> None:
        if not str(self.input.h5_path_select) and not self.input.h5_use_file_dialog:
            raise ValueError(
                "input.h5_path_select must not be empty unless "
                "input.h5_use_file_dialog is True."
            )

        if self.input.h5_fallback_fs_hz is not None and self.input.h5_fallback_fs_hz <= 0.0:
            raise ValueError("input.h5_fallback_fs_hz must be positive when supplied.")

        if self.input.default_spot_size_um <= 0.0:
            raise ValueError("input.default_spot_size_um must be positive.")

        if self.input.laser_drive_threshold is not None and not isinstance(
            self.input.laser_drive_threshold, (int, float)
        ):
            raise ValueError("input.laser_drive_threshold must be numeric or None.")

        if self.input.h5_baseline_max_samples <= 0:
            raise ValueError("input.h5_baseline_max_samples must be positive.")

        if (
            not isfinite(self.input.ted_reference_plate_effective_reflectivity)
            or not (0.0 < self.input.ted_reference_plate_effective_reflectivity <= 1.0)
        ):
            raise ValueError(
                "input.ted_reference_plate_effective_reflectivity must satisfy 0 < reflectivity <= 1."
            )

        if self.input.ted_baseline_evidence_policy != "robust_laser_off_segments":
            raise ValueError(
                "Only input.ted_baseline_evidence_policy='robust_laser_off_segments' "
                "is implemented."
            )

        if (
            not isfinite(self.input.ted_off_segment_outlier_sigma_multiplier)
            or self.input.ted_off_segment_outlier_sigma_multiplier <= 0.0
        ):
            raise ValueError(
                "input.ted_off_segment_outlier_sigma_multiplier must be finite and positive."
            )

        if (
            not isfinite(self.input.ted_clip_acceptance_sigma_multiplier)
            or self.input.ted_clip_acceptance_sigma_multiplier <= 0.0
        ):
            raise ValueError(
                "input.ted_clip_acceptance_sigma_multiplier must be finite and positive."
            )

        if self.input.ted_baseline_policy != "global_laser_off_median":
            raise ValueError(
                "Only input.ted_baseline_policy='global_laser_off_median' "
                "is implemented."
            )

    def _validate_moving_window_controls(self) -> None:
        controls = self.moving_window
        if (
            not isfinite(controls.reset_distance_threshold_mm)
            or controls.reset_distance_threshold_mm <= 0.0
        ):
            raise ValueError(
                "moving_window.reset_distance_threshold_mm must be finite and positive."
            )
        if controls.large_jump_policy != "reset_to_bulk":
            raise ValueError(
                "Only moving_window.large_jump_policy='reset_to_bulk' is implemented. "
                "A global thermal-history reinitialization model is not available."
            )

    def _validate_comparison_controls(self) -> None:
        comparison = self.comparison
        if not comparison.layer_name.strip():
            raise ValueError("comparison.layer_name must not be empty.")
        if (
            not isfinite(comparison.experimental_pixel_size_um)
            or comparison.experimental_pixel_size_um <= 0.0
        ):
            raise ValueError("comparison.experimental_pixel_size_um must be finite and positive.")
        if (
            not isfinite(comparison.sample_frequency_hz)
            or comparison.sample_frequency_hz <= 0.0
        ):
            raise ValueError("comparison.sample_frequency_hz must be finite and positive.")
        if comparison.hw_geometry_method not in {
            "cell_footprint",
            "interpolated_liquidus_contour",
        }:
            raise ValueError(
                "comparison.hw_geometry_method must be 'cell_footprint' or "
                "'interpolated_liquidus_contour'."
            )
        if not comparison.output_h5_filename.lower().endswith((".h5", ".hdf5")):
            raise ValueError("comparison.output_h5_filename must end with .h5 or .hdf5.")
        if int(comparison.progress_every_rows) < 0:
            raise ValueError("comparison.progress_every_rows must be >= 0.")

    def summary(self) -> dict:
        data = asdict(self)
        data["output"]["output_directory"] = str(data["output"]["output_directory"])
        data["input"]["h5_path_select"] = str(data["input"]["h5_path_select"])
        dx = self.grid.uniform_spacing_m(self.geometry)

        data["derived"] = {
            "grid_type": "cell_centered_finite_volume",
            "dx_m": dx,
            "dy_m": dx,
            "dz_m": dx,
            "cell_volume_m3": dx**3,
            "face_area_m2": dx**2,
            "T_solidus_K": self.material.T_solidus_K,
            "T_liquidus_K": self.material.T_liquidus_K,
            "T_boiling_K_diagnostic_only": self.material.T_boiling_K,
            "cp_eff_mushy_J_kgK": self.material.cp_eff_mushy_J_kgK,
            "liquid_conductivity_enhancement_factor": (
                self.material.liquid_conductivity_enhancement_factor
            ),
            "k_liquid_physical_W_mK": self.material.k_liquid_W_mK,
            "k_liquid_effective_W_mK": self.material.k_liquid_effective_W_mK,
            "liquid_conductivity_isotropic": True,
            "alpha_solid_m2_s": self.material.alpha_solid_m2_s,
            "alpha_mushy_m2_s": self.material.alpha_mushy_m2_s,
            "alpha_liquid_effective_m2_s": self.material.alpha_liquid_effective_m2_s,
            "alpha_max_m2_s": self.material.maximum_thermal_diffusivity_m2_s,
            "explicit_dt_limit_s": self.time.explicit_stability_limit_s(
                self.material,
                self.geometry,
                self.grid,
            ),
            "explicit_dt_limit_with_safety_s": self.time.explicit_stability_limit_with_safety_s(
                self.material,
                self.geometry,
                self.grid,
            ),
            "number_of_steps": self.time.number_of_steps(),
            "initial_temperature_K": self.initial_condition.initial_temperature_K,
            "ambient_temperature_K": self.boundary_conditions.ambient_temperature_K,
            "far_field_temperature_K": self.boundary_conditions.far_field_temperature_K,
        }

        return data


def get_grid_convergence_parameters(
    name: str,
    *,
    base_params: SimulationParameters | None = None,
) -> SimulationParameters:
    """Build and validate one named Patch 9.5 grid-study parameter set.

    The physical domain, material properties, source parameters, boundary
    conditions, and all other controls are inherited from ``base_params``.
    Only the named grid and its explicitly selected stability-safe timestep
    are replaced. Validation recomputes the phase-aware explicit stability
    limit for the selected grid before the parameter set is returned.
    """

    base = SimulationParameters() if base_params is None else base_params
    grid = get_grid_configuration(name)
    dt_s = get_grid_convergence_timestep_s(name)
    configured = replace(
        base,
        grid=grid,
        time=replace(base.time, dt_s=dt_s),
    )
    configured.validate()
    return configured


# -----------------------------
# Default simulation parameters
# -----------------------------

PARAMS = SimulationParameters()


def get_params() -> SimulationParameters:
    """Main access point for the moving-window workflow."""
    PARAMS.validate()
    return PARAMS


if __name__ == "__main__":
    params = get_params()

    dx = params.grid.uniform_spacing_m(params.geometry)
    dt_raw = params.time.explicit_stability_limit_s(
        params.material,
        params.geometry,
        params.grid,
    )
    dt_safe = params.time.explicit_stability_limit_with_safety_s(
        params.material,
        params.geometry,
        params.grid,
    )

    print("Parameter validation passed.")
    print()
    print("Derived quantities:")
    print("  grid type = cell-centered finite volume")
    print(f"  dx = dy = dz = {dx:.6e} m")
    print(f"  cell volume = {dx**3:.6e} m^3")
    print(f"  T_solidus = {params.material.T_solidus_K:.3f} K")
    print(f"  T_liquidus = {params.material.T_liquidus_K:.3f} K")
    print(f"  T_boiling diagnostic = {params.material.T_boiling_K:.3f} K")
    print(f"  cp_eff_mushy = {params.material.cp_eff_mushy_J_kgK:.6e} J/(kg*K)")
    print(f"  alpha_solid = {params.material.alpha_solid_m2_s:.6e} m^2/s")
    print(f"  alpha_mushy = {params.material.alpha_mushy_m2_s:.6e} m^2/s")
    print(
        "  liquid conductivity closure: "
        f"Ck={params.material.liquid_conductivity_enhancement_factor:.6g}, "
        f"k_physical={params.material.k_liquid_W_mK:.6e} W/(m*K), "
        f"k_effective={params.material.k_liquid_effective_W_mK:.6e} W/(m*K), isotropic"
    )
    print(f"  alpha_liquid_effective = {params.material.alpha_liquid_effective_m2_s:.6e} m^2/s")
    print(f"  alpha_max = {params.material.maximum_thermal_diffusivity_m2_s:.6e} m^2/s")
    print(f"  explicit raw dt limit = {dt_raw:.6e} s")
    print(f"  explicit safe dt limit = {dt_safe:.6e} s")
    print(f"  selected dt = {params.time.dt_s:.6e} s")
    print(f"  total steps = {params.time.number_of_steps()}")
    print(f"  input HDF5 = {params.input.h5_path_select}")
    print(f"  output directory = {params.output.output_directory}")
