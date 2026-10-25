# LPBF experimental setup and fixed process parameters

| Parameter | Value |
|---|---|
| Machine | Aconity Mini laser powder bed fusion system |
| Laser wavelength | 1070 nm |
| Laser spot diameter (nominal) | 80 µm, all coupons |
| Feedstock | m4p 316L.03 stainless steel powder |
| Build plate | 316L stainless steel |
| Atmosphere | Argon, O₂ < 300 ppm |
| Fume extraction | Pump at 50% duty cycle |
| Coupon geometry (programmed) | ≈ 4 mm × 4 mm × 6.48 mm |
| Layers per coupon | 216 |
| Layer thickness | 30 µm |
| Hatch spacing | 80 µm |
| Scan strategy | Contour pass, then hatch infill; hatch direction rotates by 45° between layers (0°, 45°, 90°, 135°) |
| Layer analysed | Layer 53 of every coupon; 54 laser-on scan tracks per coupon (track 1 = contour) |
| Laser power | 140–190 W |
| Scan speed | 600–1400 mm/s |
| Volumetric energy density | 41.7–125.0 J/mm³ (24 coupons, 18 conditions) |
| Process data acquisition | 200 kHz |
| Coaxial camera | Teledyne DALSA Genie Nano M640-NIR, 8-bit; 64 × 24 px region; ≈ 8 kHz; 40 µs exposure |
| Camera scale (nominal) | 8 µm/px, not independently calibrated |

- Rows marked 'owner' come from the thesis draft (section 3.2.1) and the owner's experimental record; the repository and the coupon HDF5 files do not record them. The HDF5 field 'n_layers_hit' (199–214) counts segmented layers and is not the design layer count.

Sources: Machine: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Laser wavelength: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Laser spot diameter (nominal): process record (A17); Feedstock: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Build plate: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Atmosphere: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Fume extraction: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Coupon geometry (programmed): owner (thesis section 3.2.1); not recorded in the repository or the coupon files; footprint consistent with the HDF5 part boundaries (4.10–4.30 mm × 4.05–4.10 mm); Layers per coupon: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; Layer thickness: A17; committee common.LAYER_MM; Hatch spacing: A17; committee common.HATCH_MM; Scan strategy: owner (thesis section 3.2.1); not recorded in the repository or the coupon files; rotation seen in layers 51–53 of the coupon files; Layer analysed: full_coupon_dataset_manifest.json; HDF5 Laser Drive; Laser power: process record (A17); Scan speed: process record (A17); Volumetric energy density: computed, P / (v h t); Process data acquisition: lpbf.model.input_data; Coaxial camera: ledger A24 (exposure: owner); HDF5 gige_image; Camera scale (nominal): ledger A24
