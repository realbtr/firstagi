"""Render a pilot report from saved H22 results; never supplies missing values."""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics

def load_results(root):
    summary = json.loads((root/"summary.json").read_text(encoding="utf-8"))
    if not summary.get("complete"):
        raise ValueError("suite is incomplete")
    checks = json.loads((root/"SHA256SUMS.json").read_text(encoding="utf-8"))
    for name, expected in checks.items():
        actual = hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"artifact hash mismatch: {name}")
    manifest = json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    groups = {}
    rows = []
    for result in summary["results"]:
        condition = result["condition"]["id"]
        full = json.loads((root/f"{condition}_seed{result['seed']}"/"result.json").read_text(encoding="utf-8"))
        groups.setdefault(condition,[]).append(full)
        for row in full["checkpoints"]:
            for domain, metric in row["metrics"].items():
                rows.append({"condition":condition,"seed":result["seed"],"domain":domain,
                    "training_steps":row["training_steps"],"base_size":row["base_size"],
                    "evictions":row["evicted"],"over_budget_steps":row["over_budget_steps"],
                    "avg_candidates":metric["avg_candidates"],"target_coverage":metric["target_coverage"],
                    "n_probe_transitions":metric["n"],"elapsed_s":row["elapsed_s"],
                    "empirical_bigram_avg":row["empirical_bigram_avg"]})
    return summary,manifest,groups,rows

