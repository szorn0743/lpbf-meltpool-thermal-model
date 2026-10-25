# Recorded data channels and their roles

| Process Channel | Description | Format | Acquisition Rate | Unit | Role in present study |
|---|---|---|---|---|---|
| Laser Drive | Laser drive/state | 64-bit float | 200 kHz | V | Laser-state determination; ≥ 2.5 V = laser on, < 2.5 V = laser off |
| Sync Pulse | Synchronization channel | 64-bit float | 200 kHz | — | Recorded synchronization channel; not directly used in present analysis |
| X-Machine | Mapped machine X coordinate | 64-bit float | 200 kHz | mm | Machine/build plate coordinate |
| Y-Machine | Mapped machine Y coordinate | 64-bit float | 200 kHz | mm | Machine/build plate coordinate |
| Coaxial GigE camera | Coaxial melt-pool image | 8-bit grayscale (uint8), 24 × 64 pixels | 8 kHz | Dimensionless intensity (0–255) | Source imagery for experimental melt-pool geometry |
| H | Threshold derived major axis dimension | 64-bit float | 8 kHz-Derived | pixels | Experimental melt pool major axis dimension |
| W | Threshold derived minor axis dimension | 64-bit float | 8 kHz-Derived | pixels | Experimental melt pool minor axis dimension |

- Content supplied by the owner (2026-10-23) and reproduced as given. The code's laser-on rule is strict, Laser Drive > 2.5 V (lpbf.model.input_data); the signal is binary 0/5 V, so the two wordings select the same frames.
