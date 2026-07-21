# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.16.0",
#     "sympy>=1.13",
# ]
# ///
"""Repo-root PEP 723 shim for the vgi-sympy worker.

The worker itself (the ``sympy`` catalog, the :class:`SympyWorker`, and
:func:`main`) lives in the wheel-importable :mod:`vgi_sympy.worker` module, so the
published wheel, the ``vgi-sympy-worker`` console script, and the container's
``vgi-serve vgi_sympy.worker:SympyWorker`` all carry the worker. This shim simply
re-exports them and runs the worker, so the historical entry point keeps working
unchanged::

    uv run sympy_worker.py              # serve over stdio (DuckDB subprocess)

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'sympy' (TYPE vgi, LOCATION 'uv run sympy_worker.py');

Because this file sits at the repo root, its directory is on ``sys.path`` when it
runs, so ``import vgi_sympy`` resolves whether launched as a PEP 723 script or
from the project venv (Makefile / ci/run-integration.sh / the pytest fixture).
"""

from __future__ import annotations

from vgi_sympy.worker import SympyWorker, main

__all__ = ["SympyWorker", "main"]


if __name__ == "__main__":
    main()
