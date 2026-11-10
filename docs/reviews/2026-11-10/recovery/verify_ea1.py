#!/usr/bin/env python3
"""Rebuild and check the paused EA-1 artifact without resuming its agent.

All test outputs go to a new maintenance directory. The legacy validator is
recorded as a limited check, not a certification of the full research instrument.
"""

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    report_dir = workspace / "maintenance" / ("verification-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    for directory in (report_dir / "src", report_dir / "bin", report_dir / "out", report_dir / "results"):
        directory.mkdir(parents=True)
    for name in ("ea1.c", "refpy.py", "validate.py", "run_driver.py"):
        shutil.copy2(workspace / "src" / name, report_dir / "src" / name)
    inputs = {str(p.relative_to(report_dir)): digest(p) for p in (report_dir / "src").iterdir()}
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "workspace": str(workspace),
        "input_sha256": inputs,
        "commands": [],
        "checks": {},
        "scientific_validation": "not_established",
    }

    def run(command, name, timeout=120):
        started = time.monotonic()
        with (report_dir / (name + ".log")).open("w") as log:
            process = subprocess.run(
                command, cwd=report_dir, stdout=log, stderr=subprocess.STDOUT, timeout=timeout
            )
        result["commands"].append(
            {
                "argv": command,
                "returncode": process.returncode,
                "wall_seconds": round(time.monotonic() - started, 4),
                "log": name + ".log",
            }
        )
        return process.returncode == 0

    result["checks"]["build"] = run(
        ["gcc", "-O2", "-std=gnu17", "-Wall", "-Wextra", "-o", "bin/ea1", "src/ea1.c", "-lm"], "build"
    )
    if result["checks"]["build"]:
        result["binary_sha256"] = digest(report_dir / "bin/ea1")
        result["checks"]["fresh_selftest"] = run(
            ["bin/ea1", "--selftest", "--out", "out/st", "--n", "400"], "selftest"
        )
        result["checks"]["foreground_smoke"] = run(
            [
                "bin/ea1",
                "--task",
                "mux6",
                "--arm",
                "sel_pars_on",
                "--N",
                "100",
                "--T",
                "60",
                "--seed",
                "99",
                "--pres-every",
                "10",
                "--out",
                "out/smoke",
            ],
            "foreground-smoke",
        )
        if result["checks"]["fresh_selftest"] and result["checks"]["foreground_smoke"]:
            result["checks"]["legacy_gates"] = run(
                ["python3", "src/validate.py", "out/st", "out/smoke"], "legacy-validation"
            )
            with (report_dir / "out/smoke.gen.csv").open() as stream:
                rows = list(csv.reader(stream))
            result["checks"]["generation_csv_columns"] = all(len(row) == len(rows[0]) for row in rows[1:])
            with gzip.open(report_dir / "out/smoke.mem.csv.gz", "rt") as stream:
                reader = csv.reader(stream)
                header = next(reader)
                result["checks"]["motif_csv_columns"] = all(len(row) == len(header) for row in reader)
            result["checks"]["no_instrument_fault"] = (
                not (report_dir / "out/smoke.fault.txt").read_text().strip()
            )
            with (report_dir / "out/smoke.lin.bin").open("rb") as stream:
                count, size, seed = map(int, stream.readline().split())
                body = stream.read()
            result["checks"]["lineage_size"] = len(body) == count * size and size == 11
            result["checks"]["lineage_parents_precede_children"] = all(
                -1 <= int.from_bytes(body[i * size : i * size + 4], "little", signed=True) < i
                for i in range(count)
            )
            result["limitations"] = [
                "Legacy G5c/G5d/G5g include vacuous assertions and do not establish their advertised properties.",
                "Passing smoke checks does not establish motif semantics or the preregistered biological hypotheses.",
                "Recorded foreground wall time is a small-run measurement, not an estimate for the full grid.",
            ]
    for path in sorted((report_dir / "out").glob("st.*")):
        inputs[str(path.relative_to(report_dir))] = digest(path)
    result["checks_passed"] = all(result["checks"].values())
    (report_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"report": str(report_dir / "verification.json"), **result}, indent=2))
    return int(not result["checks_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
