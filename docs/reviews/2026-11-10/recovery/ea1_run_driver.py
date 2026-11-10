#!/usr/bin/env python3
"""EA-1 foreground grid runner. Persist each result before starting more work.

Installed into the paused experiment's src/run_driver.py during the November
recovery. Legacy/incomplete outputs are archived, never silently trusted or
deleted. --resume requires a successful receipt for this binary and config.
"""

import argparse
import csv
import hashlib
import itertools
import json
import os
import shlex
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FIELDS = [
    "task",
    "N",
    "arm",
    "seed",
    "bottleneck",
    "T",
    "tag",
    "rc",
    "wall_s",
    "peak_rss_kb_delta",
    "cmd",
    "binary_sha256",
    "signature",
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_cells(tasks, Ns, arms, seeds, bottlenecks=(0,), T=1000, Tmap=None):
    cells = []
    for task, n, arm, seed, bn in itertools.product(tasks, Ns, arms, seeds, bottlenecks):
        generations = (Tmap or {}).get((task, n), T)
        tag = f"{task}_N{n}_{arm}_s{seed}_bn{bn}_T{generations}"
        cells.append(dict(task=task, N=n, arm=arm, seed=seed, bottleneck=bn, T=generations, tag=tag))
    return cells


def signature(cell, binary_sha, extra):
    return hashlib.sha256(json.dumps([cell, binary_sha, extra], sort_keys=True).encode()).hexdigest()


def completed(cell, out_root, binary_sha, extra):
    directory = Path(out_root) / cell["tag"]
    try:
        receipt = json.loads((directory / "completion.json").read_text())
        return (
            receipt["rc"] == 0
            and receipt["signature"] == signature(cell, binary_sha, extra)
            and receipt["summary_sha256"] == digest(directory / "r.sum.txt")
        )
    except (OSError, ValueError, KeyError):
        return False


def run_one(cell, out_root, binary, extra, binary_sha):
    directory = Path(out_root) / cell["tag"]
    if directory.exists():
        archive = Path(str(out_root).rstrip("/") + "-superseded")
        archive.mkdir(parents=True, exist_ok=True)
        directory.rename(archive / (cell["tag"] + "-" + uuid.uuid4().hex[:12]))
    directory.mkdir(parents=True)
    command = [
        binary,
        "--task",
        cell["task"],
        "--arm",
        cell["arm"],
        "--N",
        str(cell["N"]),
        "--T",
        str(cell["T"]),
        "--seed",
        str(cell["seed"]),
        "--bottleneck",
        str(cell["bottleneck"]),
        "--out",
        str(directory / "r"),
        *extra,
    ]
    started = time.monotonic()
    with (directory / "stderr.txt").open("w") as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    record = dict(
        cell,
        rc=process.returncode,
        wall_s=round(time.monotonic() - started, 4),
        peak_rss_kb_delta=None,
        cmd=shlex.join(command),
        binary_sha256=binary_sha,
        signature=signature(cell, binary_sha, extra),
    )
    summary = directory / "r.sum.txt"
    if process.returncode == 0 and summary.is_file():
        atomic_json(directory / "completion.json", {**record, "summary_sha256": digest(summary)})
    else:
        if record["rc"] == 0:
            record["rc"] = 1
        (directory / "FAILED.txt").write_text(f"rc={record['rc']}; see stderr.txt\n")
    atomic_json(directory / "run.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="mux6")
    parser.add_argument("--Ns", default="100,1000,10000")
    parser.add_argument("--arms", default="sel_pars_on,sel_pars_off,neutral")
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--bottlenecks", default="0")
    parser.add_argument("--T", type=int, default=1000)
    parser.add_argument("--Tmap", default="")
    parser.add_argument("--out-root", default="results/runs")
    parser.add_argument("--binary", default="bin/ea1")
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--extra", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    tmap = {}
    for item in filter(None, args.Tmap.split(",")):
        key, value = item.split("=")
        task, n = key.split(":")
        tmap[(task, int(n))] = int(value)
    cells = build_cells(
        args.tasks.split(","),
        list(map(int, args.Ns.split(","))),
        args.arms.split(","),
        list(map(int, args.seeds.split(","))),
        list(map(int, args.bottlenecks.split(","))),
        args.T,
        tmap,
    )
    binary_sha, extra = digest(args.binary), shlex.split(args.extra)
    if args.resume:
        cells = [c for c in cells if not completed(c, args.out_root, binary_sha, extra)]
    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "run_manifest.csv"
    if manifest.exists():
        with manifest.open() as stream:
            if next(csv.reader(stream), []) != FIELDS:
                parser.error("Manifest schema differs; use another --out-root and preserve the old results")
    print(f"{len(cells)} runs, {args.jobs} parallel, out={root}", flush=True)
    records = []
    with manifest.open("a", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
            stream.flush()
            os.fsync(stream.fileno())
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(run_one, c, root, args.binary, extra, binary_sha) for c in cells]
            for future in as_completed(futures):
                result = future.result()
                writer.writerow(result)
                stream.flush()
                os.fsync(stream.fileno())
                records.append(result)
                print(f"{result['tag']} rc={result['rc']} wall={result['wall_s']}s", flush=True)
    failed = sum(r["rc"] != 0 for r in records)
    print(f"DONE {len(records)} runs; {failed} failed", flush=True)
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
