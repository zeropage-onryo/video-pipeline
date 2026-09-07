"""
Output roots -- no test writes into the real project tree.

The companion to conftest.py's network guard, and it exists for the same
reason that one does: the failure was silent. A test patches the HTTP
layer of a render path but not its output path, the fake downloader
writes 2048 zero bytes (the size QC's floor), and the stub lands in the
owner's real data/renders/higgsfield/ named wf-<stamp>.mp4 -- shaped
exactly like a real clip, listed beside real clips, shown in the Queue as
one. Twenty had collected on his Mac before a review of the pipeline's
output could not tell rendered work from test litter.

conftest's `output_roots_in_tmp` redirects every registered root to
tmp_path. That fixture can only redirect what someone remembered to
register, so this file is the part that notices when someone doesn't:

- the first test checks the fixture is actually in force, so a redirect
  that silently stops applying (a renamed constant, `raising=False` creep)
  fails here rather than on the owner's disk;
- the second is the static audit, modelled on tests/test_tenancy.py's --
  it walks every module in src/, app/ and ops/ and fails on ANY
  module-level path that still resolves inside the real data/ or footage/
  tree. A new RENDER_DIR added next month is caught by the fact that it
  exists, not by anyone thinking to test it.
"""
import importlib
import pkgutil
from pathlib import Path

import pytest
from conftest import OUTPUT_ROOTS, PROJECT_ROOT

# The two trees this project writes into. Everything else under the
# project root -- prompts/, locations/, characters/, props/ -- is source
# material that tests READ, and redirecting those would only hide the
# fixtures that legitimately live there.
WRITE_TREES = (PROJECT_ROOT / "data", PROJECT_ROOT / "footage")


def _modules():
    """Every importable module in the three packages, by dotted name.

    Hyphenated ops scripts (`ops/build-frame-bank.py`) are not importable
    names and are skipped -- they are one-shot scripts run by hand, never
    imported by the app, so nothing in a test run can touch their paths.
    """
    import app
    import ops
    import src

    for package in (src, app, ops):
        for info in pkgutil.iter_modules(package.__path__):
            if info.name.isidentifier():
                yield f"{package.__name__}.{info.name}"


def _inside_a_write_tree(value: Path) -> bool:
    for tree in WRITE_TREES:
        if value == tree or tree in value.parents:
            return True
    return False


def test_every_registered_output_root_is_redirected(output_roots_in_tmp):
    """The fixture is autouse, so this is asking whether it still WORKS:
    every registered constant now points inside the test's tmp_path."""
    for module_name, attr, _relative in OUTPUT_ROOTS:
        module = importlib.import_module(module_name)
        value = Path(getattr(module, attr)).resolve()
        assert output_roots_in_tmp.resolve() in value.parents, (
            f"{module_name}.{attr} is {value}, not under the test's tmp_path"
        )


def test_no_module_level_path_points_into_the_real_data_or_footage_tree():
    """The audit. A module-level Path that still resolves inside the real
    data/ or footage/ tree is an output root nobody redirected -- so the
    first test that exercises it writes to the owner's machine, and looks
    like it passed."""
    offenders = []
    for module_name in _modules():
        try:
            module = importlib.import_module(module_name)
        except Exception as e:                            # noqa: BLE001
            pytest.fail(f"{module_name} would not import for the audit: {e}")
        for attr, value in vars(module).items():
            if attr.startswith("__") or not isinstance(value, Path):
                continue
            if _inside_a_write_tree(value.resolve()):
                offenders.append(f"{module_name}.{attr} -> {value}")

    assert not offenders, (
        "module-level paths still point into the real project tree during a "
        "test run:\n  " + "\n  ".join(sorted(offenders)) + "\n\nAdd each to "
        "OUTPUT_ROOTS in tests/conftest.py so every test gets tmp_path, or "
        "the first test that writes through one litters data/ for real."
    )
