"""Physics of a gore design's drawn profile: membrane check and natural shape.

The load of a design for :mod:`envelopelab.solvers.axisymmetric`:

* pressure gradient :math:`\\gamma = (\\rho_{amb} - \\rho_{int})\\, g` from the operating
  conditions (dry-air densities, as the live outputs and the simulation use), zero
  pressure at the mouth;
* weight per area :math:`w = m_{env} g / A`: the estimated envelope mass (fabric, tapes,
  seams; :func:`~envelopelab.project.gore_design.gore_outputs`) spread over the fabric
  area. Without a mass estimate the weight is left out and the result says so;
* the top opening closed by the parachute.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from envelopelab.atmosphere import G0
from envelopelab.design.model import DesignDocument
from envelopelab.materials.repository import FabricCatalog, FabricLibraryRepository
from envelopelab.project.gore_design import design_profile, gore_outputs
from envelopelab.project.model import PatternSet
from envelopelab.solvers.axisymmetric import (
    AxisymmetricLoad,
    MembraneCheck,
    NaturalShape,
    membrane_check,
    natural_shape,
)


@dataclass(frozen=True)
class DesignLoad:
    """The load of a design and where its values come from.

    Attributes
    ----------
    load : AxisymmetricLoad
        Pressure gradient (N/m^3), mouth height (m), weight per area (N/m^2).
    sources : tuple of str
        Source tags of the mass values (empty when the weight is left out).
    note : str
        What was left out, if anything.
    """

    load: AxisymmetricLoad
    sources: tuple[str, ...]
    note: str = ""


def design_load(
    design: DesignDocument,
    patterns: PatternSet,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
) -> DesignLoad:
    """Load of a gore design for the membrane check (module docstring).

    Raises
    ------
    ValueError
        For a special-shape design or an invalid profile.
    """
    outputs = gore_outputs(design, patterns, fabrics)
    profile = design_profile(design)
    gamma = (outputs.ambient_density - outputs.internal_density) * G0.value
    weight, note = 0.0, ""
    if outputs.envelope_mass is not None and outputs.area > 0.0:
        weight = outputs.envelope_mass * G0.value / outputs.area
    else:
        note = "envelope weight left out (no mass estimate)"
    load = AxisymmetricLoad(
        pressure_gradient=gamma,
        mouth_height=float(profile.z[0]),
        areal_weight=weight,
        top_closed=True,
    )
    return DesignLoad(load, outputs.sources if weight else (), note)


def check_design(
    design: DesignDocument,
    patterns: PatternSet,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
) -> MembraneCheck:
    """Membrane check of the drawn profile under the design's load."""
    return membrane_check(design_profile(design), design_load(design, patterns, fabrics).load)


def natural_design_shape(
    design: DesignDocument,
    patterns: PatternSet,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
    keep: str = "length",
) -> NaturalShape:
    """Natural shape with the design's mouth, top opening and tape length or height.

    Parameters
    ----------
    design : DesignDocument
        Gore design, m.
    patterns : PatternSet
        Row annotations (for the mass estimate).
    fabrics : FabricLibraryRepository, optional
        Fabric library (areal masses).
    keep : {"length", "height"}
        Which size of the drawn profile the shape keeps.

    Returns
    -------
    NaturalShape
        Shape (m) and tension (N); check ``converged``.
    """
    if keep not in ("length", "height"):
        raise ValueError(f"keep must be 'length' or 'height', not {keep!r}")
    profile = design_profile(design)
    load = design_load(design, patterns, fabrics).load
    check = membrane_check(profile, load)
    # Guess from the drawn profile: its mouth angle and the tension its check gives there.
    theta0 = math.atan2(float(profile.z[1] - profile.z[0]), float(profile.r[1] - profile.r[0]))
    valid = np.flatnonzero(check.evaluated)
    tension = (
        2.0 * math.pi * float(check.r[valid[0]]) * float(check.meridional[valid[0]])
        if valid.size
        else None
    )
    guess = (theta0, tension) if tension is not None and tension > 0.0 else None
    return natural_shape(
        load,
        (float(profile.r[0]), float(profile.z[0])),
        float(profile.r[-1]),
        length=profile.meridian_length if keep == "length" else None,
        height=profile.height if keep == "height" else None,
        guess=guess,
    )
