from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


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
    """Run uv against a disposable environment, excluding globally installed tools."""
    return subprocess.run(
        ["uv", *arguments],
        capture_output=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
    )


def test_clean_runtime_sync_installs_and_imports_uvicorn(tmp_path: Path) -> None:
    """Removing the ASGI runtime dependency would omit the server command and module after sync."""
    runtime_environment = tmp_path / "runtime-environment"
    runtime_bin = _runtime_bin_directory(runtime_environment)
    environment = os.environ.copy() | {
        "UV_PROJECT_ENVIRONMENT": str(runtime_environment),
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
