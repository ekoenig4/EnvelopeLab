r"""Membrane fabric and load-tape properties for the structural solvers.

Every value is a :class:`MaterialValue` carrying its SI unit and a source tag
(``datasheet | measured | assumed``). Stiffness and strength are *stress resultants*
(per unit width, N/m) because coated envelope fabrics have no meaningful thickness; a
datasheet modulus :math:`E` (Pa) converts with the fabric thickness, :math:`E t`.

Orthotropic plane stress in the fabric axes (1 = warp, 2 = weft):

.. math::
    \begin{bmatrix} N_{11} \\ N_{22} \\ N_{12} \end{bmatrix} =
    \frac{1}{1 - \nu_{12}\nu_{21}}
    \begin{bmatrix} E_1 t & \nu_{12} E_2 t & 0 \\ \nu_{12} E_2 t & E_2 t & 0 \\
    0 & 0 & (1 - \nu_{12}\nu_{21}) G_{12} t \end{bmatrix}
    \begin{bmatrix} \varepsilon_{11} \\ \varepsilon_{22} \\ \gamma_{12} \end{bmatrix},
    \qquad \nu_{21} = \nu_{12} \frac{E_2}{E_1}

with engineering shear strain :math:`\gamma_{12} = 2\varepsilon_{12}`. The matrix is
positive definite when :math:`E_1, E_2, G_{12} > 0` and :math:`\nu_{12}^2 < E_1/E_2`.

Reference: R. M. Jones, *Mechanics of Composite Materials*, 2nd ed., Taylor & Francis
(1999), sec. 2.5 (plane stress, orthotropic lamina).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

SourceTag = Literal["datasheet", "measured", "assumed"]
_SOURCES = ("datasheet", "measured", "assumed")


@dataclass(frozen=True)
class MaterialValue:
    """A material property with unit and provenance.

    Attributes
    ----------
    value : float
        Numerical value in ``unit``.
    unit : str
        SI unit string.
    source : {"datasheet", "measured", "assumed"}
        Provenance tag (AGENTS.md hard rule).
    note : str
        Optional citation or test reference.
    """

    value: float
    unit: str
    source: SourceTag
    note: str = ""

    def __post_init__(self) -> None:
        if self.source not in _SOURCES:
            raise ValueError(f"source must be one of {_SOURCES}, got {self.source!r}")
        if not math.isfinite(self.value):
            raise ValueError("material value must be finite")

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary."""
        return {"value": self.value, "unit": self.unit, "source": self.source, "note": self.note}


def _check_positive(name: str, item: MaterialValue) -> None:
    if item.value <= 0.0:
        raise ValueError(f"{name} must be positive, got {item.value} {item.unit}")


