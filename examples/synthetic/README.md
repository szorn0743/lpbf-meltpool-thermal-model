# Synthetic example

A fake coupon that lets a new user verify the installation and run the whole pipeline in about ten seconds,
without the experimental data. **Everything in it is synthetic**: two straight laser tracks, a constant "camera"
melt pool written into the file, a bright ellipse in every camera frame. The numbers it produces demonstrate only
that the code runs; they mean nothing scientifically and are not comparable with the thesis.

```powershell
python -m lpbf.reproduce example            # writes examples/synthetic/output/
```

What it does, in order (the code is `src/lpbf/synthetic_example.py`):

1. writes `output/synthetic_coupon.h5` in the layout of the real coupon files (500 process rows at 5 µs,
   22 camera frames, the `layer53/data`, `names`, `gige_time`, `gige_image` and `sync/` datasets);
2. selects the camera-side frames and applies the scored-frame rule (first and last frame of each track excluded):
   14 laser-on frames, 10 scored;
3. parses the file with the production loader, builds the frozen runtime (99 × 99 window, 16 µm, 2.5 µs) at the
   thesis's selected parameters (`src/lpbf/data/final_model.json`), and runs the numerical preflight;
4. runs the thermal solver over every process row (about 5 s) with the energy-accounting telemetry;
5. extracts the model's melt-pool H/W at every scored frame with the production beam-share association;
6. scores the frames with the log-ratio objective through the full hierarchy and writes
   `output/example_result.json` (per-frame records, energy accounting, objective, coverage) and
   `output/frame_records.csv`.

`tests/test_synthetic_example.py` runs the same example and checks the outputs exist, the energy balance closes
within the production tolerance (1e-9 relative), the frozen geometry and time step are in force, the Gaussian source
is normalized, every scored frame has finite H ≥ W, coverage is 1.0, and two runs are identical.
