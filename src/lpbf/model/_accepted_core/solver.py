"""
Explicit cell-centered finite-volume solver for 3D transient conductive heat
transfer with a volumetric laser/source term and apparent-heat-capacity
solid/mushy/liquid phase-change material properties.

Governing equation:
    rho * cp_eff(T) * dT/dt = div(k(T) grad T) + q_dot

Numerical method:
    - cell-centered finite volume
    - uniform Cartesian grid
    - cubic cells: dx = dy = dz
    - forward Euler time integration
    - vectorized NumPy operations
    - SI units internally
    - temperatures stored/calculated in Kelvin
    - temperature array shape: (Nx, Ny, Nz)

Boundary-condition philosophy:
    Boundary conditions enter as finite-volume face-flux contributions.
    Boundary cell temperatures are not overwritten after the timestep.

Phase-change limitations:
    - Solid and liquid phases only, with a mushy temperature interval.
    - Powder and re-solidified/refused metal are both treated as solid.
    - Constant density.
    - No gas/vapor dynamics, no recoil pressure, no Marangoni flow, no
      keyholing, no mass loss, and no vaporization latent heat.
    - The fixed boiling threshold can optionally activate the accepted Patch 16.5.3
      smoothed-linear or separately frozen Patch 16.5.5 smoothed-quadratic
      reduced-order top-surface energy sink; there is still no mass loss, vapor
      dynamics, recoil pressure, keyholing, Marangoni flow, or hard T cap.
"""

from __future__ import annotations

import numpy as np

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when Numba is absent
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def decorator(function):
            return function
        return decorator

from lpbf.model._accepted_core.parameters import BoundaryConditions, SimulationParameters


# -------------------------------------------------------------------------
# Phase/material fields
# -------------------------------------------------------------------------

def _compute_liquid_fraction(T: np.ndarray, params: SimulationParameters) -> np.ndarray:
    """
    Temperature-derived liquid fraction field.

    Rules:
        f_l = 0 for T <= solidus
        f_l = (T - solidus) / (liquidus - solidus) for solidus < T < liquidus
        f_l = 1 for T >= liquidus
    """
    material = params.material
    liquid_fraction = (
        (np.asarray(T, dtype=float) - material.T_solidus_K)
        / (material.T_liquidus_K - material.T_solidus_K)
    )
    return np.clip(liquid_fraction, 0.0, 1.0)


def _mushy_mask(T: np.ndarray, params: SimulationParameters) -> np.ndarray:
    material = params.material
    return (T > material.T_solidus_K) & (T < material.T_liquidus_K)


def _liquid_mask(T: np.ndarray, params: SimulationParameters) -> np.ndarray:
    return T >= params.material.T_liquidus_K


def _solid_mask(T: np.ndarray, params: SimulationParameters) -> np.ndarray:
    return T <= params.material.T_solidus_K


def _compute_thermal_conductivity_field(
    T: np.ndarray,
    params: SimulationParameters,
) -> np.ndarray:
    """
    Return local solver conductivity k(T), W/(m*K), by phase regime.

    Liquid cells use the isotropic effective conductivity
    ``k_liquid_W_mK * liquid_conductivity_enhancement_factor``. Because one
    scalar cell conductivity is used for all Cartesian face calculations, the
    closure cannot introduce directional (anisotropic) transport.
    """
    material = params.material
    T = np.asarray(T, dtype=float)

    k_cell = np.full_like(T, material.k_solid_W_mK, dtype=float)
    k_cell[_mushy_mask(T, params)] = material.k_mushy_W_mK
    k_cell[_liquid_mask(T, params)] = material.k_liquid_effective_W_mK
    return k_cell


def _harmonic_mean(a: np.ndarray | float, b: np.ndarray | float) -> np.ndarray | float:
    """
    Harmonic mean used for face conductivity.

    For positive conductivities, this gives the correct two-cell thermal
    resistance average across an internal finite-volume face.
    """
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    denominator = a_arr + b_arr

    if np.any(denominator <= 0.0):
        raise ValueError("Harmonic mean requires a + b > 0 everywhere.")

    result = 2.0 * a_arr * b_arr / denominator
    if np.isscalar(a) and np.isscalar(b):
        return float(result)
    return result


# -------------------------------------------------------------------------
# Phase/vapor diagnostics
# -------------------------------------------------------------------------

def compute_phase_diagnostics(
    temperature_K: np.ndarray,
    params: SimulationParameters,
) -> dict:
    """
    Return solid/mushy/liquid cell counts, volumes, and liquid fraction stats.
    """
    dx = params.grid.uniform_spacing_m(params.geometry)
    dV = dx**3

    solid = _solid_mask(temperature_K, params)
    mushy = _mushy_mask(temperature_K, params)
    liquid = _liquid_mask(temperature_K, params)
    liquid_fraction = _compute_liquid_fraction(temperature_K, params)

    num_solid = int(np.count_nonzero(solid))
    num_mushy = int(np.count_nonzero(mushy))
    num_liquid = int(np.count_nonzero(liquid))

    return {
        "num_cells_solid": num_solid,
        "num_cells_mushy": num_mushy,
        "num_cells_liquid": num_liquid,
        "solid_volume_m3": float(num_solid * dV),
        "mushy_volume_m3": float(num_mushy * dV),
        "liquid_volume_m3": float(num_liquid * dV),
        "mean_liquid_fraction": float(np.mean(liquid_fraction)),
        "max_liquid_fraction": float(np.max(liquid_fraction)),
    }



@njit
def _liquid_region_moments(
    temperature_flat: np.ndarray,
    liquidus_temperature_K: float,
    ny: int,
    nz: int,
) -> tuple[int, float, float, float, float, float]:
    """Return liquid index moments without connectivity traversal."""
    total_cells = temperature_flat.size
    yz_stride = ny * nz
    liquid_count = 0
    sum_i = 0.0
    sum_j = 0.0
    sum_i_squared = 0.0
    sum_j_squared = 0.0
    sum_i_j = 0.0

    for cell in range(total_cells):
        if temperature_flat[cell] < liquidus_temperature_K:
            continue
        liquid_count += 1
        i = cell // yz_stride
        remainder = cell - i * yz_stride
        j = remainder // nz
        i_float = float(i)
        j_float = float(j)
        sum_i += i_float
        sum_j += j_float
        sum_i_squared += i_float * i_float
        sum_j_squared += j_float * j_float
        sum_i_j += i_float * j_float

    return (
        liquid_count,
        sum_i,
        sum_j,
        sum_i_squared,
        sum_j_squared,
        sum_i_j,
    )


