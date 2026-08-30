from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[2]

# The sync this proves is uv's; a machine that installs the project with pip has nothing
# for it to exercise, and a red line there says "the runtime is broken" when it is not.
requires_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed on this machine")


def _runtime_bin_directory(environment: Path) -> Path:
    return environment / ("Scripts" if os.name == "nt" else "bin")


def _uvicorn_command_path(runtime_bin: Path) -> Path:
    return runtime_bin / ("uvicorn.exe" if os.name == "nt" else "uvicorn")


def _system_path_without_global_python_scripts() -> str:
    if os.name == "nt":
        system_root = Path(os.environ["SystemRoot"])
        return os.pathsep.join((str(system_root), str(system_root / "System32")))
    return os.pathsep.join(("/usr/bin", "/bin"))


def _run_in_clean_project_environment(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run uv against a disposable environment, excluding globally installed tools.

    `uv` is invoked by absolute path on purpose. The trimmed `PATH` in `environment` is
    there to keep *globally installed Python scripts* out of the child's reach, and it
    resolves the executable too — so a bare "uv" is looked up in `/usr/bin:/bin` and is
    not found on any machine that installed uv anywhere else, which is every machine
    using Homebrew or uv's own installer. Locating the tool here and restricting the
    child there keeps the two concerns apart.
    """
    executable = shutil.which("uv")
    assert executable is not None, "guarded by requires_uv"
    return subprocess.run(
        [executable, *arguments],
        capture_output=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
    )


@requires_uv
def test_clean_runtime_sync_installs_and_imports_uvicorn(tmp_path: Path) -> None:
    """Removing the ASGI runtime dependency would omit the server command and module after sync."""
    runtime_environment = tmp_path / "runtime-environment"
    runtime_bin = _runtime_bin_directory(runtime_environment)
    environment = os.environ.copy() | {
        "UV_PROJECT_ENVIRONMENT": str(runtime_environment),
        "UV_LINK_MODE": "copy",
        "PATH": os.pathsep.join((str(runtime_bin), _system_path_without_global_python_scripts())),
    }

    synced = _run_in_clean_project_environment(["sync", "--frozen", "--no-dev"], environment)
    command = _run_in_clean_project_environment(
        ["run", "--no-sync", "python", "-m", "uvicorn", "--version"], environment
    )

    assert synced.returncode == 0, synced.stderr
    assert _uvicorn_command_path(runtime_bin).is_file()
    assert command.returncode == 0, command.stderr
    assert command.stdout.startswith("Running uvicorn ")
