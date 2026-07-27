# Patch 0.1.1

This patch fixes the Windows setup failure and replaces the minimal batch launchers with verbose, persistent launchers.

## Fixed setup failure

The previous setup command used:

```text
pip install --no-build-isolation -e .
```

A Python 3.12 virtual environment does not necessarily include `setuptools`. Disabling build isolation therefore made `pip` try to import `setuptools.build_meta` from an environment where it was absent.

The new setup sequence is:

```text
python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-build-isolation --editable .
```

The `pyproject.toml` build requirement now explicitly requests `setuptools>=69`. Build isolation remains disabled for the editable install, but only after the backend has been installed and verified in the virtual environment.

## Windows launcher changes

Every `.bat` file now:

- prints its working directory, configuration, current action, success or failure, and exit code;
- delegates to a PowerShell script that creates a persistent transcript under `logs\`;
- keeps the console open with `pause` on both success and failure;
- returns the underlying nonzero exit code after the pause.

The new `scripts/test.ps1` provides the same logging behavior for the test suite.