@njit
def _liquid_region_moments_and_largest_component(
    temperature_flat: np.ndarray,
    liquidus_temperature_K: float,
    nx: int,
    ny: int,
    nz: int,
    visited: np.ndarray,
    stack: np.ndarray,
) -> tuple[int, float, float, float, float, float, int]:
    """Return liquid index moments and largest 6-connected component size."""
    visited.fill(0)
    total_cells = temperature_flat.size
    yz_stride = ny * nz
    liquid_count = 0
    sum_i = 0.0
    sum_j = 0.0
    sum_i_squared = 0.0
    sum_j_squared = 0.0
    sum_i_j = 0.0
    largest_component = 0

    for seed in range(total_cells):
        if temperature_flat[seed] < liquidus_temperature_K or visited[seed] != 0:
            continue

        stack_size = 1
        stack[0] = seed
        visited[seed] = 1
        component_size = 0

        while stack_size > 0:
            stack_size -= 1
            cell = int(stack[stack_size])
            component_size += 1
            liquid_count += 1

            i = cell // yz_stride
            remainder = cell - i * yz_stride
            j = remainder // nz
            k = remainder - j * nz
            i_float = float(i)
            j_float = float(j)
            sum_i += i_float
            sum_j += j_float
            sum_i_squared += i_float * i_float
            sum_j_squared += j_float * j_float
            sum_i_j += i_float * j_float

            if i > 0:
                neighbor = cell - yz_stride
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1
            if i + 1 < nx:
                neighbor = cell + yz_stride
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1
            if j > 0:
                neighbor = cell - nz
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1
            if j + 1 < ny:
                neighbor = cell + nz
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1
            if k > 0:
                neighbor = cell - 1
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1
            if k + 1 < nz:
                neighbor = cell + 1
                if (
                    temperature_flat[neighbor] >= liquidus_temperature_K
                    and visited[neighbor] == 0
                ):
                    visited[neighbor] = 1
                    stack[stack_size] = neighbor
                    stack_size += 1

        if component_size > largest_component:
            largest_component = component_size

    return (
        liquid_count,
        sum_i,
        sum_j,
        sum_i_squared,
        sum_j_squared,
        sum_i_j,
        largest_component,
    )


class MeltPoolFeatureWorkspace:
    """Reusable scratch storage for full-rate melt-pool feature extraction."""

    def __init__(self, shape: tuple[int, int, int]) -> None:
        if len(shape) != 3 or any(int(length) <= 0 for length in shape):
            raise ValueError("shape must contain three positive dimensions.")
        self.shape = tuple(int(length) for length in shape)
        total_cells = int(np.prod(self.shape))
        self.visited = np.zeros(total_cells, dtype=np.uint8)
        self.stack = np.empty(total_cells, dtype=np.int64)


def compute_melt_pool_features(
    temperature_K: np.ndarray,
    params: SimulationParameters,
    laser_center_x_m: float | None = None,
    laser_center_y_m: float | None = None,
    workspace: MeltPoolFeatureWorkspace | None = None,
    *,
    compute_connectivity: bool = True,
) -> dict:
    """Compute full-field liquid-region geometry and connectivity features.

    The liquid mask is ``T >= T_liquidus``. Centroid offsets use the fixed local
    Cartesian grid: positive x/y means the liquid centroid is at larger local
    x/y than the current heat-source center. Offsets are invalid during
    laser-off rows, represented by a missing center, and when no liquid cells
    exist. Invalid scalar values use the finite sentinel 0.0 and are paired with
    explicit validity flags. When ``compute_connectivity`` is false, the
    geometry still uses the complete liquid mask but the analysis-only largest
    connected-component fraction is returned as NaN so unsampled rows cannot
    be mistaken for a physical zero.
    """
    T_array = np.asarray(temperature_K, dtype=np.float64)
    if T_array.ndim != 3:
        raise ValueError(
            "temperature_K must be a three-dimensional temperature field."
        )
    T_array = np.ascontiguousarray(T_array)

    if workspace is None:
        workspace = MeltPoolFeatureWorkspace(T_array.shape)
    elif workspace.shape != T_array.shape:
        raise ValueError("workspace shape must match the temperature field shape.")

    dx = params.grid.uniform_spacing_m(params.geometry)
    cell_volume_m3 = dx**3
    temperature_flat = T_array.reshape(-1)
    liquidus_temperature_K = float(params.material.T_liquidus_K)
    if compute_connectivity:
        (
            liquid_count,
            sum_i,
            sum_j,
            sum_i_squared,
            sum_j_squared,
            sum_i_j,
            largest_component_count,
        ) = _liquid_region_moments_and_largest_component(
            temperature_flat,
            liquidus_temperature_K,
            T_array.shape[0],
            T_array.shape[1],
            T_array.shape[2],
            workspace.visited,
            workspace.stack,
        )
    else:
        (
            liquid_count,
            sum_i,
            sum_j,
            sum_i_squared,
            sum_j_squared,
            sum_i_j,
        ) = _liquid_region_moments(
            temperature_flat,
            liquidus_temperature_K,
            T_array.shape[1],
            T_array.shape[2],
        )
        largest_component_count = 0
    liquid_count = int(liquid_count)

    result = {
        "liquid_volume_m3": float(liquid_count * cell_volume_m3),
        "melt_pool_aspect_ratio": 0.0,
        "melt_pool_centroid_offset_x_m": 0.0,
        "melt_pool_centroid_offset_y_m": 0.0,
        "liquid_largest_component_fraction": (0.0 if compute_connectivity else float("nan")),
        "melt_pool_aspect_ratio_valid_flag": False,
        "melt_pool_centroid_valid_flag": False,
    }
    if liquid_count == 0:
        return result

    inverse_count = 1.0 / liquid_count
    mean_i = sum_i * inverse_count
    mean_j = sum_j * inverse_count
    centroid_x_m = float((mean_i + 0.5) * dx)
    centroid_y_m = float((mean_j + 0.5) * dx)

    center_is_valid = (
        laser_center_x_m is not None
        and laser_center_y_m is not None
        and np.isfinite(laser_center_x_m)
        and np.isfinite(laser_center_y_m)
    )
    if center_is_valid:
        result["melt_pool_centroid_offset_x_m"] = float(
            centroid_x_m - float(laser_center_x_m)
        )
        result["melt_pool_centroid_offset_y_m"] = float(
            centroid_y_m - float(laser_center_y_m)
        )
        result["melt_pool_centroid_valid_flag"] = True

    if liquid_count >= 2:
        covariance_xx = max(sum_i_squared * inverse_count - mean_i * mean_i, 0.0) * dx**2
        covariance_xy = (sum_i_j * inverse_count - mean_i * mean_j) * dx**2
        covariance_yy = max(sum_j_squared * inverse_count - mean_j * mean_j, 0.0) * dx**2

        discriminant = max(
            (covariance_xx - covariance_yy) ** 2 + 4.0 * covariance_xy**2,
            0.0,
        )
        root = float(np.sqrt(discriminant))
        eigenvalue_major = 0.5 * (covariance_xx + covariance_yy + root)
        eigenvalue_minor = 0.5 * (covariance_xx + covariance_yy - root)

        # Cell-center covariance alone has a zero minor dimension for a
        # one-cell-wide line. Add the exact in-cell variance of a uniform cubic
        # control volume so the principal dimensions remain finite and physical.
        cell_internal_variance_m2 = dx**2 / 12.0
        major_variance_m2 = max(eigenvalue_major + cell_internal_variance_m2, 0.0)
        minor_variance_m2 = max(eigenvalue_minor + cell_internal_variance_m2, 0.0)
        if minor_variance_m2 > 0.0:
            aspect_ratio = float(np.sqrt(major_variance_m2 / minor_variance_m2))
            if np.isfinite(aspect_ratio):
                result["melt_pool_aspect_ratio"] = max(1.0, aspect_ratio)
                result["melt_pool_aspect_ratio_valid_flag"] = True

    if compute_connectivity:
        result["liquid_largest_component_fraction"] = float(
            int(largest_component_count) / liquid_count
        )
    return result




