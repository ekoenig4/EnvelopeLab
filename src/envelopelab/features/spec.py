"""Feature specification: the ``features`` section of a build-pack YAML file.

Every design-specific value of a feature (which pieces form it, where it sits, how many
match points, the designed ease, the intended dome height or lean) lives in the build
pack's YAML file, never in code. Lengths are written in mm (``*_mm``) and converted to m
by the accessors. Example (generic)::

    features:
      - name: pod_left
        kind: ram_air_pod
        host: {ring: body, gores: [3, 5], rows: [C, E]}
        footprint: {piece: pod_footprint}
        skin: {piece: pod_skin}
        rim: {seam: pod_rim, match_points: 12, tape: "rim tape"}
        feed_holes: [{opening: "body/D@4:feed"}]
        pressure: {mode: fed, loss_factor: 0.1}
        intended: {dome_height_mm: 600}
        construction:
          - {step: strip_seams}
          - {step: ordinate_check, tolerance_mm: 10}
          - {step: ease_onto_envelope}

Kinds
-----
``ram_air_pod``
    Pressure-fed pod or blister: a separate skin over a footprint, fed through holes.
``blister``
    Attached dome, blister or applique with surplus/ease (fed or independently set).
``tubular``
    Tube, horn or mast with optional internal ties.
``line_supported``
    Flexible appendage (fin, stayed mast) held by support lines.
``reinforced_hole``
    Reinforced opening (feed hole, vent) with hem tape and optional doubler.
``rim_tape``
    Perimeter reinforcement along a marked line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

FeatureKind = Literal[
    "ram_air_pod", "blister", "tubular", "line_supported", "reinforced_hole", "rim_tape"
]
StepKind = Literal[
    "strip_seams",
    "ordinate_check",
    "feed_holes",
    "rim_tape",
    "ease_onto_envelope",
    "gore_assembly",
    "doubler_caught_into_seams",
    "attach_appendage",
    "load_test",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostPlacement(_Strict):
    """Where a feature sits: ring, gore span and row span of the host panels."""

    ring: str
    gores: tuple[int, int]
    rows: tuple[str, str]
    mirror: bool = False
    margin_mm: float | None = None


class StripSource(_Strict):
    """Cutting sub-division of a skin into strips (for the ordinate check)."""

    file: str
    layer: str


class PieceRef(_Strict):
    """A finished piece (by piece id) or an assembly instance (by instance id)."""

    piece: str | None = None
    instance: str | None = None
    strips: StripSource | None = None
    grain: tuple[float, float] | None = None


class RimSpec(_Strict):
    """Rim seam of a skin onto its footprint line."""

    seam: str | None = None
    match_points: int = Field(default=16, ge=1)
    ease_mode: Literal["match_points", "pooled"] = "match_points"
    tape: str | None = None
    caught_into_host_tapes: bool = True
    match_start: tuple[float, float] | None = None


class FeedHoleRef(_Strict):
    """A feed hole: an assembly opening ``<instance>:<loop>``."""

    opening: str
    hem_tape: str | None = None


class PressureSpecModel(_Strict):
    """Chamber pressure: ``fed`` from feed holes or ``independent`` (Pa, m, Pa/m)."""

    mode: Literal["fed", "independent"] = "fed"
    loss_factor: float = Field(default=0.1, ge=0.0, lt=1.0)
    reference_pressure_pa: float | None = None
    gradient_pa_m: float | None = None


class TubeEnds(_Strict):
    """End conditions of a tubular appendage."""

    base_edge: str = "bottom"
    neck_edge: str = "top"
    side_a: str = "left"
    side_b: str = "right"
    neck_closed: bool = True
    tip_mass_kg: float = 0.0
    tip_lift_n: float = 0.0
    base_footprint_ellipse_mm: tuple[float, float] | None = None
    base_mark: str | None = None
    internal_ties_mm: list[float] = Field(default_factory=list)
    tie_tape: str | None = None


class SupportLineSpec(_Strict):
    """A support line from the neck ring to an anchor offset from the base, mm."""

    name: str
    neck_fraction: float = 0.0
    anchor_offset_mm: tuple[float, float, float]
    tape: str
    slack_mm: float = 0.0


class DoublerSpec(_Strict):
    """A doubled panel that must be caught into the surrounding seams."""

    instance: str
    caught_at: Literal["gore_assembly"] = "gore_assembly"


class ConstructionStep(_Strict):
    """One step of the construction sequence."""

    step: StepKind
    tolerance_mm: float | None = None
    note: str | None = None


class FeatureSpec(_Strict):
    """One special-shape feature."""

    name: str
    kind: FeatureKind
    host: HostPlacement
    footprint: PieceRef | None = None
    skin: PieceRef | None = None
    skin_zone: str | None = None
    rim: RimSpec = Field(default_factory=RimSpec)
    feed_holes: list[FeedHoleRef] = Field(default_factory=list)
    pressure: PressureSpecModel = Field(default_factory=PressureSpecModel)
    tube: TubeEnds | None = None
    supports: list[SupportLineSpec] = Field(default_factory=list)
    doubler: DoublerSpec | None = None
    intended: dict[str, float] = Field(default_factory=dict)
    construction: list[ConstructionStep] = Field(default_factory=list)
    mesh_size_mm: float = 250.0

    def intended_si(self) -> dict[str, float]:
        """Intended values with ``_mm`` keys converted to m (``_m``)."""
        out: dict[str, float] = {}
        for key, value in self.intended.items():
            if key.endswith("_mm"):
                out[key[:-3] + "_m"] = value / 1000.0
            else:
                out[key] = value
        return out


class FeaturesDocument(_Strict):
    """The ``features`` section plus the reference data used by the report."""

    features: list[FeatureSpec] = Field(default_factory=list)
    reference: dict[str, str | float] = Field(default_factory=dict)


def load_features(path: str | Path) -> FeaturesDocument:
    """Read the ``features`` (and optional ``reference``) sections of a build-pack YAML.

    Parameters
    ----------
    path : str or Path
        Build-pack YAML file.

    Returns
    -------
    FeaturesDocument
        Validated specification (empty when the file has no ``features`` section).
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return FeaturesDocument(
        features=[FeatureSpec(**f) for f in data.get("features", []) or []],
        reference={
            str(k): (v if isinstance(v, int | float) else str(v))
            for k, v in (data.get("reference") or {}).items()
        },
    )
