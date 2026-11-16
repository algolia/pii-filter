"""The core install stays light: ``import pii`` never pulls the bench extra.

matplotlib lives in the optional ``bench`` extra. These tests run each check in a
fresh interpreter so modules already imported by other tests (pii.bench loads the
corpus helpers) cannot mask a regression.
"""

from __future__ import annotations

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_import_pii_does_not_import_matplotlib() -> None:
    proc = _run(
        "import sys, pii\n"
        "pii.Tier1Detector().detect('mail jane@example.com')\n"
        "print('matplotlib' in sys.modules)"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_bench_without_extra_fails_with_install_hint() -> None:
    # A None entry in sys.modules makes matplotlib unimportable, as if the extra
    # were not installed.
    proc = _run("import sys\nsys.modules['matplotlib'] = None\nimport pii.bench")
    assert proc.returncode != 0
    assert "ImportError" in proc.stderr
    assert "algolia-pii[bench]" in proc.stderr