def compute_vaporization_diagnostics(
    temperature_K: np.ndarray,
    params: SimulationParameters,
) -> dict:
    """
    Diagnostic-only count/volume of cells at or above the boiling threshold.

    This function does not cap temperature, remove mass, add vaporization
    latent heat, or introduce a gas phase.
    """
    dx = params.grid.uniform_spacing_m(params.geometry)
    dV = dx**3
    boiling_mask = temperature_K >= params.material.T_boiling_K
    top_layer_mask = boiling_mask[:, :, -1]

    num_all = int(np.count_nonzero(boiling_mask))
    num_top = int(np.count_nonzero(top_layer_mask))

    return {
        "num_cells_above_boiling_all": num_all,
        "num_cells_above_boiling_top_layer": num_top,
        "volume_above_boiling_all_m3": float(num_all * dV),
        "volume_above_boiling_top_layer_m3": float(num_top * dV),
    }


# -------------------------------------------------------------------------
# Enthalpy/stored energy diagnostics
# -------------------------------------------------------------------------

def _compute_specific_enthalpy_J_kg(
    temperature_K: np.ndarray | float,
    params: SimulationParameters,
) -> np.ndarray | float:
    """
    Piecewise specific enthalpy h(T), J/kg, referenced to h(0 K) = 0.

    This is used for diagnostics and energy accounting. It is consistent with
    the same apparent heat capacity regimes used by the explicit update.
    """
    material = params.material
    T_arr = np.asarray(temperature_K, dtype=float)

    Ts = material.T_solidus_K
    Tl = material.T_liquidus_K
    cp_s = material.cp_solid_J_kgK
    cp_m_eff = material.cp_eff_mushy_J_kgK
    cp_l = material.cp_liquid_J_kgK

    h_solidus = cp_s * Ts
    h_liquidus = h_solidus + cp_m_eff * (Tl - Ts)

    h = np.empty_like(T_arr, dtype=float)

    solid = T_arr <= Ts
    mushy = (T_arr > Ts) & (T_arr < Tl)
    liquid = T_arr >= Tl

    h[solid] = cp_s * T_arr[solid]
    h[mushy] = h_solidus + cp_m_eff * (T_arr[mushy] - Ts)
    h[liquid] = h_liquidus + cp_l * (T_arr[liquid] - Tl)

    if np.isscalar(temperature_K):
        return float(h)
    return h


def _compute_temperature_from_specific_enthalpy_J_kg(
    specific_enthalpy_J_kg: np.ndarray | float,
    params: SimulationParameters,
) -> np.ndarray | float:
    """
    Invert the piecewise enthalpy relation h(T) used for diagnostics.

    This is used by the heat-source update so that deposited source energy
    maps through the same apparent-latent-heat enthalpy curve used in energy
    accounting. That avoids skipping over the mushy interval when a source
    step is large compared with the 25 K solidus-liquidus interval.
    """
    material = params.material
    h_arr = np.asarray(specific_enthalpy_J_kg, dtype=float)

    Ts = material.T_solidus_K
    Tl = material.T_liquidus_K
    cp_s = material.cp_solid_J_kgK
    cp_m_eff = material.cp_eff_mushy_J_kgK
    cp_l = material.cp_liquid_J_kgK

    h_solidus = cp_s * Ts
    h_liquidus = h_solidus + cp_m_eff * (Tl - Ts)

    T = np.empty_like(h_arr, dtype=float)

    solid = h_arr <= h_solidus
    mushy = (h_arr > h_solidus) & (h_arr < h_liquidus)
    liquid = h_arr >= h_liquidus

    T[solid] = h_arr[solid] / cp_s
    T[mushy] = Ts + (h_arr[mushy] - h_solidus) / cp_m_eff
    T[liquid] = Tl + (h_arr[liquid] - h_liquidus) / cp_l

    if np.isscalar(specific_enthalpy_J_kg):
        return float(T)
    return T


def compute_stored_energy_relative_to_temperature_J(
    temperature_K: np.ndarray,
    reference_temperature_K: float,
    params: SimulationParameters,
) -> float:
    """
    Total material enthalpy relative to a uniform reference temperature.
    """
    rho = params.material.density_kg_m3
    dx = params.grid.uniform_spacing_m(params.geometry)
    dV = dx**3

    h = _compute_specific_enthalpy_J_kg(temperature_K, params)
    h_ref = _compute_specific_enthalpy_J_kg(float(reference_temperature_K), params)
    return float(np.sum(rho * (h - h_ref) * dV))


# -------------------------------------------------------------------------
# Conductive finite-volume update
# -------------------------------------------------------------------------

def _compute_phase_aware_conduction_energy_density_update(
    temperature_K: np.ndarray,
    params: SimulationParameters,
) -> np.ndarray:
    """
    Compute internal conductive energy-density change, J/m^3, for one step.

    For each internal face between cells P and N:
        delta_u_P =  dt * k_face * (T_N - T_P) / dx^2
        delta_u_N = -dt * k_face * (T_N - T_P) / dx^2

    Conductivity at faces uses harmonic averaging. The face exchange is
    exactly equal-and-opposite in energy-density form, so internal conduction
    remains conservative before the final enthalpy inversion.
    """
    dt = params.time.dt_s
    dx = params.grid.uniform_spacing_m(params.geometry)

    k_cell = _compute_thermal_conductivity_field(temperature_K, params)
    delta_u = np.zeros_like(temperature_K, dtype=float)

    # x-direction internal faces
    k_face_x = _harmonic_mean(k_cell[:-1, :, :], k_cell[1:, :, :])
    energy_density_x = (
        dt
        * k_face_x
        * (temperature_K[1:, :, :] - temperature_K[:-1, :, :])
        / dx**2
    )
    delta_u[:-1, :, :] += energy_density_x
    delta_u[1:, :, :] -= energy_density_x

    # y-direction internal faces
    k_face_y = _harmonic_mean(k_cell[:, :-1, :], k_cell[:, 1:, :])
    energy_density_y = (
        dt
        * k_face_y
        * (temperature_K[:, 1:, :] - temperature_K[:, :-1, :])
        / dx**2
    )
    delta_u[:, :-1, :] += energy_density_y
    delta_u[:, 1:, :] -= energy_density_y

    # z-direction internal faces
    k_face_z = _harmonic_mean(k_cell[:, :, :-1], k_cell[:, :, 1:])
    energy_density_z = (
        dt
        * k_face_z
        * (temperature_K[:, :, 1:] - temperature_K[:, :, :-1])
        / dx**2
    )
    delta_u[:, :, :-1] += energy_density_z
    delta_u[:, :, 1:] -= energy_density_z

    return delta_u



