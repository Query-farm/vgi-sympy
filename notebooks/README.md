# Symbolic models through SQL

[01 · When is the reservoir fullest?](01_reservoir_storage.ipynb) derives storage
from a synthetic inflow pulse, checks two independent volume budgets, solves
stationary points and boundaries, and compares rates with accumulated volumes.
All algebra and numerical substitutions run through the real SymPy worker in
visible SQL. Python presents its returned results; it does not import SymPy.

[Open in Colab](https://colab.research.google.com/github/Query-farm/vgi-sympy/blob/main/notebooks/01_reservoir_storage.ipynb)
and run all cells. The bootstrap installs only the base
[shared notebook package v0.3.6](https://github.com/Query-farm/vgi-example-notebooks/tree/v0.3.6).
It preserves compatible preinstalled plotting and Jupyter libraries. The shared
package owns the [presentation standard](https://github.com/Query-farm/vgi-example-notebooks/blob/v0.3.8/docs/standard.md),
canonical branding and execution tooling. Saved GitHub charts use linked SVG
assets; fresh Jupyter and Colab runs display native SVG.

## Run locally

Prerequisites are Git and [uv](https://docs.astral.sh/uv/). From this directory:

```sh
uv sync --locked
uv run --locked vgi-notebooks 01_reservoir_storage.ipynb --timeout 300
```

The local environment installs the shared package's `[runner]` extra and locks
Haybarn 2.0.0rc11. Select `notebooks/.venv/bin/python` in a Jupyter editor and
restart the kernel before running all cells. The command above provides a
temporary kernel specification and starts in this notebook directory.

The visible connection uses the published release directly:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'sympy' (TYPE vgi, LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-sympy@v0.4.0 vgi-sympy-worker');
```

The worker runs in its own environment, with dependencies selected by that
release. No checkout, local worker binary, dependency overrides or engine build
is required. Initial downloads need network access; the calculation needs no API
or credentials. The shared connection starts with an empty temporary SQL-secret
directory and persistent secrets disabled. The returned SymPy version, **1.14.0**
in the saved run, appears beside the results and in figure provenance. To upgrade,
change the release deliberately and rerun the default, experiment and checks.

## Drain-rate experiment

Change only the drain from **8 to 12 L/min** in a separate output directory:

```sh
uv run --locked vgi-notebooks 01_reservoir_storage.ipynb \
  --parameters '{"DRAIN_L_MIN": 12.0}' \
  --output-dir artifacts/drain-12 --timeout 300
```

The measured peak moves from **153.814 L at 10.472 min** to **113.856 L at
9.464 min**. Final storage falls from **148 to 100 L**, matching the predicted
48 L of extra drainage. The inflow peak remains **18 L/min at 6 min** and total
inflow remains **144 L**. All seven identity checks and the simplified zero
budget residual remain unchanged. Each run's panels use independent volume scales;
compare their labeled values rather than apparent chart height.

Overrides require a separate destination, and failed runs preserve the last
successful default. Generated experiments, PNG review exports and logs stay
ignored. The notebook is also executable by itself through its base bootstrap;
it requires no local helper or asset companions.

## Model, units and limits

Inputs are explicitly synthetic: `q(t) = a*t*(tau-t)` L/min on the closed interval
`0 <= t <= tau`, with constant drain `d` L/min and initial storage `v0` L.
Defaults are `tau=12 min`, `a=0.5 L/min³`, `d=8 L/min`, `v0=100 L`. There are no
recorded or live observations. Units are declared assumptions; the CAS does not
infer dimensional types.

There is no capacity, spill, evaporation, drain shutoff or water-level dependent
drainage. Runs that reach zero storage are rejected after evaluating every exact
candidate minimum. Parameters must be finite, duration 1–60 min, pulse coefficient
0.01–2 L/min³, initial volume 1–10,000 L, drain strictly between zero and
`a*tau²/4`, and drawing samples 51–501. These restrictions keep two distinct
interior stationary points. Both boundaries participate in the global-extrema
comparison; the grid only draws curves. Nothing is extrapolated beyond the domain.

Transform failures and unresolved or non-real evaluations can return NULL.
Required results are checked before drawing and never replaced with zero.
Symbolic identities establish internal consistency, not physical accuracy.
Numerical substitutions use double precision and tolerance-based comparisons.

## Coverage and verification

[coverage.json](coverage.json) maps all **10 of 10** public logical SQL names to
visible executed SQL, results and interpretations. Separate complete released and
current catalogs include native function, table and view exports. The current
public baseline is `ccbc26579f9d0f970ab12fbc4ae90cb4c10ccdb1`; its worker source and
root dependencies match release v0.4.0. Examples ran against the release: exact
runtime coverage is 10/10 for the release and 0/10 for current-main revision,
with reviewed interface coverage 10/10 for both.

The saved default has 29 executed code cells and two SVG charts. Verification
includes the default, a notebook-only drain-12 run with a fresh worker cache,
all four figures, three runner protections, two input rejections and the
positive-storage domain rejection. A fresh Python 3.12 kernel with already
imported pandas 2.2.3, Matplotlib 3.10.0, IPython 8.30.0, ipykernel 6.17.1 and
jupyter-client 7.4.9 completed the notebook after base-only installation; those
versions remained unchanged and `pip check` passed. This is a local compatibility
test, not a claim of a manual hosted-Colab run.

Repository checks passed: 41 pytest tests, 31 SQL assertions across CAS and
security cases, Ruff, formatting, mypy, isolated doclint and executed metadata
validation (100/100, L2, zero findings). The worker implementation and root lock
are unchanged. The contributor commands remain in the root `CLAUDE.md`.

<p><a href="https://query.farm/"><img src="https://raw.githubusercontent.com/Query-farm/vgi-example-notebooks/v0.1.1/assets/query-farm-strata-sun.svg" alt="Query.Farm — Strata Sun" width="252"></a></p>
