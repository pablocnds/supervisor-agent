import csv
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def driver():
    path = Path(__file__).resolve().parents[1] / "docs/reviews/2026-11-10/recovery/ea1_run_driver.py"
    spec = importlib.util.spec_from_file_location("ea1_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resume_requires_successful_matching_receipt_and_preserves_legacy_outputs(tmp_path):
    module = driver()
    binary = tmp_path / "fake-ea1"
    binary.write_text(
        "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index('--out')+1]+'.sum.txt'); p.write_text('complete')\n"
    )
    binary.chmod(0o700)
    root = tmp_path / "runs"
    cell = module.build_cells(["mux6"], [100], ["neutral"], [0])[0]
    legacy = root / cell["tag"]
    legacy.mkdir(parents=True)
    (legacy / "r.sum.txt").write_text("unverified legacy")
    binary_sha = module.digest(binary)
    assert not module.completed(cell, root, binary_sha, [])
    record = module.run_one(cell, root, str(binary), [], binary_sha)
    assert record["rc"] == 0
    assert module.completed(cell, root, binary_sha, [])
    archived = next((tmp_path / "runs-superseded").glob("*/r.sum.txt"))
    assert archived.read_text() == "unverified legacy"
    assert not module.completed(cell, root, "different binary", [])
    assert not module.completed(cell, root, binary_sha, ["--different-config"])
    (root / cell["tag"] / "r.sum.txt").write_text("changed")
    assert not module.completed(cell, root, binary_sha, [])


def test_failed_process_cannot_be_resumed_as_complete_even_with_a_summary(tmp_path):
    module = driver()
    binary = tmp_path / "failing-ea1"
    binary.write_text(
        "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index('--out')+1]+'.sum.txt').write_text('partial')\nsys.exit(9)\n"
    )
    binary.chmod(0o700)
    cell = module.build_cells(["mux6"], [100], ["neutral"], [0])[0]
    root = tmp_path / "runs"
    record = module.run_one(cell, root, str(binary), [], module.digest(binary))
    assert record["rc"] == 9
    assert not module.completed(cell, root, module.digest(binary), [])
    assert json.loads((root / cell["tag"] / "run.json").read_text())["rc"] == 9


def test_interrupted_grid_keeps_fast_cell_receipt_and_manifest(tmp_path):
    module = driver()
    binary = tmp_path / "mixed-ea1"
    binary.write_text(
        "#!/usr/bin/env python3\nimport os,sys,time\nfrom pathlib import Path\n"
        "if sys.argv[sys.argv.index('--seed')+1]=='1' and not os.getenv('EA_TEST_NO_DELAY'): time.sleep(20)\n"
        "Path(sys.argv[sys.argv.index('--out')+1]+'.sum.txt').write_text('complete')\n"
    )
    binary.chmod(0o700)
    root = tmp_path / "runs"
    command = [
        sys.executable,
        module.__file__,
        "--binary",
        str(binary),
        "--out-root",
        str(root),
        "--tasks",
        "mux6",
        "--Ns",
        "100",
        "--arms",
        "neutral",
        "--seeds",
        "0,1",
        "--jobs",
        "2",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            manifest = root / "run_manifest.csv"
            if manifest.exists():
                with manifest.open() as stream:
                    if len(list(csv.DictReader(stream))) == 1:
                        break
            time.sleep(0.02)
        else:
            raise AssertionError("Fast cell was not persisted while the other cell was running")
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
    cell = module.build_cells(["mux6"], [100], ["neutral"], [0])[0]
    assert module.completed(cell, root, module.digest(binary), [])
    result = subprocess.run(
        command + ["--resume"],
        env={**os.environ, "EA_TEST_NO_DELAY": "1"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("1 runs,")
    with (root / "run_manifest.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 2