# -------------------------------------------------------------------------
# Boundary heat-loss model
# -------------------------------------------------------------------------

def _compute_top_heat_loss_flux_W_m2(
    T: np.ndarray,
    params: SimulationParameters,
) -> np.ndarray:
    """
    Compute top-surface heat-loss flux q''_loss in W/m^2.

    Positive q''_loss means heat leaves the computational domain through the
    top face. For fixed-temperature mode, local top-cell conductivity is used
    through a half-cell face distance.
    """
    bc: BoundaryConditions = params.boundary_conditions
    dx = params.grid.uniform_spacing_m(params.geometry)
    T_s = T[:, :, -1]

    if bc.top_surface_mode == "adiabatic":
        return np.zeros_like(T_s)

    if bc.top_surface_mode == "convection":
        h = bc.convection_coefficient_W_m2K
        T_inf = bc.ambient_temperature_K
        return h * (T_s - T_inf)

    if bc.top_surface_mode == "convection_radiation":
        h = bc.convection_coefficient_W_m2K
        eps = bc.emissivity
        sigma = bc.stefan_boltzmann_W_m2K4
        T_inf = bc.ambient_temperature_K
        T_rad = np.maximum(T_s, 0.0)
        q_conv = h * (T_s - T_inf)
        q_rad = eps * sigma * (T_rad**4 - T_inf**4)
        return q_conv + q_rad

    if bc.top_surface_mode == "fixed_temperature":
        T_fixed = bc.ambient_temperature_K
        k_top = _compute_thermal_conductivity_field(T, params)[:, :, -1]
        return k_top * (T_s - T_fixed) / (0.5 * dx)

    raise ValueError(f"Unsupported top_surface_mode: {bc.top_surface_mode}")


def _compute_boiling_loss_flux_W_m2(
    T_surface_K: np.ndarray,
    params: SimulationParameters,
) -> np.ndarray:
    """Return the selected reduced-order top-surface boiling-loss flux in W/m^2.

    Patch 16.5.3 freezes the smoothed-linear branch. Patch 16.5.5 adds one
    separately frozen smoothed-quadratic branch while retaining the linear law.

    Positive values remove energy. Strength zero uses an explicit OFF branch and
    does not evaluate the smoothstep law, preserving the accepted top-boundary
    arithmetic as strongly as possible.
    """
    bc = params.boundary_conditions
    T_surface = np.asarray(T_surface_K, dtype=float)
    if bc.boiling_damper_strength == 0.0:
        return np.zeros_like(T_surface)

    delta_T = np.maximum(T_surface - params.material.T_boiling_K, 0.0)
    x = delta_T / bc.boiling_transition_width_K
    # Evaluate the quintic only inside its frozen transition interval. Using a
    # masked piecewise evaluation avoids needless high-power arithmetic for
    # already-saturated superheat while preserving the exact law.
    smoothstep = np.zeros_like(x)
    ramp_mask = (x > 0.0) & (x < 1.0)
    xr = x[ramp_mask]
    smoothstep[ramp_mask] = 10.0 * xr**3 - 15.0 * xr**4 + 6.0 * xr**5
    smoothstep[x >= 1.0] = 1.0
    if bc.boiling_loss_law == "smoothstep_linear":
        # Accepted Patch 16.5.3 law. Keep this arithmetic branch intact so
        # the earlier implementation remains reproducible.
        q_boil = (
            bc.boiling_damper_strength
            * bc.boiling_max_conductance_W_m2K
            * delta_T
            * smoothstep
        )
    elif bc.boiling_loss_law == "smoothstep_quadratic":
        # Patch 16.5.5 alternate law: same threshold/ramp and reference
        # conductance, with a dimensionless DeltaT/DeltaT_ref factor.
        q_boil = (
            bc.boiling_damper_strength
            * bc.boiling_max_conductance_W_m2K
            * delta_T
            * (delta_T / bc.boiling_reference_superheat_K)
            * smoothstep
        )
    else:
        raise ValueError(f"Unsupported boiling_loss_law: {bc.boiling_loss_law}")
    if not np.all(np.isfinite(q_boil)):
        raise FloatingPointError("Patch 16.5.3 boiling flux became nonfinite.")
    if np.any(q_boil < 0.0):
        raise FloatingPointError("Patch 16.5.3 boiling flux attempted to add energy.")
    return q_boil


# -------------------------------------------------------------------------
# Boundary face fluxes in energy-density form
# -------------------------------------------------------------------------

def _add_fixed_far_field_energy_density_to_face(
    T_face: np.ndarray,
    delta_u_face: np.ndarray,
    k_face: np.ndarray,
    params: SimulationParameters,
) -> None:
    """Add fixed far-field boundary energy-density change to one face."""
    dt = params.time.dt_s
    dx = params.grid.uniform_spacing_m(params.geometry)
    T_far = params.boundary_conditions.far_field_temperature_K

    q_into_domain = k_face * (T_far - T_face) / (0.5 * dx)
    delta_u_face += dt * q_into_domain / dx


def _add_solid_absorbing_energy_density_to_face(
    T_face: np.ndarray,
    delta_u_face: np.ndarray,
    params: SimulationParameters,
) -> None:
    """Add approximate solid absorbing boundary energy-density change."""
    dt = params.time.dt_s
    dx = params.grid.uniform_spacing_m(params.geometry)
    bc = params.boundary_conditions

    q_into_domain = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T_face)
    delta_u_face += dt * q_into_domain / dx


