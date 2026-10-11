"""Compare a committed generated validation page with a freshly generated one.

Generated pages are compared as text with their numbers taken out, and number by number.
Integers (node counts, pass counts) must match exactly; decimals may differ within a
platform tolerance. Converged solves of weakly determined quantities (displacements of
wrinkled fabric, near-mechanisms) differ by about 0.1 % between CPU architectures
(observed: Linux x86-64 vs macOS arm64), which moves the last printed digit; any fixed
rounding has boundaries where such a change flips a digit.

Numbers that are round-off zeros on both pages (magnitude at most :data:`ABSOLUTE`, e.g. a
closed-form seam error of 6.7e-16 m on one machine and 8.9e-16 m on another) match: their
value is the order of float64 round-off, not a result. Whether a benchmark passes is
asserted by its own test against its tolerance, not by this comparison.
"""

from __future__ import annotations

import math
import re

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
#: Relative tolerance on decimals, dimensionless.
RELATIVE = 5e-3
#: Absolute tolerance on percentages, percentage points.
PERCENT_POINTS = 0.5
#: Magnitude at or below which two numbers are both round-off zeros (unit of the page's
#: column; every page reports SI values or fractions of order 1, for which float64
#: round-off after a few thousand operations stays below this).
ABSOLUTE = 1e-12


def page_differences(
    committed: str,
    fresh: str,
    relative: float = RELATIVE,
    percent_points: float = PERCENT_POINTS,
) -> list[str]:
    """Differences between two generated pages beyond the platform tolerance.

    Parameters
    ----------
    committed, fresh : str
        Page texts.
    relative : float
        Relative tolerance on decimal numbers, dimensionless.
    percent_points : float
        Absolute tolerance on numbers followed by ``%``, percentage points.

    Returns
    -------
    list of str
        One message per difference; empty when the pages match.
    """
    masked_a, masked_b = NUMBER.sub("#", committed), NUMBER.sub("#", fresh)
    if masked_a != masked_b:
        for k, (la, lb) in enumerate(
            zip(masked_a.splitlines(), masked_b.splitlines(), strict=False)
        ):
            if la != lb:
                return [f"text differs at line {k + 1}: {la!r} vs {lb!r}"]
        return ["pages have different lengths"]
    out: list[str] = []
    ma, mb = list(NUMBER.finditer(committed)), list(NUMBER.finditer(fresh))
    for a, b in zip(ma, mb, strict=True):
        ta, tb = a.group(), b.group()
        if ta == tb:
            continue
        integer = not any(c in ta + tb for c in ".eE")
        va, vb = float(ta), float(tb)
        percent = committed[a.end() : a.end() + 2].lstrip().startswith("%")
        if max(abs(va), abs(vb)) <= ABSOLUTE:
            ok = True
        elif integer:
            ok = False
        elif percent:
            ok = abs(va - vb) <= percent_points
        else:
            ok = math.isclose(va, vb, rel_tol=relative, abs_tol=0.0)
        if not ok:
            line = committed.count("\n", 0, a.start()) + 1
            out.append(f"line {line}: {ta} vs {tb}")
    return out
