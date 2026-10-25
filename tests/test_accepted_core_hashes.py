from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_accepted_core_hashes_are_unchanged():
    manifest = json.loads((ROOT / "PATCH_22_3_4_ACCEPTED_CORE_HASHES.json").read_text(encoding="utf-8"))
    tracked = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src/lpbf/model/_accepted_core").glob("*.py"))
    assert sorted(item["path"] for item in manifest["files"]) == tracked
    for item in manifest["files"]:
        assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"], item["path"]