def _apply_side_boundary_energy_density_fluxes(
    T: np.ndarray,
    delta_u: np.ndarray,
    params: SimulationParameters,
) -> tuple[np.ndarray, float]:
    """Apply x/y artificial-boundary fluxes and return signed loss power.

    ``side_loss_power_W`` is positive when net heat leaves the computational
    domain and negative when the far field supplies heat to the domain.
    Corner cells contribute once for each physical boundary face they touch.
    """
    mode = params.boundary_conditions.side_boundary_mode
    dx = params.grid.uniform_spacing_m(params.geometry)
    area = dx**2

    if mode == "zero_flux":
        return delta_u, 0.0

    k_cell = _compute_thermal_conductivity_field(T, params)
    side_loss_power_W = 0.0

    if mode == "fixed_far_field":
        T_far = params.boundary_conditions.far_field_temperature_K
        q_into_x0 = k_cell[0, :, :] * (T_far - T[0, :, :]) / (0.5 * dx)
        q_into_x1 = k_cell[-1, :, :] * (T_far - T[-1, :, :]) / (0.5 * dx)
        q_into_y0 = k_cell[:, 0, :] * (T_far - T[:, 0, :]) / (0.5 * dx)
        q_into_y1 = k_cell[:, -1, :] * (T_far - T[:, -1, :]) / (0.5 * dx)
        side_loss_power_W = float(
            -area
            * (
                np.sum(q_into_x0, dtype=np.float64)
                + np.sum(q_into_x1, dtype=np.float64)
                + np.sum(q_into_y0, dtype=np.float64)
                + np.sum(q_into_y1, dtype=np.float64)
            )
        )
        _add_fixed_far_field_energy_density_to_face(T[0, :, :], delta_u[0, :, :], k_cell[0, :, :], params)
        _add_fixed_far_field_energy_density_to_face(T[-1, :, :], delta_u[-1, :, :], k_cell[-1, :, :], params)
        _add_fixed_far_field_energy_density_to_face(T[:, 0, :], delta_u[:, 0, :], k_cell[:, 0, :], params)
        _add_fixed_far_field_energy_density_to_face(T[:, -1, :], delta_u[:, -1, :], k_cell[:, -1, :], params)
        return delta_u, side_loss_power_W

    if mode == "solid_absorbing":
        bc = params.boundary_conditions
        q_into_x0 = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T[0, :, :])
        q_into_x1 = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T[-1, :, :])
        q_into_y0 = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T[:, 0, :])
        q_into_y1 = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T[:, -1, :])
        side_loss_power_W = float(
            -area
            * (
                np.sum(q_into_x0, dtype=np.float64)
                + np.sum(q_into_x1, dtype=np.float64)
                + np.sum(q_into_y0, dtype=np.float64)
                + np.sum(q_into_y1, dtype=np.float64)
            )
        )
        _add_solid_absorbing_energy_density_to_face(T[0, :, :], delta_u[0, :, :], params)
        _add_solid_absorbing_energy_density_to_face(T[-1, :, :], delta_u[-1, :, :], params)
        _add_solid_absorbing_energy_density_to_face(T[:, 0, :], delta_u[:, 0, :], params)
        _add_solid_absorbing_energy_density_to_face(T[:, -1, :], delta_u[:, -1, :], params)
        return delta_u, side_loss_power_W

    raise ValueError(f"Unsupported side_boundary_mode: {mode}")


def _apply_bottom_boundary_energy_density_flux(
    T: np.ndarray,
    delta_u: np.ndarray,
    params: SimulationParameters,
) -> tuple[np.ndarray, float]:
    """Apply the bottom artificial-boundary flux and return signed loss power."""
    mode = params.boundary_conditions.bottom_boundary_mode
    dx = params.grid.uniform_spacing_m(params.geometry)
    area = dx**2

    if mode == "zero_flux":
        return delta_u, 0.0

    k_cell = _compute_thermal_conductivity_field(T, params)

    if mode == "fixed_far_field":
        T_far = params.boundary_conditions.far_field_temperature_K
        q_into = k_cell[:, :, 0] * (T_far - T[:, :, 0]) / (0.5 * dx)
        bottom_loss_power_W = float(-np.sum(q_into, dtype=np.float64) * area)
        _add_fixed_far_field_energy_density_to_face(T[:, :, 0], delta_u[:, :, 0], k_cell[:, :, 0], params)
        return delta_u, bottom_loss_power_W

    if mode == "solid_absorbing":
        bc = params.boundary_conditions
        q_into = bc.h_solid_W_m2K * (bc.far_field_temperature_K - T[:, :, 0])
        bottom_loss_power_W = float(-np.sum(q_into, dtype=np.float64) * area)
        _add_solid_absorbing_energy_density_to_face(T[:, :, 0], delta_u[:, :, 0], params)
        return delta_u, bottom_loss_power_W

    raise ValueError(f"Unsupported bottom_boundary_mode: {mode}")


def _apply_top_boundary_energy_density_flux(
    T: np.ndarray,
    delta_u: np.ndarray,
    params: SimulationParameters,
) -> tuple[np.ndarray, dict[str, float]]:
    """Apply top-surface losses and expose existing/boiling components."""
    dt = params.time.dt_s
    dx = params.grid.uniform_spacing_m(params.geometry)
    area = dx**2
    bc = params.boundary_conditions
    T_surface = T[:, :, -1]

    # Preserve the accepted pre-Patch-16.5.3 existing boundary calculation.
    q_existing = _compute_top_heat_loss_flux_W_m2(T, params)
    existing_top_loss_power_W = float(np.sum(q_existing, dtype=np.float64) * area)

    convection_loss_power_W = 0.0
    radiation_loss_power_W = 0.0
    if bc.top_surface_mode == "convection":
        convection_loss_power_W = existing_top_loss_power_W
    elif bc.top_surface_mode == "convection_radiation":
        q_conv = bc.convection_coefficient_W_m2K * (T_surface - bc.ambient_temperature_K)
        T_rad = np.maximum(T_surface, 0.0)
        q_rad = bc.emissivity * bc.stefan_boltzmann_W_m2K4 * (
            T_rad**4 - bc.ambient_temperature_K**4
        )
        convection_loss_power_W = float(np.sum(q_conv, dtype=np.float64) * area)
        radiation_loss_power_W = float(np.sum(q_rad, dtype=np.float64) * area)

    # Explicit OFF path: do not evaluate the boiling law when strength == 0.
    if bc.boiling_damper_strength == 0.0:
        q_total = q_existing
        boiling_loss_power_W = 0.0
    else:
        q_boil = _compute_boiling_loss_flux_W_m2(T_surface, params)
        boiling_loss_power_W = float(np.sum(q_boil, dtype=np.float64) * area)
        if not np.isfinite(boiling_loss_power_W) or boiling_loss_power_W < 0.0:
            raise FloatingPointError("Patch 16.5.3 boiling power must be finite and nonnegative.")
        q_total = q_existing + q_boil

    delta_u[:, :, -1] += -dt * q_total / dx
    top_loss_power_W = existing_top_loss_power_W + boiling_loss_power_W
    return delta_u, {
        "top_loss_power_W": float(top_loss_power_W),
        "existing_top_loss_power_W": float(existing_top_loss_power_W),
        "convection_loss_power_W": float(convection_loss_power_W),
        "radiation_loss_power_W": float(radiation_loss_power_W),
        "boiling_loss_power_W": float(boiling_loss_power_W),
    }


def _apply_boundary_energy_density_fluxes(
    T: np.ndarray,
    delta_u: np.ndarray,
    params: SimulationParameters,
) -> tuple[np.ndarray, dict[str, float]]:
    """Apply all external boundary fluxes and report signed loss powers."""
    delta_u, side_loss_power_W = _apply_side_boundary_energy_density_fluxes(
        T, delta_u, params
    )
    delta_u, bottom_loss_power_W = _apply_bottom_boundary_energy_density_flux(
        T, delta_u, params
    )
    delta_u, top = _apply_top_boundary_energy_density_flux(T, delta_u, params)
    boundary = dict(top)
    boundary["side_loss_power_W"] = float(side_loss_power_W)
    boundary["bottom_loss_power_W"] = float(bottom_loss_power_W)
    boundary["total_boundary_loss_power_W"] = float(
        boundary["top_loss_power_W"] + side_loss_power_W + bottom_loss_power_W
    )
    return delta_u, boundary


