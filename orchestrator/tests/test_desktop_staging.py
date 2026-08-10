"""Every path dependency a service declares must be staged into the desktop bundle.

This lives in the orchestrator suite for one reason: it is the suite CI runs on every
pull request. The desktop job runs signing-script tests and a Rust build, and never
executes `stage.sh` or `uv sync` — so the gap this covers was invisible to CI while
being fatal at runtime.

The failure it guards: `tauri/scripts/stage.sh` copies each service's `pyproject.toml`
and `uv.lock` into `resources/services/<name>/`, and the app then runs
`uv sync --frozen --project <that dir>` on first launch. `--frozen` means the lockfile
is authoritative, so a package the lockfile references but staging skipped does not
degrade — provisioning fails and the app never starts. Adding a path dep to a service
therefore silently breaks the desktop build unless staging picks it up, which is
exactly what happened when orrery-codesum and orrery-tracksum were added while
stage.sh still hand-listed orrery-relay alone.
"""

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STAGE_SH = _ROOT / "tauri" / "scripts" / "stage.sh"
_SERVICES = ["orchestrator", "worker"]

pytestmark = pytest.mark.skipif(
    not _STAGE_SH.is_file(),
    reason="desktop staging script not present in this checkout",
)


def _declared_path_deps(service: str) -> dict[str, str]:
    """`{name: relative path}` for every `[tool.uv.sources]` entry with a `path`."""
    data = tomllib.loads((_ROOT / service / "pyproject.toml").read_text())
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    return {name: spec["path"] for name, spec in sources.items()
            if isinstance(spec, dict) and "path" in spec}


def test_the_services_declare_path_deps_at_all():
    """Guard against a vacuous pass if the pyproject layout ever changes."""
    declared = {n for s in _SERVICES for n in _declared_path_deps(s)}
    assert "orrery-relay" in declared, (
        "no path dependencies found — the [tool.uv.sources] shape changed and the "
        "assertions below would silently check nothing")


@pytest.mark.parametrize("service", _SERVICES)
def test_every_declared_path_dep_lives_under_packages(service):
    """Staging copies `packages/*`, so a dep pointing elsewhere would not be staged."""
    for name, rel in _declared_path_deps(service).items():
        assert rel.startswith("../packages/"), (
            f"{service} declares {name} at {rel!r}, outside packages/ — stage.sh only "
            f"stages packages/*, so this would be missing from the desktop bundle")
        assert (_ROOT / service / rel).resolve().is_dir(), (
            f"{service} declares {name} at {rel!r}, which does not exist")


def test_staging_copies_every_package_rather_than_a_hand_listed_one():
    """The fix must be a loop over `packages/*`, not a longer list of `cp` lines.

    Asserted structurally on purpose. A test that only checked "orrery-codesum appears
    in stage.sh" would pass for a third hardcoded line and fail again on the fourth
    package — the point is that adding a package requires no edit here at all.
    """
    script = _STAGE_SH.read_text()
    assert re.search(r'for\s+pkg\s+in\s+"\$ORRERY"/packages/\*/', script), (
        "stage.sh should iterate packages/* so a new path dependency is staged "
        "automatically; a hand-listed copy per package is what broke the desktop "
        "bundle when orrery-codesum and orrery-tracksum were added")

    # And no package should still be singled out by name, which is how the loop gets
    # quietly bypassed for "just this one".
    hardcoded = re.findall(r'cp -r "\$ORRERY/packages/([\w-]+)"', script)
    assert not hardcoded, f"stage.sh still hardcodes package(s): {hardcoded}"


def test_the_staged_layout_matches_what_the_relative_paths_expect():
    """`../packages/x` from `services/worker/` must resolve to `services/packages/x`.

    stage.sh writes services to `resources/services/<name>` and packages to
    `resources/services/packages/<name>`, which is what makes the relative path in the
    lockfile resolve after staging. If either destination moved independently, uv would
    look outside the bundle.
    """
    script = _STAGE_SH.read_text()
    assert '"$RES/services/$name"' in script          # services/<name>
    assert '"$RES/services/packages/$name"' in script  # services/packages/<name>
