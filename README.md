# RCABench Leaderboard

Reproducible CI/CD for all 12 algorithms reported by the FSE paper on FSE
RCABench and OPS-Lite. The repository pins every algorithm commit and dataset revision,
executes each datapack in Docker, calculates one canonical metric schema, and
publishes the latest results as a static leaderboard.

## What lives where

| Asset | Location |
|---|---|
| Benchmark controller, configs, results, site | This GitHub repository |
| Versioned telemetry datapacks and manifests | `HamsterStation/rcabench-fse` on Hugging Face |
| Immutable algorithm images | `ghcr.io/hamsterstation/rcabench-*` |
| Full evaluation compute | GitHub self-hosted runner labeled `rcabench` |
| Public result view | GitHub Pages deployment from `site/` |

The Hugging Face dataset and GitHub repository should remain private until the
original dataset redistribution terms have been confirmed.

## Pipeline

1. `config/algorithms.json` registers 12 algorithms and nine immutable images;
   `config/datasets.json` registers datasets. Each dataset config pins its
   revision, split sizes, resources, and error tolerances.
2. A new algorithm or dataset is proposed as a PR. `benchmark-pr.yml` detects
   only the affected algorithm × dataset pairs, builds candidate Linux/AMD64
   images, and evaluates them on the self-hosted server before merge.
3. Successful metrics are committed back to the PR and the bot squash-merges
   it automatically. Failed or incomplete evaluations remain open and cannot
   replace leaderboard values. `benchmark.yml` remains available for manual
   full or selected reruns.
4. ART and Eadro training outputs are cached by algorithm commit. A new data
   revision uses a fresh cache and retrains them.
5. Each datapack has an isolated log and atomic `result.json`; interrupted runs
   resume from existing valid result files.
6. `dataset-watch.yml` checks trusted Hugging Face repositories daily. A new
   revision regenerates deterministic splits and opens an auditable evaluation
   PR; the same PR gate runs metrics before automatic merge.
7. Metrics are validated, archived under `results/history/`, promoted to
   `results/leaderboard.json`, and deployed by `pages.yml`.

Dataset PRs first pass a cloud-only schema, immutable Hugging Face revision,
manifest partition, and sampled ground-truth check. Fork PRs never receive secrets or
run on the self-hosted server. After maintainer promotion to a trusted same-repository
branch, the PR expands to every registered algorithm and follows the metric/merge gate.

The registry contains BARO, ART, Eadro, CausalRCA, DiagFusion, MicroDig,
MicroHECL, MicroRank, MicroRCA, Nezha, ShapleyIQ, and SimpleRCA. DiagFusion's
released container uses its bundled checkpoint; those rows are marked with
that checkpoint policy and should not be described as leakage-free retraining
on a newly added dataset until a training adapter is implemented.

## Local commands

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

rcabench-leaderboard validate
rcabench-leaderboard doctor
rcabench-leaderboard download --output .cache/datasets/v1.0.0
```

Prepare the pinned OPS-Lite snapshot. This preserves the raw cases, creates a
compatible case view, and generates a deterministic 400/100 split balanced on
system, fault, service, and fault-service marginals:

```bash
rcabench-leaderboard download --config config/ops-lite.json \
  --output .cache/datasets/ops-lite
rcabench-leaderboard normalize --adapter ops-lite \
  --config config/ops-lite.json --snapshot .cache/datasets/ops-lite
```

Run BARO on the first five cases:

```bash
rcabench-leaderboard run baro \
  --snapshot .cache/datasets/v1.0.0 \
  --output runs/baro-smoke \
  --limit 5

rcabench-leaderboard evaluate baro \
  --snapshot .cache/datasets/v1.0.0 \
  --results runs/baro-smoke \
  --output runs/baro-smoke/metrics.json \
  --limit 5 --require-complete
```

ART and Eadro require a training preparation step:

```bash
rcabench-leaderboard prepare art --snapshot .cache/datasets/v1.0.0
rcabench-leaderboard prepare eadro --snapshot .cache/datasets/v1.0.0
```

## Metric contract

- `Top@1`, `Top@3`, `Top@5`, `Avg@3`, `Avg@5`, and `MRR` use the requested
  manifest size as their denominator. Missing or invalid results are misses.
- Duplicate service names are removed from rankings before scoring.
- Per-case algorithm exceptions are serialized as auditable misses. The CI
  fails if their count exceeds the configured tolerance.
- Rankings are compared at service level against every service listed in
  `injection.json` ground truth.
- OPS-Lite cases can contain two root services. Evaluation accepts either root;
  ART/Eadro training uses the first listed root because their released label
  pipelines are single-label.

## Operations

See [docs/SETUP.zh-CN.md](docs/SETUP.zh-CN.md) for deployment and recovery, and
[docs/DATASET_PR.zh-CN.md](docs/DATASET_PR.zh-CN.md) for the generic dataset PR flow.