def _apply_enthalpy_energy_density_update(
    T: np.ndarray,
    delta_u_J_m3: np.ndarray,
    params: SimulationParameters,
) -> np.ndarray:
    """Apply a volumetric energy-density increment through h(T) inversion."""
    rho = params.material.density_kg_m3
    h_old = _compute_specific_enthalpy_J_kg(T, params)
    h_new = h_old + delta_u_J_m3 / rho
    return _compute_temperature_from_specific_enthalpy_J_kg(h_new, params)



# -------------------------------------------------------------------------
# Numba-compiled explicit FVM timestep
# -------------------------------------------------------------------------

@njit(cache=True)
def _conductivity_scalar(
    temperature_K: float,
    solidus_K: float,
    liquidus_K: float,
    k_solid: float,
    k_mushy: float,
    k_liquid_effective: float,
) -> float:
    if temperature_K <= solidus_K:
        return k_solid
    if temperature_K < liquidus_K:
        return k_mushy
    return k_liquid_effective


@njit(cache=True)
def _specific_enthalpy_scalar(
    temperature_K: float,
    solidus_K: float,
    liquidus_K: float,
    cp_solid: float,
    cp_mushy_effective: float,
    cp_liquid: float,
) -> float:
    h_solidus = cp_solid * solidus_K
    h_liquidus = h_solidus + cp_mushy_effective * (liquidus_K - solidus_K)
    if temperature_K <= solidus_K:
        return cp_solid * temperature_K
    if temperature_K < liquidus_K:
        return h_solidus + cp_mushy_effective * (temperature_K - solidus_K)
    return h_liquidus + cp_liquid * (temperature_K - liquidus_K)


@njit(cache=True)
def _temperature_from_enthalpy_scalar(
    enthalpy_J_kg: float,
    solidus_K: float,
    liquidus_K: float,
    cp_solid: float,
    cp_mushy_effective: float,
    cp_liquid: float,
) -> float:
    h_solidus = cp_solid * solidus_K
    h_liquidus = h_solidus + cp_mushy_effective * (liquidus_K - solidus_K)
    if enthalpy_J_kg <= h_solidus:
        return enthalpy_J_kg / cp_solid
    if enthalpy_J_kg < h_liquidus:
        return solidus_K + (enthalpy_J_kg - h_solidus) / cp_mushy_effective
    return liquidus_K + (enthalpy_J_kg - h_liquidus) / cp_liquid


@njit(cache=True)
def _explicit_fvm_step_numba_kernel(
    T: np.ndarray,
    q_dot: np.ndarray,
    T_out: np.ndarray,
    dt: float,
    dx: float,
    rho: float,
    solidus_K: float,
    liquidus_K: float,
    cp_solid: float,
    cp_mushy_effective: float,
    cp_liquid: float,
    k_solid: float,
    k_mushy: float,
    k_liquid_effective: float,
    top_mode: int,
    side_mode: int,
    bottom_mode: int,
    ambient_K: float,
    far_field_K: float,
    convection_h: float,
    emissivity: float,
    stefan_boltzmann: float,
    solid_h: float,
    boiling_strength: float,
    boiling_temperature_K: float,
    boiling_transition_width_K: float,
    boiling_max_conductance_W_m2K: float,
    boiling_law_code: int,
    boiling_reference_superheat_K: float,
) -> tuple[float, float, float, float, float, float, float]:
    nx, ny, nz = T.shape
    inverse_dx_squared = 1.0 / (dx * dx)
    area = dx * dx
    top_loss_power_W = 0.0
    existing_top_loss_power_W = 0.0
    convection_loss_power_W = 0.0
    radiation_loss_power_W = 0.0
    boiling_loss_power_W = 0.0
    side_loss_power_W = 0.0
    bottom_loss_power_W = 0.0

    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                temperature = T[i, j, k]
                k_cell = _conductivity_scalar(
                    temperature, solidus_K, liquidus_K,
                    k_solid, k_mushy, k_liquid_effective,
                )
                delta_u = dt * q_dot[i, j, k]

                if i > 0:
                    neighbor_temperature = T[i - 1, j, k]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared
                if i + 1 < nx:
                    neighbor_temperature = T[i + 1, j, k]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared
                if j > 0:
                    neighbor_temperature = T[i, j - 1, k]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared
                if j + 1 < ny:
                    neighbor_temperature = T[i, j + 1, k]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared
                if k > 0:
                    neighbor_temperature = T[i, j, k - 1]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared
                if k + 1 < nz:
                    neighbor_temperature = T[i, j, k + 1]
                    k_neighbor = _conductivity_scalar(
                        neighbor_temperature, solidus_K, liquidus_K,
                        k_solid, k_mushy, k_liquid_effective,
                    )
                    k_face = 2.0 * k_cell * k_neighbor / (k_cell + k_neighbor)
                    delta_u += dt * k_face * (neighbor_temperature - temperature) * inverse_dx_squared

                # x/y side boundaries. 0=zero flux, 1=fixed far field,
                # 2=solid absorbing.
                number_of_side_faces = 0
                if i == 0:
                    number_of_side_faces += 1
                if i == nx - 1:
                    number_of_side_faces += 1
                if j == 0:
                    number_of_side_faces += 1
                if j == ny - 1:
                    number_of_side_faces += 1
                if number_of_side_faces > 0:
                    if side_mode == 1:
                        q_into = k_cell * (far_field_K - temperature) / (0.5 * dx)
                        delta_u += number_of_side_faces * dt * q_into / dx
                        side_loss_power_W -= number_of_side_faces * q_into * area
                    elif side_mode == 2:
                        q_into = solid_h * (far_field_K - temperature)
                        delta_u += number_of_side_faces * dt * q_into / dx
                        side_loss_power_W -= number_of_side_faces * q_into * area

                # Bottom boundary.
                if k == 0:
                    if bottom_mode == 1:
                        q_into = k_cell * (far_field_K - temperature) / (0.5 * dx)
                        delta_u += dt * q_into / dx
                        bottom_loss_power_W -= q_into * area
                    elif bottom_mode == 2:
                        q_into = solid_h * (far_field_K - temperature)
                        delta_u += dt * q_into / dx
                        bottom_loss_power_W -= q_into * area

                # Top boundary. Positive q_loss leaves the domain.
                if k == nz - 1:
                    q_existing = 0.0
                    q_convection = 0.0
                    q_radiation = 0.0
                    if top_mode == 1:
                        q_convection = convection_h * (temperature - ambient_K)
                        q_existing = q_convection
                    elif top_mode == 2:
                        radiation_temperature = temperature if temperature > 0.0 else 0.0
                        q_convection = convection_h * (temperature - ambient_K)
                        q_radiation = (
                            emissivity * stefan_boltzmann
                            * (radiation_temperature**4 - ambient_K**4)
                        )
                        q_existing = q_convection + q_radiation
                    elif top_mode == 3:
                        q_existing = k_cell * (temperature - ambient_K) / (0.5 * dx)

                    # Explicit OFF path: no boiling arithmetic at strength zero.
                    q_boil = 0.0
                    if boiling_strength > 0.0 and temperature > boiling_temperature_K:
                        delta_T_boil = temperature - boiling_temperature_K
                        x_boil = delta_T_boil / boiling_transition_width_K
                        if x_boil >= 1.0:
                            smoothstep_boil = 1.0
                        else:
                            smoothstep_boil = (
                                10.0 * x_boil**3
                                - 15.0 * x_boil**4
                                + 6.0 * x_boil**5
                            )
                        q_boil = (
                            boiling_strength
                            * boiling_max_conductance_W_m2K
                            * delta_T_boil
                            * smoothstep_boil
                        )
                        if boiling_law_code == 1:
                            q_boil *= delta_T_boil / boiling_reference_superheat_K

                    q_loss = q_existing + q_boil
                    delta_u -= dt * q_loss / dx
                    top_loss_power_W += q_loss * area
                    existing_top_loss_power_W += q_existing * area
                    convection_loss_power_W += q_convection * area
                    radiation_loss_power_W += q_radiation * area
                    boiling_loss_power_W += q_boil * area

                h_old = _specific_enthalpy_scalar(
                    temperature, solidus_K, liquidus_K,
                    cp_solid, cp_mushy_effective, cp_liquid,
                )
                h_new = h_old + delta_u / rho
                T_out[i, j, k] = _temperature_from_enthalpy_scalar(
                    h_new, solidus_K, liquidus_K,
                    cp_solid, cp_mushy_effective, cp_liquid,
                )

    return (
        top_loss_power_W,
        existing_top_loss_power_W,
        convection_loss_power_W,
        radiation_loss_power_W,
        boiling_loss_power_W,
        side_loss_power_W,
        bottom_loss_power_W,
    )


