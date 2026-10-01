r"""Shared conventions of the rigging modules: seam azimuths, line results, findings.

Azimuth convention: vertical seam :math:`k` (1..N) joins gore :math:`k` and gore
:math:`k+1` (gore N+1 is gore 1) and lies at azimuth :math:`\varphi_k = 2\pi k / N`
(seam N at 0), measured counter-clockwise seen from above. Heights are those of the
meridian profile (the mouth is at :math:`z(0)`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from envelopelab.materials.repository import MaterialProperty

FloatArray = np.ndarray
Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class RiggingFinding:
    """A validation message about the parachute, rigging or turning vents.

    Attributes
    ----------
    code : str
        Machine-readable code.
    severity : {"info", "warning", "error"}
        Errors include every factor-of-safety failure.
    message : str
        Text shown to the builder.
    target : str
        Design section the finding points at (``parachute``, ``rigging``,
        ``turning_vents``).
    """

    code: str
    severity: Severity
    message: str
    target: str = ""


@dataclass(frozen=True)
class LineResult:
    """Length, limit load and factor of safety of one kind of line.

    Attributes
    ----------
    name : str
        What the line is (e.g. ``shroud line``).
    count : int
        Number of identical lines.
    length : float
        Length of each line, m.
    tension : float, optional
        Limit tension of the most loaded line, N (None when not assessed).
    strength : MaterialProperty
        Breaking strength, N, with its source tag.
    linear_mass : MaterialProperty
        kg/m, with its source tag.
    required_safety_factor : float
        Dimensionless.
    """

    name: str
    count: int
    length: float
    tension: float | None
    strength: MaterialProperty
    linear_mass: MaterialProperty
    required_safety_factor: float

    @property
    def safety_factor(self) -> float | None:
        """Breaking strength over limit tension (None when not assessed)."""
        if self.tension is None:
            return None
        return math.inf if self.tension <= 0.0 else self.strength.value / self.tension

    @property
    def passes(self) -> bool:
        """True when the safety factor meets the requirement (or is not assessed)."""
        fos = self.safety_factor
        return fos is None or fos >= self.required_safety_factor

    @property
    def total_length(self) -> float:
        """All lines of this kind, m."""
        return self.count * self.length

    @property
    def mass(self) -> float:
        """All lines of this kind, kg."""
        return self.total_length * self.linear_mass.value


def seam_azimuth(seam: int, gore_count: int) -> float:
    """Azimuth of vertical seam ``seam`` (1..N), rad (module docstring)."""
    if not 1 <= seam <= gore_count:
        raise ValueError(f"seam {seam} is not in 1..{gore_count}")
    return 2.0 * math.pi * (seam % gore_count) / gore_count


def point(radius: float, azimuth: float, height: float) -> FloatArray:
    """Cartesian point (x, y, z), m, from radius (m), azimuth (rad) and height (m)."""
    return np.array([radius * math.cos(azimuth), radius * math.sin(azimuth), height])


def fos_finding(line: LineResult, target: str, what: str | None = None) -> RiggingFinding | None:
    """An error when ``line`` fails its required factor of safety, else None."""
    fos = line.safety_factor
    if fos is None or line.passes:
        return None
    assert line.tension is not None
    return RiggingFinding(
        "fos",
        "error",
        f"{what or line.name}: factor of safety {fos:.2f} is below the required "
        f"{line.required_safety_factor:.2f} (limit load {line.tension:.0f} N, strength "
        f"{line.strength.value:.0f} N {line.strength.source})",
        target,
    )
