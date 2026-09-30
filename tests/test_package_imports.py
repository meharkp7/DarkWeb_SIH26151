"""Import-time contracts for optional-dependency boundaries.

These assert properties that only fail at *import* time, which is why a
normal test run cannot catch them: by the time pytest is collecting, every
module it will ever import has already succeeded or raised. So each test
imports deliberately, in a subprocess where a poisoned import cannot leak
into the rest of the session.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Executed with `torch` made unimportable, standing in for any job that
#: synced without the ``ml`` extra. The ``backend`` job installs it, so this
#: only reproduces where the failure is invisible locally.
_NO_TORCH = textwrap.dedent(
    """
    import builtins

    _real = builtins.__import__


    def _guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return _real(name, *args, **kwargs)


    builtins.__import__ = _guarded
    """
)


def _run_without_torch(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _NO_TORCH + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_the_numeric_gnn_core_imports_without_torch() -> None:
    """`aegis.gnn` must not require its optional dependency to be imported.

    A package's `__init__` always runs before any submodule, so an eager
    `from aegis.gnn.torch_models import ...` there makes *every* import of
    the package need torch — including `aegis.gnn.graph` and
    `aegis.gnn.models`, which are numpy only.

    That is not hypothetical. The integration job syncs without the ``ml``
    extra and ignored three GNN modules, but not the fourth; collecting
    `tests/test_gnn_models.py` took the whole job down with::

        src/aegis/gnn/torch_models.py:14: in <module>
            import torch
        E   ModuleNotFoundError: No module named 'torch'

    The numeric models' own tests do not need torch and should not be
    excluded because of an import they never use.
    """
    result = _run_without_torch(
        """
        from aegis.gnn.graph import GnnNodeType, HeteroGraph
        from aegis.gnn.models import (
            ContradictionAwareTemporalHGT,
            HGTEncoder,
            RGCNEncoder,
            TemporalHGTEncoder,
        )
        from aegis.gnn import build_gnn_graph

        print("ok")
        """
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_the_torch_backed_exports_still_resolve_when_torch_is_present() -> None:
    """Laziness must not change the public surface.

    Every name in `__all__` has to be importable exactly as before.     A lazy
    `__getattr__` that missed an export would turn a working import into an
    `AttributeError` at first use — much harder to trace than an import
    error, and invisible to a test that only touches the numpy side.

    Skipped without torch, which is the point: this is the one test here
    that needs the `ml` extra. The `backend` job installs it so this runs;
    the integration job does not, so it must skip rather than fail. Without
    the guard it traded one collection error in that job for a test failure
    — the same mistake, one layer down.
    """
    pytest.importorskip("torch", reason="torch-backed exports need the `ml` extra")

    import aegis.gnn

    for name in aegis.gnn.__all__:
        assert hasattr(aegis.gnn, name), f"__all__ advertises {name!r} but it does not resolve"


def test_a_missing_torch_names_the_dependency_not_a_bare_module_error() -> None:
    """Asking for a torch-backed export without torch must say so clearly.

    The eager import raised `ModuleNotFoundError: No module named 'torch'`
    from inside an unrelated `__init__`, which names neither the attribute
    the caller asked for nor the package that wanted it. Deferred to first
    use, the caller can be told what to install.
    """
    result = _run_without_torch(
        """
        import aegis.gnn

        try:
            aegis.gnn.TemporalHeterogeneousGNN
        except ModuleNotFoundError as error:
            print(f"raised: {error}")
        else:
            raise SystemExit("expected the import to fail")
        """
    )

    assert result.returncode == 0, result.stderr
    assert "raised:" in result.stdout
    assert "torch" in result.stdout


def test_an_unknown_attribute_is_an_attribute_error() -> None:
    """A typo must not be reported as a missing optional dependency."""
    result = _run_without_torch(
        """
        import aegis.gnn

        try:
            aegis.gnn.NoSuchModel
        except AttributeError as error:
            print(f"raised: {error}")
        else:
            raise SystemExit("expected an AttributeError")
        """
    )

    assert result.returncode == 0, result.stderr
    assert "NoSuchModel" in result.stdout


def test_the_export_map_has_no_stale_entries() -> None:
    """Every lazily-declared name must actually exist in its module.

    The map is data, so nothing checks it for you. An entry naming a symbol
    that was renamed would otherwise surface as an `AttributeError` from
    inside the library rather than as a test failure here.

    Needs torch, because resolving an entry means importing the module that
    defines it. Skipped without the `ml` extra, as above.
    """
    pytest.importorskip("torch", reason="verifying the export map imports the torch modules")

    import importlib

    import aegis.gnn

    for name, module_name in aegis.gnn._TORCH_EXPORTS.items():
        module = importlib.import_module(module_name)
        assert hasattr(module, name), f"{module_name} no longer defines {name}"
        assert name in aegis.gnn.__all__, f"{name} is lazy but missing from __all__"

    # And nothing is advertised without being reachable.
    eager = {*aegis.gnn._EAGER, *aegis.gnn._TORCH_EXPORTS}
    assert set(aegis.gnn.__all__) == eager


@pytest.mark.parametrize(
    "module",
    [
        pytest.param("aegis.api.app", id="api-app"),
        pytest.param("aegis.attribution.fusion", id="attribution-fusion"),
        pytest.param("aegis.search.engine", id="search-engine"),
        pytest.param("aegis.copilot.service", id="copilot-service"),
    ],
)
def test_core_modules_import_without_torch(module: str) -> None:
    """Nothing on the request path may pull in the ML extra.

    The deployment runs without torch, so a stray import anywhere reachable
    from the API would be a crash at boot on a free-tier deploy rather than
    in a test. `aegis.gnn` is the known risk: its own `__init__` imported
    torch eagerly.
    """
    result = _run_without_torch(f"import {module}; print('ok')")

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