def _boundary_mode_codes(params: SimulationParameters) -> tuple[int, int, int]:
    top_codes = {
        "adiabatic": 0,
        "convection": 1,
        "convection_radiation": 2,
        "fixed_temperature": 3,
    }
    artificial_codes = {
        "zero_flux": 0,
        "fixed_far_field": 1,
        "solid_absorbing": 2,
    }
    return (
        top_codes[params.boundary_conditions.top_surface_mode],
        artificial_codes[params.boundary_conditions.side_boundary_mode],
        artificial_codes[params.boundary_conditions.bottom_boundary_mode],
    )


def explicit_fvm_step_numba(
    temperature_K: np.ndarray,
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
    temperature_out_K: np.ndarray | None = None,
    *,
    return_boundary_powers: bool = False,
) -> tuple[np.ndarray, float] | tuple[np.ndarray, dict[str, float]]:
    """Advance one timestep with a compiled, allocation-free cell kernel.

    By default the second return value is top-surface loss power. Set
    ``return_boundary_powers=True`` to receive a dictionary containing signed
    top, side, bottom, and total external-boundary loss powers.
    """
    if not NUMBA_AVAILABLE:
        result = explicit_fvm_step(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            return_boundary_powers=return_boundary_powers,
        )
        T_new, boundary_result = result
        if temperature_out_K is not None:
            np.copyto(temperature_out_K, T_new)
            return temperature_out_K, boundary_result
        return T_new, boundary_result

    T_array = np.ascontiguousarray(temperature_K, dtype=np.float64)
    q_array = np.ascontiguousarray(volumetric_heat_source_W_m3, dtype=np.float64)
    if temperature_out_K is None:
        temperature_out_K = np.empty_like(T_array)
    elif temperature_out_K is temperature_K:
        raise ValueError(
            "temperature_out_K must not alias temperature_K for the explicit timestep."
        )

    material = params.material
    bc = params.boundary_conditions
    top_mode, side_mode, bottom_mode = _boundary_mode_codes(params)
    (
        top_loss_power_W,
        existing_top_loss_power_W,
        convection_loss_power_W,
        radiation_loss_power_W,
        boiling_loss_power_W,
        side_loss_power_W,
        bottom_loss_power_W,
    ) = _explicit_fvm_step_numba_kernel(
        T_array,
        q_array,
        temperature_out_K,
        float(params.time.dt_s),
        float(params.grid.uniform_spacing_m(params.geometry)),
        float(material.density_kg_m3),
        float(material.T_solidus_K),
        float(material.T_liquidus_K),
        float(material.cp_solid_J_kgK),
        float(material.cp_eff_mushy_J_kgK),
        float(material.cp_liquid_J_kgK),
        float(material.k_solid_W_mK),
        float(material.k_mushy_W_mK),
        float(material.k_liquid_effective_W_mK),
        int(top_mode),
        int(side_mode),
        int(bottom_mode),
        float(bc.ambient_temperature_K),
        float(bc.far_field_temperature_K),
        float(bc.convection_coefficient_W_m2K),
        float(bc.emissivity),
        float(bc.stefan_boltzmann_W_m2K4),
        float(bc.h_solid_W_m2K),
        float(bc.boiling_damper_strength),
        float(material.T_boiling_K),
        float(bc.boiling_transition_width_K),
        float(bc.boiling_max_conductance_W_m2K),
        0 if bc.boiling_loss_law == "smoothstep_linear" else 1,
        float(bc.boiling_reference_superheat_K),
    )
    top_loss_power_W = float(top_loss_power_W)
    existing_top_loss_power_W = float(existing_top_loss_power_W)
    convection_loss_power_W = float(convection_loss_power_W)
    radiation_loss_power_W = float(radiation_loss_power_W)
    boiling_loss_power_W = float(boiling_loss_power_W)
    side_loss_power_W = float(side_loss_power_W)
    bottom_loss_power_W = float(bottom_loss_power_W)

    if bc.boiling_damper_strength > 0.0:
        if not np.isfinite(boiling_loss_power_W) or boiling_loss_power_W < 0.0:
            raise FloatingPointError(
                "Patch 16.5.3 boiling-active Numba step produced invalid boiling power."
            )
        if not np.all(np.isfinite(temperature_out_K)):
            raise FloatingPointError(
                "Patch 16.5.3 boiling-active Numba step generated nonfinite temperature."
            )
        if np.any(temperature_out_K < 0.0):
            raise FloatingPointError(
                "Patch 16.5.3 boiling-active Numba step generated negative enthalpy/temperature state."
            )

    if return_boundary_powers:
        return temperature_out_K, {
            "top_loss_power_W": top_loss_power_W,
            "existing_top_loss_power_W": existing_top_loss_power_W,
            "convection_loss_power_W": convection_loss_power_W,
            "radiation_loss_power_W": radiation_loss_power_W,
            "boiling_loss_power_W": boiling_loss_power_W,
            "side_loss_power_W": side_loss_power_W,
            "bottom_loss_power_W": bottom_loss_power_W,
            "total_boundary_loss_power_W": (
                top_loss_power_W + side_loss_power_W + bottom_loss_power_W
            ),
        }
    return temperature_out_K, top_loss_power_W


