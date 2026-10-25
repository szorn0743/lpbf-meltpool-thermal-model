"""Exploratory (post hoc) check on Step-0 mean images: best rotation mapping layer52 onto layer53."""
import sys, json, math, csv, numpy as np, cv2
out = sys.argv[1]
prof = json.load(open(f"{out}/step0_profiles.json"))
summ = {(r["member_identity"], r["layer"]): r for r in csv.DictReader(open(f"{out}/step0_member_layer_summary.csv", encoding="utf-8"))}

def rotate(img, cx, cy, theta_deg):
    """Rotate by theta in image convention (angle from +x toward +y, y down)."""
    m = cv2.getRotationMatrix2D((cx, cy), -theta_deg, 1.0)
    rot = cv2.warpAffine(img.astype(np.float32), m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
    ok = cv2.warpAffine(np.ones_like(img, np.float32), m, (img.shape[1], img.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0) > 0.5
    return rot, ok

# sign-convention self-check on a synthetic ellipse
e = np.zeros((24, 64), np.uint8); cv2.ellipse(e, (32, 12), (10, 3), 30, 0, 360, 255, -1)
r, _ = rotate(e, 32, 12, 45)
ys, xs = np.nonzero(r > 128); w, v = np.linalg.eigh(np.cov(np.c_[xs, ys].T))
ax = math.degrees(math.atan2(v[1, 1], v[0, 1])) % 180
assert abs(ax - 75) < 4, ax

members = sorted({k[0] for k in summ})
angles = np.arange(-90, 91, 5)
print("member              cond   best_rot  rms@0  rms@+45  rms@best  (low-level band 8-150, cores aligned)")
best_all = []
for m in members:
    a = np.array(prof[f"{m}|layer52"]["mean_image"]); b = np.array(prof[f"{m}|layer53"]["mean_image"])
    s52, s53 = summ[(m, "layer52")], summ[(m, "layer53")]
    cx52, cy52 = float(s52["centroid_x_median"]), float(s52["centroid_y_median"])
    cx53, cy53 = float(s53["centroid_x_median"]), float(s53["centroid_y_median"])
    # translate layer52 so its core sits on the layer53 core, then rotate about it
    t = np.float32([[1, 0, cx53 - cx52], [0, 1, cy53 - cy52]])
    a_shift = cv2.warpAffine(a.astype(np.float32), t, (64, 24), flags=cv2.INTER_LINEAR, borderValue=0)
    ok_shift = cv2.warpAffine(np.ones((24, 64), np.float32), t, (64, 24), flags=cv2.INTER_NEAREST, borderValue=0) > 0.5
    rms = []
    for th in angles:
        ra, ok = rotate(a_shift, cx53, cy53, th)
        okr, _ = rotate(ok_shift.astype(np.float32), cx53, cy53, th)
        valid = ok & (okr > 0.5) & (b >= 8) & (b <= 150)
        rms.append(np.sqrt(np.mean((ra[valid] - b[valid]) ** 2)) if valid.sum() > 30 else np.nan)
    rms = np.array(rms); k = int(np.nanargmin(rms)); best_all.append(angles[k])
    print(f"{m:>16} {s53['condition_id']:>11} {angles[k]:7d} {rms[angles==0][0]:7.2f} {rms[angles==45][0]:7.2f} {rms[k]:8.2f}")
print("median best rotation:", np.median(best_all), " (scan-following predicts about +45; image-fixed predicts 0)")

fam = list(csv.DictReader(open(f"{out}/step0_threshold_family.csv", encoding="utf-8")))
print("\nlayer53 threshold family, median over members: thr  H_px  W_px  HW_nonedge  edge_touch")
for t in (30, 45, 60, 100, 150, 250):
    sel = [r for r in fam if r["layer"] == "layer53" and int(r["threshold"]) == t]
    f = lambda k: np.median([float(r[k]) for r in sel if r[k] not in ("", "None")])
    print(f"  {t:3d} {f('median_H_px'):6.1f} {f('median_W_px'):6.1f} {f('median_HW_non_edge'):6.2f} {f('edge_touch_fraction'):6.2f}  (range HW_nonedge {min(float(r['median_HW_non_edge']) for r in sel):.2f}-{max(float(r['median_HW_non_edge']) for r in sel):.2f})")
