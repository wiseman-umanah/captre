"""
Developer convenience entry-point wrappers.

Each function is registered as a ``[project.scripts]`` entry point in
``pyproject.toml`` so it can be invoked directly:

    uv run captre           # start the API server (production mode, no reload)
    uv run captre-dev       # start the API server (dev mode, hot-reload enabled)
    uv run captre-test      # run the full unit test suite
    uv run captre-lint      # ruff lint check
    uv run captre-fmt       # ruff auto-format
    uv run captre-deploy    # deploy / re-use the Algorand smart contract

All commands delegate to subprocess so the return code is forwarded to the shell.
"""

import subprocess
import sys


def test() -> None:
    """
    Run the full unit test suite with verbose output.

    Delegates to ``pytest tests/unit/ -v``. Exit code mirrors pytest's.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with pytest's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/", "-v"],
        check=False,
    )
    sys.exit(result.returncode)


def lint() -> None:
    """
    Run ruff lint checks across the whole project.

    Delegates to ``ruff check .``. Exit code mirrors ruff's.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with ruff's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        check=False,
    )
    sys.exit(result.returncode)


def fmt() -> None:
    """
    Auto-format the project with ruff.

    Delegates to ``ruff format .``. Exit code mirrors ruff's.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with ruff's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "."],
        check=False,
    )
    sys.exit(result.returncode)


def deploy() -> None:
    """
    Deploy (or reuse) the CaptreApp smart contract on Algorand.

    Delegates to ``python -m captre.contract.deploy``. Reads ``ALGOD_URL``,
    ``DEPLOYER_MNEMONIC``, and optionally ``APP_ID`` from the ``.env`` file.
    If ``APP_ID`` is already set, the existing deployment is reused.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with the deploy script's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "captre.contract.deploy"],
        check=False,
    )
    sys.exit(result.returncode)


def deploy_task() -> None:
    """
    Deploy (or reuse) the TaskApp smart contract on Algorand.

    Delegates to ``python -m captre.contract.deploy_task``. Reads ``ALGOD_URL``,
    ``DEPLOYER_MNEMONIC``, and optionally ``TASK_APP_ID`` from the ``.env``
    file. If ``TASK_APP_ID`` is already set, the existing deployment is reused.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with the deploy script's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "captre.contract.deploy_task"],
        check=False,
    )
    sys.exit(result.returncode)


def deploy_ledger() -> None:
    """
    Deploy (or reuse) the LedgerApp smart contract on Algorand.

    Delegates to ``python -m captre.contract.deploy_ledger``. Reads
    ``ALGOD_URL``, ``DEPLOYER_MNEMONIC``, and optionally ``LEDGER_APP_ID``
    from the ``.env`` file. If ``LEDGER_APP_ID`` is already set, the existing
    deployment is reused.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with the deploy script's return code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "captre.contract.deploy_ledger"],
        check=False,
    )
    sys.exit(result.returncode)


def dev() -> None:
    """
    Run the development server with hot-reload enabled.

    Sets ``DEV=1`` in the environment so the app enables Jinja2
    ``auto_reload`` and other dev conveniences, then delegates to
    ``uvicorn`` with ``--reload``.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
        Exits the process with uvicorn's return code.
    """
    import os

    result = subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "captre:create_app",
            "--factory",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ],
        env={**os.environ, "DEV": "1"},
        check=False,
    )
    sys.exit(result.returncode)
