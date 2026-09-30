r"""Scoop: fabric hanging below the mouth over consecutive gores.

A scoop continues the envelope below the mouth ring (radius :math:`r_m`) as a conical
frustum of depth :math:`H` flaring outward at :math:`\phi` from the vertical, over
:math:`k` consecutive gores (all :math:`N` gores make a full skirt). Its meridian runs from
the bottom edge :math:`(r_m + H\tan\phi,\ z_m - H)` straight up to the mouth; the slant
length is :math:`H/\cos\phi`. Each scoop panel is the gore of that frustum cut with the
envelope's small-bulge width model, so its top edge matches the bottom edge of the mouth
row within the seam tolerance.

The scoop's weight is included in the rigging mass. Wind loads on the scoop and its
effect on the mouth shape are not modelled; the structural model ends at the mouth.
"""

from __future__ import annotations

import math

import numpy as np

from envelopelab.geometry.gore import (
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    split_rows,
)

#: Label of the scoop panel piece.
PANEL_LABEL = "S"


def scoop_profile(
    mouth_radius: float, mouth_height: float, height: float, flare_deg: float
) -> MeridianProfile:
    """Scoop meridian from the bottom edge up to the mouth, m (module docstring)."""
    if height <= 0.0 or not 0.0 <= flare_deg < 60.0:
        raise ValueError("scoop height must be positive and flare in [0, 60) degrees")
    t = np.linspace(0.0, 1.0, 41)
    bottom = mouth_radius + height * math.tan(math.radians(flare_deg))
    r = bottom + (mouth_radius - bottom) * t
    z = mouth_height - height + height * t
    return MeridianProfile.from_points(r, z)


def scoop_panel(profile: MeridianProfile, gore_count: int, allowance: float) -> PanelRow:
    """Flat pattern of one scoop panel (bottom edge down, mouth seam up), m."""
    return split_rows(
        profile,
        GoreWidthModel(n_gores=gore_count, form="small_bulge"),
        [profile.meridian_length],
        labels=[PANEL_LABEL],
        allowance=SeamAllowance(side=allowance, bottom=allowance, top=allowance),
    )[0]
