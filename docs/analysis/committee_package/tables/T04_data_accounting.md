# Data accounting

Every camera frame from the layer stream down to the scored frames, per coupon. Nothing is removed silently.

| Coupon | Role | Raw frames (layer) | Sync-mapped | Laser-on mapped | Camera-invalid | Eligible | Excluded first / last / single | Undefined | Scored | No-pool (scored as 0) | Coverage | Tracks scored |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260730:part_1 | calibration | 14,026 | 1,675 | 1,162 | 0 | 1,162 | 52 / 52 / 2 | 0 | 1,056 | 0 | 1.000 | 51 |
| 20260730:part_2 | in-window held out | 14,026 | 3,125 | 1,108 | 0 | 1,108 | 54 / 54 / 0 | 0 | 1,000 | 0 | 1.000 | 52 |
| 20260730:part_3 | calibration | 14,026 | 3,076 | 1,071 | 0 | 1,071 | 53 / 53 / 1 | 0 | 964 | 0 | 1.000 | 52 |
| 20260730:part_4 | in-window held out | 14,026 | 1,917 | 1,019 | 0 | 1,019 | 51 / 51 / 3 | 0 | 914 | 0 | 1.000 | 49 |
| 20260730:part_5 | calibration | 14,026 | 2,148 | 976 | 0 | 976 | 53 / 53 / 1 | 0 | 869 | 0 | 1.000 | 52 |
| 20260730:part_6 | calibration | 14,026 | 2,015 | 954 | 0 | 954 | 53 / 53 / 1 | 0 | 847 | 0 | 1.000 | 52 |
| 20260731:part_1 | calibration | 14,657 | 1,751 | 1,221 | 0 | 1,221 | 53 / 53 / 0 | 0 | 1,115 | 7 | 1.000 | 53 |
| 20260731:part_2 | in-window held out | 14,657 | 3,190 | 1,160 | 0 | 1,160 | 54 / 54 / 0 | 0 | 1,052 | 6 | 1.000 | 52 |
| 20260731:part_3 | calibration | 14,657 | 3,151 | 1,078 | 0 | 1,078 | 53 / 53 / 1 | 0 | 971 | 3 | 1.000 | 52 |
| 20260731:part_4 | in-window held out | 14,657 | 2,176 | 1,053 | 0 | 1,053 | 53 / 53 / 1 | 0 | 946 | 5 | 1.000 | 52 |
| 20260731:part_5 | calibration | 14,657 | 2,171 | 1,003 | 0 | 1,003 | 53 / 53 / 1 | 0 | 896 | 2 | 1.000 | 52 |
| 20260731:part_6 | calibration | 14,657 | 2,156 | 963 | 0 | 963 | 53 / 53 / 1 | 0 | 856 | 4 | 1.000 | 52 |
| 20260904:part_1 | out, examined | 14,369 | 3,363 | 1,626 | 0 | 1,626 | 54 / 54 / 0 | 0 | 1,518 | 0 | 1.000 | 52 |
| 20260904:part_2 | out, blind | 14,369 | 2,191 | 1,043 | 0 | 1,043 | 53 / 53 / 1 | 0 | 936 | 1 | 1.000 | 52 |
| 20260904:part_3 | out, examined | 14,369 | 2,185 | 755 | 0 | 755 | 53 / 53 / 1 | 0 | 648 | 347 | 1.000 | 51 |
| 20260904:part_4 | out, examined | 14,369 | 3,184 | 1,719 | 0 | 1,719 | 54 / 54 / 0 | 0 | 1,611 | 0 | 1.000 | 52 |
| 20260904:part_5 | in-window held out | 14,369 | 2,108 | 992 | 0 | 992 | 54 / 54 / 0 | 0 | 884 | 0 | 1.000 | 52 |
| 20260904:part_6 | out, examined | 14,369 | 1,275 | 765 | 2 | 763 | 53 / 53 / 0 | 0 | 657 | 22 | 1.000 | 52 |
| 20260910:part_1 | calibration | 15,289 | 3,173 | 1,477 | 0 | 1,477 | 54 / 54 / 0 | 0 | 1,369 | 0 | 1.000 | 53 |
| 20260910:part_2 | out, blind | 15,289 | 3,120 | 1,421 | 0 | 1,421 | 54 / 54 / 0 | 0 | 1,313 | 0 | 1.000 | 52 |
| 20260910:part_3 | out, examined | 15,289 | 3,179 | 1,484 | 0 | 1,484 | 54 / 54 / 0 | 0 | 1,376 | 0 | 1.000 | 52 |
| 20260910:part_4 | out, examined | 15,289 | 2,168 | 883 | 0 | 883 | 53 / 53 / 1 | 0 | 776 | 85 | 1.000 | 51 |
| 20260910:part_5 | out, blind | 15,289 | 2,192 | 884 | 0 | 884 | 54 / 54 / 0 | 0 | 776 | 0 | 1.000 | 52 |
| 20260910:part_6 | out, examined | 15,289 | 1,395 | 886 | 1 | 885 | 53 / 53 / 0 | 0 | 779 | 1 | 1.000 | 52 |
| All 24 coupons |  | – | 58,084 | 26,703 | 3 | 26,700 | 1278 / 1278 / 15 | 0 | 24,129 | 483 | 1.000 | 1,244 |

**Notes.**

- Identity checked for every coupon: eligible − excluded by rule − undefined = scored; eligible equals the Patch 21.3 characterization count.
- Raw frames are the whole layer's camera stream, shared by the six coupons of a set; sync-mapped frames are those the sync maps to this coupon's process rows (laser on or off).
- Camera-invalid: laser-on mapped frames whose camera H/W is non-finite (3 frames, track 54 of 20260904:part_6 and 20260910:part_6); they never enter residuals.
- No-pool frames are scored model predictions (D1), not exclusions; they are listed in D7 with the excluded frames.
- Frame-level ledger: `data/D7_exclusion_ledger.csv` (reconciles exactly with this table; test `test_committee_package.py`).
