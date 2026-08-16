from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unavailable_c_b6_and_legacy_contract_are_reported() -> None:
    fixture = ROOT / "fixtures" / "CO2C1R-20260815-CODEX-S001"
    unavailable = subprocess.run(
        [sys.executable, "verify/verify_co2_model.py", "--session-dir", str(fixture)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unavailable.returncode == 2
    assert "MODEL_ARTIFACT_UNAVAILABLE" in unavailable.stdout
    legacy = subprocess.run(
        [sys.executable, "verify/verify_co2_model.py", "--session-dir", str(fixture), "--model-contract", "team_legacy_3feature"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert legacy.returncode == 3
    assert "MODEL_INPUT_CONTRACT_MISMATCH" in legacy.stdout