def warm_up_numba_solver(params: SimulationParameters) -> None:
    """Compile the Numba timestep before the timed production loop."""
    if not NUMBA_AVAILABLE:
        return
    shape = (params.grid.Nx, params.grid.Ny, params.grid.Nz)
    T = np.full(shape, params.initial_condition.initial_temperature_K, dtype=np.float64)
    q_dot = np.zeros(shape, dtype=np.float64)
    T_out = np.empty_like(T)
    explicit_fvm_step_numba(T, q_dot, params, temperature_out_K=T_out)
    workspace = MeltPoolFeatureWorkspace(shape)
    _liquid_region_moments_and_largest_component(
        T.reshape(-1),
        float(params.material.T_liquidus_K),
        shape[0],
        shape[1],
        shape[2],
        workspace.visited,
        workspace.stack,
    )


# -------------------------------------------------------------------------
# Full explicit FVM timestep
# -------------------------------------------------------------------------

def explicit_fvm_step(
    temperature_K: np.ndarray,
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
    *,
    return_boundary_powers: bool = False,
) -> tuple[np.ndarray, float] | tuple[np.ndarray, dict[str, float]]:
    """
    Advance the temperature field by one explicit finite-volume step.

    The step is explicit in flux/source evaluation, but conservative in the
    thermodynamic update:

        1. evaluate conduction, boundary fluxes, and source at T_old;
        2. accumulate their net energy-density change delta_u [J/m^3];
        3. update h_new = h(T_old) + delta_u / rho;
        4. recover T_new from the same piecewise enthalpy curve used by
           diagnostics.

    This enthalpy update prevents a large source step from crossing the mushy
    interval without accounting for the corresponding latent enthalpy.
    """
    dt = params.time.dt_s

    delta_u = _compute_phase_aware_conduction_energy_density_update(temperature_K, params)
    delta_u += dt * np.asarray(volumetric_heat_source_W_m3, dtype=float)
    delta_u, boundary_powers = _apply_boundary_energy_density_fluxes(
        temperature_K, delta_u, params
    )

    T_new = _apply_enthalpy_energy_density_update(temperature_K, delta_u, params)
    if params.boundary_conditions.boiling_damper_strength > 0.0:
        if not np.all(np.isfinite(T_new)):
            raise FloatingPointError(
                "Patch 16.5.3 boiling-active Python step generated nonfinite temperature."
            )
        if np.any(T_new < 0.0):
            raise FloatingPointError(
                "Patch 16.5.3 boiling-active Python step generated negative enthalpy/temperature state."
            )
    if return_boundary_powers:
        return T_new, boundary_powers
    return T_new, float(boundary_powers["top_loss_power_W"])



def compute_source_power_W(
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
) -> float:
    """
    Discrete finite-volume source power:
        P = sum(volumetric_heat_source_W_m3) * dV
    """
    dx = params.grid.uniform_spacing_m(params.geometry)
    dV = dx**3
    return float(np.sum(volumetric_heat_source_W_m3) * dV)


def _compute_temperature_median_and_moments(
    values: np.ndarray,
    *,
    mean_K: float,
    minimum_K: float,
    maximum_K: float,
    median_buffer: np.ndarray | None,
) -> tuple[float, float, float, float]:
    """Return median, standard deviation, skewness, and Pearson kurtosis.

    This private boundary keeps the existing formulas intact while allowing the
    Patch 7.1 profiler to measure the median/higher-moment cost separately from
    the complete temperature-statistics call.
    """
    count = values.size
    if median_buffer is None:
        median_K = float(np.median(values))
    else:
        if median_buffer.size != count:
            raise ValueError("median_buffer must contain exactly temperature_K.size elements.")
        np.copyto(median_buffer, values)
        middle = count // 2
        if count % 2:
            median_buffer.partition(middle)
            median_K = float(median_buffer[middle])
        else:
            median_buffer.partition((middle - 1, middle))
            median_K = float(0.5 * (median_buffer[middle - 1] + median_buffer[middle]))

    # Higher standardized moments are undefined and numerically unstable when
    # the field is constant, or constant to machine precision. A range-based
    # test is more reliable than comparing the variance with float64 ``tiny``:
    # a perfectly uniform field can still acquire a ~1e-14 K mean-roundoff
    # offset when many cells are summed.
    temperature_scale_K = max(abs(minimum_K), abs(maximum_K), 1.0)
    constant_tolerance_K = 64.0 * np.finfo(np.float64).eps * temperature_scale_K
    effectively_constant = (maximum_K - minimum_K) <= constant_tolerance_K

    if effectively_constant:
        std_K = 0.0
        skewness = 0.0
        kurtosis = 0.0
    else:
        centered = values - mean_K
        second_moment = float(np.dot(centered, centered) / count)
        centered_squared = centered * centered
        third_moment = float(np.sum(centered_squared * centered, dtype=np.float64) / count)
        fourth_moment = float(np.dot(centered_squared, centered_squared) / count)
        std_K = float(np.sqrt(second_moment))
        skewness = float(third_moment / (second_moment ** 1.5))
        kurtosis = float(fourth_moment / (second_moment * second_moment))

    return median_K, std_K, skewness, kurtosis


def compute_temperature_statistics(
    temperature_K: np.ndarray,
    median_buffer: np.ndarray | None = None,
    *,
    compute_distribution_statistics: bool = True,
) -> dict:
    """Compute full-field scalar statistics with limited temporary storage.

    Minimum, maximum, and mean are always computed because they remain full-rate
    runtime/output quantities. When ``compute_distribution_statistics`` is
    false, median/std/skewness/kurtosis are returned as NaN rather than being
    interpolated or replaced with a physical-looking sentinel.
    """
    values = np.asarray(temperature_K, dtype=np.float64).reshape(-1)
    mean_K = float(np.mean(values, dtype=np.float64))
    minimum_K = float(np.min(values))
    maximum_K = float(np.max(values))
    if compute_distribution_statistics:
        median_K, std_K, skewness, kurtosis = _compute_temperature_median_and_moments(
            values,
            mean_K=mean_K,
            minimum_K=minimum_K,
            maximum_K=maximum_K,
            median_buffer=median_buffer,
        )
    else:
        median_K = float("nan")
        std_K = float("nan")
        skewness = float("nan")
        kurtosis = float("nan")

    return {
        "temperature_min_K": minimum_K,
        "temperature_max_K": maximum_K,
        "temperature_mean_K": mean_K,
        "temperature_median_K": median_K,
        "temperature_std_K": std_K,
        "temperature_skewness": skewness,
        "temperature_kurtosis_pearson": kurtosis,
    }



# -------------------------------------------------------------------------
# Module entry point
# -------------------------------------------------------------------------

if __name__ == "__main__":
    print(
        "solver.py is a library module. Run run_simulation.py for the "
        "HDF5 production workflow."
    )
