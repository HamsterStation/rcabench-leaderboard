# RCABench Leaderboard

Reproducible CI/CD for BARO, ART, Eadro, and CausalRCA on the FSE RCABench
dataset. The repository pins every algorithm commit and dataset revision,
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

1. `config/benchmark.json` pins the data revision, split sizes, algorithm
   commits, images, resources, and error tolerances.
2. `build-images.yml` builds Linux/AMD64 images from the exact upstream commits
   and pushes them to GHCR.
3. `benchmark.yml` downloads the pinned Hugging Face snapshot and runs the four
   algorithms sequentially on the self-hosted server.
4. ART and Eadro training outputs are cached by algorithm commit. A new data
   revision uses a fresh cache and retrains them.
5. Each datapack has an isolated log and atomic `result.json`; interrupted runs
   resume from existing valid result files.
6. Metrics are validated, archived under `results/history/`, promoted to
   `results/leaderboard.json`, and deployed by `pages.yml`.

## Local commands

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

rcabench-leaderboard validate
rcabench-leaderboard doctor
rcabench-leaderboard download --output .cache/datasets/v1.0.0
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

## Operations

See [docs/SETUP.zh-CN.md](docs/SETUP.zh-CN.md) for Hugging Face upload,
GitHub secrets, self-hosted runner setup, update flow, and recovery steps.

