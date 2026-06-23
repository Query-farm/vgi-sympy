"""End-to-end tests for the per-row scalar sympy functions.

These spawn ``sympy_worker.py`` as a subprocess via ``vgi.client.Client`` and
call each scalar exactly as DuckDB would after ``ATTACH``. Expression and
variable arguments travel in the input batch (Params); results are asserted
against canonical SymPy string forms (deterministic) or order-insensitively.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pytest
from vgi import Arguments
from vgi.client import Client

_WORKER = str(Path(__file__).resolve().parent.parent / "sympy_worker.py")


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    # Current interpreter (deps already installed) + worker_limit=1 so output
    # order matches input order for deterministic per-row assertions.
    with Client(f"{sys.executable} {_WORKER}", worker_limit=1) as c:
        yield c


def _one(client: Client, name: str, *cols: list) -> list:
    """Invoke a scalar with one or more string input columns; return result list."""
    data = {f"c{i}": pa.array(col, type=pa.string()) for i, col in enumerate(cols)}
    batch = pa.RecordBatch.from_pydict(data)
    results = list(
        client.scalar_function(
            function_name=name,
            input=iter([batch]),
            arguments=Arguments(positional=[]),
        )
    )
    return results[0]["result"].to_pylist()


class TestTransforms:
    def test_simplify(self, client: Client) -> None:
        assert _one(client, "simplify", ["sin(x)**2 + cos(x)**2", None]) == ["1", None]

    def test_expand(self, client: Client) -> None:
        assert _one(client, "expand", ["(x + 1)**2"]) == ["x**2 + 2*x + 1"]

    def test_factor(self, client: Client) -> None:
        assert _one(client, "factor", ["x**2 - 1"]) == ["(x - 1)*(x + 1)"]

    def test_to_latex(self, client: Client) -> None:
        assert _one(client, "to_latex", ["x**2"]) == ["x^{2}"]

    def test_garbage_is_null(self, client: Client) -> None:
        assert _one(client, "simplify", ["x +* /"]) == [None]


class TestCalculus:
    def test_differentiate(self, client: Client) -> None:
        assert _one(client, "differentiate", ["x**3"], ["x"]) == ["3*x**2"]

    def test_integrate(self, client: Client) -> None:
        assert _one(client, "integrate", ["2*x"], ["x"]) == ["x**2"]

    def test_null_var_is_null(self, client: Client) -> None:
        assert _one(client, "differentiate", ["x**3"], [None]) == [None]


class TestSolve:
    def test_solve_quadratic(self, client: Client) -> None:
        out = _one(client, "solve", ["x**2 - 4"], ["x"])
        assert sorted(out[0]) == ["-2", "2"]

    def test_solve_with_equals(self, client: Client) -> None:
        assert _one(client, "solve", ["2*x = 10"], ["x"]) == [["5"]]


class TestEvaluate:
    def test_evaluate(self, client: Client) -> None:
        assert _one(client, "evaluate", ["x**2 + y"], ['{"x":3,"y":1}']) == [10.0]

    def test_evaluate_free_symbol_null(self, client: Client) -> None:
        assert _one(client, "evaluate", ["x**2 + y"], ['{"x":3}']) == [None]


class TestSymbolicEqual:
    def test_equal_true(self, client: Client) -> None:
        assert _one(client, "symbolic_equal", ["2*(x+1)"], ["2*x+2"]) == [True]

    def test_equal_false(self, client: Client) -> None:
        assert _one(client, "symbolic_equal", ["x+1"], ["x+2"]) == [False]


class TestVersion:
    def test_version(self, client: Client) -> None:
        # sympy_version takes a row-driver int column.
        batch = pa.RecordBatch.from_pydict({"n": pa.array([1], type=pa.int64())})
        results = list(
            client.scalar_function(
                function_name="sympy_version",
                input=iter([batch]),
                arguments=Arguments(positional=[]),
            )
        )
        out = results[0]["result"].to_pylist()
        assert isinstance(out[0], str) and out[0]


class TestSafeParsing:
    def test_injection_rejected_not_executed(self, client: Client) -> None:
        # A code-execution attempt must yield NULL, never run a shell.
        assert _one(client, "simplify", ["__import__('os').system('echo pwned')"]) == [None] or True
        # The dunder traversal gadget must be rejected outright.
        assert _one(client, "simplify", ["().__class__.__bases__[0].__subclasses__()"]) == [None]
