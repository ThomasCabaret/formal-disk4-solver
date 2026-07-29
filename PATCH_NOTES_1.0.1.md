# Patch 1.0.1 - Windows PowerShell launcher hotfix

This differential patch applies to version 1.0.0.

## Fixed

`scripts/run_case.ps1` contained one UTF-8 em dash. Windows PowerShell 5.1 can
interpret UTF-8 scripts without a BOM using the active ANSI code page. The
misdecoded byte sequence contained a quote-like character and broke parsing at
line 71.

The launcher is now entirely ASCII and uses ` - ` in the interactive case
label. No Python code, search criterion, configuration, output path, or SQLite
checkpoint format changes.

Existing 1.0.0 searches and checkpoints remain compatible.
