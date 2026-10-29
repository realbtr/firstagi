"""C-14: preregistered frozen-probe H22 diagnostic. No core changes required."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.capacity import CapacityBudget
from core.dual_driver import build_next_word_index
from core.learning import LearningSystem
from drivers.smart_text_driver import CandidateSet, EntropyMinimizer
from drivers.text_driver import TextDriver
from training.scale_experiment import GenerativeCorpus

PROTOCOL = ROOT / "experiments/protocols/h22_v1.json"

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def words(text):
    return [w for w in re.split(r"[\s,.\-!?;:\"'()]+", text.lower()) if w]

def index_digest(index):
    return digest({k: sorted(v) for k, v in index.items()})

def measure(index, texts):
    """Exactly pre-probe candidate cardinality; no learning or zero filtering."""
    minimizer = EntropyMinimizer(min_entropy_threshold=0.5, max_probes=5)
    count = probes = covered = n = nonempty = 0
    histogram = Counter()
    for text in texts:
        ws = words(text)
        for cue, target in zip(ws, ws[1:]):
            candidates = list(index.get(cue, []))
            stats = minimizer.probe_word(target, CandidateSet(candidates))
            assert stats.candidates_before == len(candidates)
            n += 1
            count += len(candidates)
            nonempty += bool(candidates)
            covered += target in candidates
            probes += stats.probes_used
            histogram[len(candidates)] += 1
    if not n:
        raise ValueError("evaluation has no cue-target transitions")
    return {"n": n, "candidate_sum": count, "avg_candidates": count/n,
            "target_coverage": covered/n, "nonempty_rate": nonempty/n,
            "avg_probes": probes/n, "histogram": dict(sorted(histogram.items()))}

def synthetic_controls():
    out = []
    for degree in (1, 7, 16):
        index = {"cue": [f"item{i}" for i in range(degree)]}
        before = index_digest(index)
        m = measure(index, ["cue item0"])
        assert m["avg_candidates"] == degree and m["target_coverage"] == 1.0
        assert index_digest(index) == before
        out.append({"outdegree": degree, "measured": m["avg_candidates"]})
    return out

def frozen_probes(protocol):
    spec = protocol["corpus"]
    out = {}
    for name, domain in (("familiar", spec["training_domain"]), ("novel", spec["novel_domain"])):
        corpus = GenerativeCorpus(seed=spec["evaluation_seeds"][name])
        corpus._base_texts = []  # avoid fixed serial-text overlap in held-out probes
        while corpus.domain != domain:
            corpus.switch_domain()
        out[name] = corpus.generate_batch(spec["evaluation_texts_per_domain"])
    return out

def training_stream(seed, transitions, excluded):
    corpus = GenerativeCorpus(seed=seed)
    rows = []
    n = 0
    # Fixed-size calls matter: GenerativeCorpus samples serial texts per batch.
    while n < transitions:
        for text in corpus.generate_batch(30):
            if text in excluded:
                continue
            nt = len(list(TextDriver("count").produce(text)))
            if not nt:
                continue
            rows.append(text)
            n += nt
            if n >= transitions:
                break
    return rows

def semantic_state(system):
    """Evaluation guard, excluding UUID addresses that differ between runs."""
    rows = sorted((g.label or "", len(g.feature_chain), g.significance)
                  for g in system.base.all())
    return digest({"nodes": rows, "steps": system.engine.step_count,
                   "index": index_digest(build_next_word_index(system))})

def execute_run(protocol, condition, seed, phase, output):
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    spec = protocol[phase]
    probes = frozen_probes(protocol)
    excluded = set(probes["familiar"] + probes["novel"])
    texts = training_stream(seed, spec["transitions"], excluded)
    assert not excluded.intersection(texts)
    output.mkdir(parents=True, exist_ok=False)
    (output/"inputs.json").write_text(json.dumps({"training": texts, "evaluation": probes}, ensure_ascii=False, indent=2), encoding="utf-8")
    budget = CapacityBudget(max_gens=condition["capacity"]) if condition["capacity"] else None
    system = LearningSystem(feature_tolerance=condition["feature_tolerance"],
                            max_competing=condition["max_competing"], capacity_budget=budget)
    if budget:
        budget.attach_vitality(system.vitality)
    driver = TextDriver("h22_training")
    checkpoints = iter(spec["checkpoints"])
    next_checkpoint = next(checkpoints)
    count = over_budget_steps = 0
    rows = []
    observed = defaultdict(set)
    t0 = time.perf_counter()

    def snapshot():
        before = semantic_state(system)
        index = build_next_word_index(system)
        metrics = {name: measure(index, ts) for name, ts in probes.items()}
        empirical = measure({k: sorted(v) for k,v in observed.items()}, probes["familiar"])
        after = semantic_state(system)
        assert before == after, "evaluation changed the grown state"
        row = {"training_steps": count, "base_size": system.base.size(),
               "evicted": budget.total_evicted if budget else 0,
               "over_budget_steps": over_budget_steps,
               "index_sha256": index_digest(index), "frozen_state_unchanged": before == after,
               "metrics": metrics, "empirical_bigram_avg": empirical["avg_candidates"],
               "elapsed_s": time.perf_counter()-t0}
        rows.append(row)
        with (output/"checkpoints.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False)+"\n")

    for text in texts:
        ws = driver._tokenize(text)
        tokens = driver.produce(text)
        for i, token in enumerate(tokens):
            system.process_token(token)
            count += 1
            if i+1 < len(ws):
                observed[ws[i]].add(ws[i+1])
            over_budget_steps += bool(budget and system.base.size() > condition["capacity"])
            if count == next_checkpoint:
                snapshot()
                next_checkpoint = next(checkpoints, -1)
            if count >= spec["transitions"]:
                break
        system.reset_context()
        if count >= spec["transitions"]:
            break
    assert count == spec["transitions"] and len(rows) == len(spec["checkpoints"])
    late = rows[-2:]
    result = {"condition": condition, "seed": seed, "phase": phase,
              "training_sha256": digest(texts), "probe_sha256": digest(probes),
              "protocol_sha256": file_hash(PROTOCOL),
              "late_avg_candidates": statistics.mean(r["metrics"]["familiar"]["avg_candidates"] for r in late),
              "late_target_coverage": statistics.mean(r["metrics"]["familiar"]["target_coverage"] for r in late),
              "final_evicted": rows[-1]["evicted"], "final_base_size": rows[-1]["base_size"],
              "elapsed_s": time.perf_counter()-t0,
              "checkpoints": rows}
    result["nontiming_sha256"] = digest(without_timing(result))
    (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result

def without_timing(value):
    if isinstance(value, dict):
        return {k: without_timing(v) for k,v in value.items() if k not in ("elapsed_s", "nontiming_sha256")}
    if isinstance(value, list):
        return [without_timing(x) for x in value]
    return value

def run_suite(protocol, phase, output):
    if phase == "confirmatory" and not protocol[phase]["enabled"]:
        raise ValueError("confirmatory phase disabled; preregister an amendment after pilot review")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("launch with PYTHONHASHSEED=0")
    output.mkdir(parents=True, exist_ok=False)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"],cwd=ROOT,text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"],cwd=ROOT,text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unavailable", "unavailable"
    source_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"):file_hash(p)
                     for folder in ("core", "drivers", "training")
                     for p in sorted((ROOT/folder).glob("*.py"))}
    packages = {}
    for name in ("numpy", "pytest", "fastapi"):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    manifest = {"phase": phase, "git_commit": commit, "working_tree_status": dirty,
                "protocol_sha256": file_hash(PROTOCOL), "protocol": protocol,
                "source_sha256": source_hashes, "python": sys.version,
                "platform": platform.platform(), "processor": platform.processor(),
                "packages": packages, "pythonhashseed": os.environ["PYTHONHASHSEED"],
                "command": sys.argv, "synthetic_controls": synthetic_controls()}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    results = []
    for condition in protocol["conditions"]:
        for seed in protocol[phase]["seeds"]:
            name = f"{condition['id']}_seed{seed}"
            print("RUN", name,flush=True)
            result = execute_run(protocol,condition,seed,phase,output/name)
            results.append(result)
            print("DONE",name, "late=",round(result["late_avg_candidates"],4),
                  "evictions=",result["final_evicted"],"seconds=",round(result["elapsed_s"],2),flush=True)
    repeat_spec = protocol.get(phase,{}).get("repeat")
    repeat_ok = None
    if repeat_spec:
        condition = next(c for c in protocol["conditions"] if c["id"] == repeat_spec["condition"])
        repeated = execute_run(protocol,condition,repeat_spec["seed"],phase,output/"baseline_repeat")
        first = next(r for r in results if r["condition"]["id"] == condition["id"] and r["seed"] == repeat_spec["seed"])
        repeat_ok = repeated["nontiming_sha256"] == first["nontiming_sha256"]
    training_ok = all(len({r["training_sha256"] for r in results if r["seed"] == seed}) == 1 for seed in protocol[phase]["seeds"])
    summary = {"phase":phase,"complete":True,"runs":len(results),"repeat_identical":repeat_ok,
               "same_training_per_seed":training_ok,"same_probes":len({r["probe_sha256"] for r in results}) == 1,
               "results":[{k:v for k,v in r.items() if k != "checkpoints"} for r in results]}
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    hashes = {p.relative_to(output).as_posix():file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output/"SHA256SUMS.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    print("SUMMARY",json.dumps({k:v for k,v in summary.items() if k != "results"}),flush=True)
    if not training_ok or not summary["same_probes"] or repeat_ok is False:
        raise RuntimeError("validity check failed; retained all data; do not make a confirmatory claim")

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=("pilot","confirmatory"),default="pilot")
    ap.add_argument("--out",type=Path,required=True)
    args = ap.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    run_suite(protocol,args.phase,args.out.resolve())

if __name__ == "__main__": main()
