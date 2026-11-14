"""Guard the composed example queries against drift.

Each composed example in :mod:`vgi_sympy.examples` is published in the worker's
metadata and its rows are pinned end-to-end in ``test/sql/cas.test``. This test
keeps the two copies identical, so an edited example cannot silently stop being
the query that the SQL test checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vgi_sympy.examples import COMPOSED_EXAMPLES

_CAS_TEST = (Path(__file__).resolve().parent.parent / "test" / "sql" / "cas.test").read_text()


@pytest.mark.parametrize("example", COMPOSED_EXAMPLES, ids=lambda e: e["sql"].split("\n", 1)[0][:40])
def test_composed_example_is_pinned_in_sql_test(example: dict[str, str]) -> None:
    assert example["description"].strip()
    assert example["sql"] + ";\n" in _CAS_TEST
