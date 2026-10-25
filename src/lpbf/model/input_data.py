"""Supported package adapter for exact-source-frozen HDF5/process input logic."""
from __future__ import annotations
from lpbf.model._accepted_core.input_data import (  # accepted-core package boundary
    LayerH5ProcessData,
    PRODUCTION_DAQ_DT_S,
    PRODUCTION_DAQ_FREQUENCY_HZ,
    PRODUCTION_LASER_DRIVE_THRESHOLD,
    _compute_scan_track_id,
    _infer_laser_drive_threshold,
    assert_fixed_production_time_s,
    decode_h5_names,
    iter_h5_process_blocks,
    load_layer_h5_process_data,
    prepare_h5_stream,
    resolve_h5_path,
)
compute_scan_track_id = _compute_scan_track_id
infer_laser_drive_threshold = _infer_laser_drive_threshold
__all__ = [
    "LayerH5ProcessData",
    "PRODUCTION_DAQ_DT_S",
    "PRODUCTION_DAQ_FREQUENCY_HZ",
    "PRODUCTION_LASER_DRIVE_THRESHOLD",
    "assert_fixed_production_time_s",
    "compute_scan_track_id",
    "decode_h5_names",
    "infer_laser_drive_threshold",
    "iter_h5_process_blocks",
    "load_layer_h5_process_data",
    "prepare_h5_stream",
    "resolve_h5_path",
]
