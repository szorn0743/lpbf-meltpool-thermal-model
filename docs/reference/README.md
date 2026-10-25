# Reference records (read-only)

## `LPBF_Process_Parameters.csv`: experimental process parameters

This is the as-built laser power and travel speed for all 24 coupons: 4 acquisition dates × parts 1–6. **The
experiments have been run, so these values are a fixed record and must never change.** If one is ever found to
be wrong, record the correction in [`docs/DECISIONS.md`](../DECISIONS.md) and add a new, separately named file.
Never edit this one.

| Property | Value |
|---|---|
| Source | Owner-supplied file `LPBF_Process_Parameters.csv`, copied byte-for-byte on 2026-10-13 |
| SHA256 | `15faa033e51025698ccf138db760fa6e80e8ecce9e5389016dc4d440d602f304` |
| Size / format | 994 bytes, ASCII, CRLF line endings, no trailing newline, 24 data rows |
| Columns | Part Number, Power (W), Travel Speed (mm/s), Spot Size (mm), Area Power Density (J/mm2), Volumetric Power Density (J/mm3), Date |

### How it is protected

1. `tests/test_process_parameter_record.py` pins the SHA256, so any edit fails the test suite. The same test
   cross-checks the record against the code's own copies of these values:
   - `src/lpbf/data/patch21_0_calibration_contract.json`: power and speed for all 24 members.
   - `src/lpbf/data/full_coupon_dataset_manifest.json`: power, speed, spot size and both energy densities.

   All 120 values matched on 2026-10-13.
2. `.gitattributes` (`* -text`) stops git from converting line endings, so the bytes stay identical in every
   checkout.

### How the derived columns relate to the inputs

- **Area power density** = P / (v · d). Values are rounded half-up to 0.01; for example, 170 W at 1000 mm/s
  gives 2.125, recorded as 2.13.
- **Volumetric power density** = P / (v · h · t).
  - Hatch spacing h = 0.080 mm and layer thickness t = 0.030 mm, the same for all 24 coupons (owner, 2026-10-13).
  - Values from the Satterlee dissertation committee draft, §4.2. That section also gives P_E = P/(v·h·t) and
    P_C = P/(v·d), Eqs. 4.1–4.2.
- With these values, both derived columns reproduce exactly for all 24 rows (half-up rounding).
  `test_record_energy_densities_follow_from_hatch_and_layer_thickness` enforces this.

**Do not confuse with the dissertation's Table 4.1.** That process matrix describes a different, earlier
campaign: 12 coupons in two prints, e.g. 135 W / 800 mm/s and 75 W / 600 mm/s. This project's 24 coupons are
defined only by this record.

### Mapping to code identifiers

- The date maps to `acquisition_set_id`: 7/30/2026 → `20260730`, 7/31/2026 → `20260731`,
  9/4/2026 → `20260904`, 9/10/2026 → `20260910`.
- Part Number maps to `part_number`.
- The calibration and held-out split of these coupons is in `docs/DECISIONS.md` (A7, A8).
