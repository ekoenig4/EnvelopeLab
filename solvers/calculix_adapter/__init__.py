"""CalculiX verification-solver adapter for EnvelopeLab (optional).

EnvelopeLab never links CalculiX: the adapter writes a CalculiX input deck, runs the
``ccx`` executable as a separate process and reads its text output back. CalculiX is not
a Python dependency; install the ``ccx`` program to use this package (see
``docs/dev/calculix-installation.md``). Nothing in ``envelopelab`` imports this package.
"""

from calculix_adapter.analysis import (
    CalculixCancelledError,
    CalculixProgress,
    CalculixRunError,
    CalculixSettings,
    run_calculix,
)
from calculix_adapter.detect import (
    SETUP_MESSAGE,
    CalculixInstallation,
    CalculixNotFoundError,
    find_calculix,
    require_calculix,
)

__all__ = [
    "SETUP_MESSAGE",
    "CalculixCancelledError",
    "CalculixInstallation",
    "CalculixNotFoundError",
    "CalculixProgress",
    "CalculixRunError",
    "CalculixSettings",
    "find_calculix",
    "require_calculix",
    "run_calculix",
]
