"""``python -m calculix_adapter [PATH]``: where CalculiX (ccx) was looked for, and why.

Exit code 0 when a working ``ccx`` is found, 1 otherwise. ``PATH`` is tried first, the
way the application tries its *CalculiX executable* preference.
"""

from __future__ import annotations

import sys

from calculix_adapter.detect import SETUP_MESSAGE, calculix_report, find_calculix


def main(argv: list[str]) -> int:
    explicit = argv[0] if argv else None
    print(calculix_report(explicit))
    if find_calculix(explicit) is None:
        print()
        print(SETUP_MESSAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