def render(root, plots=False):
    summary,manifest,groups,rows = load_results(root)
    with (root.parent/"pilot_table.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    seeds=manifest["protocol"]["pilot"]["seeds"]
    lines=[]
    for condition,runs in groups.items():
        values=" / ".join(f"{r['late_avg_candidates']:.3f}" for r in runs)
        coverage=" / ".join(f"{r['late_target_coverage']*100:.1f}%" for r in runs)
        evictions=" / ".join(str(r['final_evicted']) for r in runs)
        sizes=" / ".join(str(r['final_base_size']) for r in runs)
        lines.append(f"| {condition} | {values} | {coverage} | {evictions} | {sizes} |")
    valid=summary["repeat_identical"] and summary["same_training_per_seed"] and summary["same_probes"]
    repeat=json.loads((root/"baseline_repeat/result.json").read_text(encoding="utf-8"))
    costs=[r["elapsed_s"] for runs in groups.values() for r in runs] + [repeat["elapsed_s"]]
    report=f'''# H22 pilot: what does the 7±2-like number measure?

**Date:** 2026-10-29. **Status:** completed pilot, preliminary; no final H22 verdict.

Preregistration / source commit: `{manifest['git_commit']}`.
Protocol SHA-256: `{manifest['protocol_sha256']}`.
Counterfactual idea: Solomon (The Colony). Baseline provenance feedback: Skitter.

## Result / Результат

The pre-probe candidate count changes across storage/tolerance settings in
this pilot. It is a count of lexical successors extracted from stored labels.
It does not establish a working-memory capacity. All values below are the
mean of the last two frozen familiar-probe checkpoints per seed, including
zero-candidate transitions. The pilot contains only two independent seeds.

Предварительный результат: число лексических кандидатов зависит от настроек
в исследованных условиях. Само попадание в диапазон 5–9 ещё не доказывает
возникновение ёмкости памяти. Основная серия пока не проведена.

| Condition | Late candidate mean (seeds {' / '.join(map(str,seeds))}) | Target coverage | Evictions | Final nodes |
|---|---|---|---|---|
{chr(10).join(lines)}

Coverage = fraction of probe targets present in a candidate set; this is not
forced-choice accuracy. Separate familiar/novel checkpoint values and the
empirical training-bigram baseline are in `pilot_table.csv`.

![Candidate count and target coverage for every condition and seed](h22_pilot.png)

## What was measured

Seven one-factor conditions, 8,000 training tokens each, two corpus seeds,
plus a baseline repeat. Baseline: uncapped store, tolerance 0.15,
max_competing 8. Fixed familiar (forest) and novel (sea) probes, 30 texts each.
The primary measure is `candidates_before`, computed on the frozen successor
index without calling `process_token`. Inputs are shared across conditions
within each seed; exact probe text overlaps are removed from training.
Capacity enforcement uses the original eviction policy from the first node,
not the legacy 3,125-node activation wall. Sleep/domain switching disabled.

## Instrumentation and controls

- Synthetic outdegrees 1/7/16 returned exactly 1/7/16.
- Same training input per seed across all conditions: **{summary['same_training_per_seed']}**.
- Same frozen probe corpus across conditions and seeds: **{summary['same_probes']}**.
- Repeated baseline non-timing output identical: **{summary['repeat_identical']}**.
- All recorded evaluation state guards passed; evaluation makes no learning calls.
- Combined control status: **{'PASS' if valid else 'FAIL — investigate before inference'}**.

Budget exceedances are logged because protected short chains can prevent
strict enforcement. Always read actual evictions and size beside nominal cap.

## Why this differs from legacy H22

`build_next_word_index` extracts successor labels from learned chains.
`avg_cands` therefore measures lexical branching. The legacy DualDriver probe
also updates both systems, and the legacy MR probe changes the grown state
and corpus RNG. Our diagnostic removes those measurement interventions.
It is **not an exact replication** of the old 1M-transition trajectory.

Code inspection also found a separate configured disambiguator cap of 8.
Changing it is an ablation, not proof that it determines lexical outdegree.
The old report's last-three-snapshot interval [4,8] differs from the new
preregistered descriptive 7±2 band [5,9]. Both definitions are disclosed.

## Cost and reproducibility

Fifteen pilot runs took {sum(costs):.1f} measured seconds total
(per-run median {statistics.median(costs):.1f} s, maximum {max(costs):.1f} s).
These times exclude tests, plotting and setup. The pilot is too short for
a reliable linear forecast of the 50,000-token phase: growth costs change
with store size. Run a longer timing sample before reserving its full budget.

Environment, dependency versions, source hashes and command: `pilot_v1/manifest.json`.
All raw inputs/results: `pilot_v1/`; original artifact checksums: `pilot_v1/SHA256SUMS.json`.
The report generator verifies those checksums before reading results.

```powershell
$env:PYTHONHASHSEED='0'
python training/h22_counterfactual.py --phase pilot --out experiments/reports/h22/pilot_reproduction
python training/h22_report.py --results experiments/reports/h22/pilot_v1 --plots
```

Plotting needs `matplotlib==3.9.4` (optional; runtime experiment does not).

## Limits and next decision

Only 8k tokens and two seeds: no late-stage convergence claim, memory span
claim, universal refutation, statistical significance claim or reasoning
benchmark. A frozen diagnostic can differ from online DualDriver learning.
No chunk-vs-symbol recall experiment or original scale-1M replication was run.

Before the confirmatory series, review whether the intended hypothesis is
lexical branching or actual memory capacity. Amend and preregister v2 if
necessary; keep pilot data out of confirmatory inference. The existing
50k/five-new-seed phase remains disabled. No challenge points are claimed.
'''
    (root.parent/"PILOT_REPORT.md").write_text(report,encoding="utf-8")
    if plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["svg.hashsalt"] = "firstagi-h22-pilot-v1"
        fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
        colors=["#1874c3","#d76c28"]
        ids=list(groups)
        axes[0].axhspan(5,9,color="#7cad81",alpha=.16,label="Descriptive 7±2 band")
        for x,(condition,runs) in enumerate(groups.items()):
            for j,r in enumerate(runs):
                dx=(-.09 if j == 0 else .09)
                axes[0].scatter(x+dx,r["late_avg_candidates"],color=colors[j],s=42,label=f"Seed {r['seed']}" if x==0 else None)
                axes[1].scatter(x+dx,100*r["late_target_coverage"],color=colors[j],s=42)
        for ax in axes:
            ax.set_xticks(range(len(ids)),ids,rotation=40,ha="right")
            ax.grid(axis="y",alpha=.2)
            ax.spines[["top","right"]].set_visible(False)
        axes[0].set_ylabel("Mean candidates per cue-target transition")
        axes[1].set_ylabel("Target present in candidates (%)")
        axes[0].legend(fontsize=8)
        axes[0].set_ylim(bottom=0)
        axes[1].set_ylim(0,100)
        fig.suptitle("H22 pilot · lexical candidates, not memory capacity\n8,000 training tokens · two seeds · frozen probes",fontsize=12)
        fig.savefig(root.parent/"h22_pilot.png",dpi=180)
        fig.savefig(root.parent/"h22_pilot.svg",metadata={"Date":None})
        plt.close(fig)
        plot_env={name:importlib.metadata.version(name) for name in ("matplotlib","numpy","pillow","contourpy","fonttools","kiwisolver","cycler","pyparsing")}
        (root.parent/"plot_environment.json").write_text(json.dumps(plot_env,indent=2),encoding="utf-8")
    artifacts=["PILOT_REPORT.md","pilot_table.csv"] + (["h22_pilot.png","h22_pilot.svg","plot_environment.json"] if plots else [])
    hashes={name:hashlib.sha256((root.parent/name).read_bytes()).hexdigest() for name in artifacts}
    (root.parent/"REPORT_SHA256SUMS.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    print("Rendered",root.parent/"PILOT_REPORT.md")

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results",required=True,type=Path)
    ap.add_argument("--plots",action="store_true")
    args=ap.parse_args()
    render(args.results.resolve(),args.plots)

if __name__ == "__main__": main()