@dataclass(frozen=True)
class MembraneMaterial:
    """Orthotropic membrane fabric (warp/weft axes follow the pattern grain arrow).

    Attributes
    ----------
    name : str
        Display name.
    stiffness_warp, stiffness_weft : MaterialValue
        Tensile stiffness :math:`E t` along warp and weft, N/m.
    shear_stiffness : MaterialValue
        In-plane shear stiffness :math:`G_{12} t`, N/m.
    poisson_warp_weft : MaterialValue
        :math:`\\nu_{12}`, contraction along weft per unit warp strain, dimensionless.
    areal_mass : MaterialValue
        Mass per unit area including coating, kg/m^2.
    strength_warp, strength_weft : MaterialValue
        Tensile strength (breaking load per width), N/m.
    seam_efficiency : MaterialValue
        Seam strength divided by fabric strength, dimensionless in (0, 1].
    max_service_temperature : MaterialValue
        Maximum continuous fabric temperature, K.
    """

    name: str
    stiffness_warp: MaterialValue
    stiffness_weft: MaterialValue
    shear_stiffness: MaterialValue
    poisson_warp_weft: MaterialValue
    areal_mass: MaterialValue
    strength_warp: MaterialValue
    strength_weft: MaterialValue
    seam_efficiency: MaterialValue
    max_service_temperature: MaterialValue

    def __post_init__(self) -> None:
        for name in (
            "stiffness_warp",
            "stiffness_weft",
            "shear_stiffness",
            "strength_warp",
            "strength_weft",
            "max_service_temperature",
        ):
            _check_positive(name, getattr(self, name))
        if self.areal_mass.value < 0.0:
            raise ValueError("areal_mass must be non-negative")
        if not 0.0 < self.seam_efficiency.value <= 1.0:
            raise ValueError("seam_efficiency must be in (0, 1]")
        e1, e2 = self.stiffness_warp.value, self.stiffness_weft.value
        if self.poisson_warp_weft.value**2 >= e1 / e2:
            raise ValueError("nu_12^2 must be below E1/E2 for a positive-definite material")

    @classmethod
    def isotropic(
        cls,
        name: str,
        stiffness: float,
        poisson: float = 0.3,
        areal_mass: float = 0.0,
        strength: float = math.inf,
        seam_efficiency: float = 1.0,
        max_service_temperature: float = 1.0e4,
        source: SourceTag = "assumed",
    ) -> MembraneMaterial:
        """Isotropic membrane, the simple default.

        Parameters
        ----------
        name : str
            Display name.
        stiffness : float
            Tensile stiffness :math:`E t`, N/m.
        poisson : float
            Poisson's ratio, dimensionless (0 <= nu < 1).
        areal_mass : float
            kg/m^2.
        strength : float
            Tensile strength, N/m (``inf``: not checked; stored as 1e30).
        seam_efficiency : float
            Dimensionless.
        max_service_temperature : float
            K (default 1e4 K: not checked).
        source : {"datasheet", "measured", "assumed"}
            Source tag applied to every value.

        Returns
        -------
        MembraneMaterial
            Material with :math:`G t = E t / (2 (1 + \\nu))`.
        """
        s = source
        strength = 1e30 if math.isinf(strength) else strength
        return cls(
            name=name,
            stiffness_warp=MaterialValue(stiffness, "N/m", s),
            stiffness_weft=MaterialValue(stiffness, "N/m", s),
            shear_stiffness=MaterialValue(stiffness / (2.0 * (1.0 + poisson)), "N/m", s),
            poisson_warp_weft=MaterialValue(poisson, "-", s),
            areal_mass=MaterialValue(areal_mass, "kg/m^2", s),
            strength_warp=MaterialValue(strength, "N/m", s),
            strength_weft=MaterialValue(strength, "N/m", s),
            seam_efficiency=MaterialValue(seam_efficiency, "-", s),
            max_service_temperature=MaterialValue(max_service_temperature, "K", s),
        )

    def plane_stress_matrix(self) -> npt.NDArray[np.float64]:
        """Resultant constitutive matrix in fabric axes (Voigt, engineering shear).

        Returns
        -------
        ndarray, shape (3, 3)
            Maps :math:`(\\varepsilon_{11}, \\varepsilon_{22}, \\gamma_{12})` (dimensionless)
            to :math:`(N_{11}, N_{22}, N_{12})`, N/m.
        """
        e1, e2 = self.stiffness_warp.value, self.stiffness_weft.value
        nu12 = self.poisson_warp_weft.value
        nu21 = nu12 * e2 / e1
        d = 1.0 - nu12 * nu21
        return np.array(
            [
                [e1 / d, nu12 * e2 / d, 0.0],
                [nu12 * e2 / d, e2 / d, 0.0],
                [0.0, 0.0, self.shear_stiffness.value],
            ]
        )

    def sources(self) -> dict[str, dict[str, object]]:
        """Every property with value, unit and source tag."""
        return {
            name: getattr(self, name).as_dict()
            for name in self.__dataclass_fields__
            if name != "name"
        }


@dataclass(frozen=True)
class TapeMaterial:
    """Load tape, webbing or cable (tension only).

    Attributes
    ----------
    name : str
        Display name (matches the seam ``load_tape`` text in a build pack).
    axial_stiffness : MaterialValue
        :math:`E A`, N (force per unit engineering strain).
    breaking_strength : MaterialValue
        Breaking load, N.
    linear_mass : MaterialValue
        Mass per unit length, kg/m.
    """

    name: str
    axial_stiffness: MaterialValue
    breaking_strength: MaterialValue
    linear_mass: MaterialValue = field(
        default_factory=lambda: MaterialValue(0.0, "kg/m", "assumed")
    )

    def __post_init__(self) -> None:
        _check_positive("axial_stiffness", self.axial_stiffness)
        _check_positive("breaking_strength", self.breaking_strength)
        if self.linear_mass.value < 0.0:
            raise ValueError("linear_mass must be non-negative")

    def sources(self) -> dict[str, dict[str, object]]:
        """Every property with value, unit and source tag."""
        return {
            name: getattr(self, name).as_dict()
            for name in self.__dataclass_fields__
            if name != "name"
        }
