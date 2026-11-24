# ADR-0057: Python 3.12 only, on Linux, macOS, Windows and WSL 2

- Status: Accepted
- Date: 2026-11-21
- Supersedes: the Python version of ADR-0001 (stack choice)

## Context
ADR-0001 set Python 3.11+, and CI ran every operating system on both 3.11 and 3.12.
Keeping 3.11 has cost real work: mypy had to run unpinned so that numpy's 3.12-only stub
syntax parsed, a fix was needed only to type numpy results for the 3.11 job, and the
PySide6 6.12 reference-count bug aborted the application on 3.11 alone (3.12 makes `None`
immortal). Builders install with the scripts, which already prefer 3.12.

## Decision
* EnvelopeLab supports **Python 3.12**. `requires-python` is `>=3.12`, so newer versions
  still install, but CI tests only 3.12 and the install scripts prefer it; the Windows
  script warns when it uses a newer one.
* The CI matrix is Python 3.12 on Linux, macOS and Windows, plus Windows with WSL 2 Ubuntu
  24.04. The operating systems are unchanged.
* Ruff targets `py312`. Mypy stays unpinned and checks against the interpreter it runs on.

## Consequences
Python 3.11 users must install 3.12 (the install scripts stop with a message). Code may use
3.12 syntax and standard library features. Moving the project's 3.12 floor to a newer
version later is a new ADR. The `<6.12` PySide6 cap was set for a 3.11-only crash; lifting
it is a separate change once the GUI suite has been run on 6.12.
