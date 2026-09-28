r"""Finished piece outlines from imported cut and sew lines.

The *finished* outline of a piece is its sew line: the line the stitches follow and the
edge of the fabric that is visible once the seam is closed. When a pack gives only cut
lines, the finished outline is the cut outline inset by the seam allowance
(:func:`envelopelab.geometry.polygon.offset_polygon`). Holes work the other way round: the
finished edge of a hole is its cut line *grown* by the hem allowance.

Every finished outline is validated (closed, non-self-intersecting, nonzero area) and
normalised to counter-clockwise order in the pattern frame (seen from the outside of the
envelope, :math:`+y` up), which makes all panel normals point outward after assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from envelopelab.geometry.polygon import (
    FloatArray,
    OutlineCheck,
    distance_to_polyline,
    offset_polygon,
    orient_ccw,
    signed_area,
    validate_outline,
)
from envelopelab.io.pattern_import import (
    ImportWarning,
    PatternEntity,
    PatternImport,
    PieceKind,
    Provenance,
    RawPiece,
)

OutlineSource = Literal["sew", "inset", "exact"]


@dataclass(frozen=True, eq=False)
class FinishedHole:
    """A hole in a finished piece.

    Attributes
    ----------
    finished : ndarray, shape (n, 2)
        Finished (hemmed) hole edge, counter-clockwise, m.
    cut : ndarray, shape (n, 2)
        Cut line of the hole, counter-clockwise, m.
    source : {"sew", "inset"}
        Whether the finished edge is the drawn sew line or the grown cut line.
    provenance : Provenance
        Cut-line entity.
    """

    finished: FloatArray
    cut: FloatArray
    source: OutlineSource
    provenance: Provenance


@dataclass(eq=False)
class FinishedPiece:
    """A piece with validated finished and cut geometry.

    Attributes
    ----------
    piece_id, kind, quantity, mirrored
        From the import.
    outline : ndarray, shape (n, 2)
        Finished outline, counter-clockwise, m.
    cut_outline : ndarray, shape (n, 2)
        Cut outline, counter-clockwise, m.
    outline_source : {"sew", "inset", "exact"}
        ``sew`` = drawn sew line, ``inset`` = cut line inset by the allowance, ``exact`` =
        zero allowance (cut line used as is).
    holes : list of FinishedHole
        Holes cut in the piece.
    seam_allowance : float
        Configured seam allowance, m.
    measured_allowance : float or None
        Median distance from the finished outline to the cut outline, m (None when the
        finished outline was derived from the cut line).
    check, cut_check : OutlineCheck
        Validation of the finished and cut outlines as drawn.
    origin : ndarray, shape (2,)
        Local frame origin (bottom-centre of the finished outline bounding box) in the DXF
        pattern frame, m. Assembly works in coordinates relative to this point.
    material_zone : str
        Material zone name.
    grain : (float, float) or None
        Unit grain vector in the pattern frame.
    grain_source : str
        Where the grain came from.
    provenance : Provenance
        Cut-line entity; ``sew_provenance`` is the sew-line entity when present.
    entities : dict of str to list of PatternEntity
        Marks inside the piece (feature, tape, notch, ...), in the DXF pattern frame.
    """

    piece_id: str
    kind: PieceKind
    quantity: int
    mirrored: bool
    outline: FloatArray
    cut_outline: FloatArray
    outline_source: OutlineSource
    holes: list[FinishedHole]
    seam_allowance: float
    measured_allowance: float | None
    check: OutlineCheck
    cut_check: OutlineCheck
    origin: FloatArray
    material_zone: str
    grain: tuple[float, float] | None
    grain_source: str
    provenance: Provenance
    sew_provenance: Provenance | None
    entities: dict[str, list[PatternEntity]]
    corner_angle_deg: float
    label_text: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def finished_area(self) -> float:
        """Finished area (outline minus finished holes), m^2."""
        return abs(signed_area(self.outline)) - sum(
            abs(signed_area(h.finished)) for h in self.holes
        )

    @property
    def cut_area(self) -> float:
        """Cut area (cut outline minus cut holes), m^2."""
        return abs(signed_area(self.cut_outline)) - sum(abs(signed_area(h.cut)) for h in self.holes)

    @property
    def valid(self) -> bool:
        """Finished outline and every hole are valid."""
        return self.check.valid

    def local(self, points: FloatArray) -> FloatArray:
        """Convert pattern-frame points to this piece's local frame, m."""
        return points - self.origin


def measured_allowance(finished: FloatArray, cut: FloatArray) -> float:
    """Median distance from a finished outline's vertices to the cut outline.

    Parameters
    ----------
    finished, cut : ndarray, shape (n, 2)
        Closed outlines, m.

    Returns
    -------
    float
        Median allowance, m.
    """
    return float(np.median(distance_to_polyline(finished, cut, closed=True)))


def build_finished_piece(raw: RawPiece, warnings: list[ImportWarning]) -> FinishedPiece:
    """Build the finished geometry of one imported piece.

    Parameters
    ----------
    raw : RawPiece
        Imported piece.
    warnings : list of ImportWarning
        Appended with invalid-geometry errors and derivation assumptions.

    Returns
    -------
    FinishedPiece
        Finished piece (check ``valid`` before assembly).
    """
    pid = raw.piece_id
    cut_check = validate_outline(raw.cut.points, raw.cut.closed)
    cut = orient_ccw(raw.cut.points)
    measured: float | None = None
    if raw.sew is not None:
        check = validate_outline(raw.sew.points, raw.sew.closed)
        outline = orient_ccw(raw.sew.points)
        source: OutlineSource = "sew"
        measured = measured_allowance(outline, cut)
        if cut_check.orientation != check.orientation:
            warnings.append(
                ImportWarning(
                    "orientation",
                    f"{pid}: cut line is {cut_check.orientation} but sew line is "
                    f"{check.orientation}; both normalised to counter-clockwise",
                    severity="info",
                    piece_id=pid,
                    provenance=raw.sew.provenance,
                )
            )
    elif raw.seam_allowance == 0:
        outline, source, check = cut.copy(), "exact", cut_check
    else:
        outline = offset_polygon(cut, -raw.seam_allowance)
        source = "inset"
        check = validate_outline(outline, raw.cut.closed)
        warnings.append(
            ImportWarning(
                "assumption",
                f"{pid}: no sew line; finished outline = cut line inset by "
                f"{raw.seam_allowance * 1e3:.1f} mm",
                severity="info",
                piece_id=pid,
                provenance=raw.cut.provenance,
            )
        )
        if not check.valid:
            check = OutlineCheck(
                check.closed,
                check.simple,
                check.orientation,
                check.area,
                check.vertex_count,
                (*check.issues, "allowance inset exceeds the supported offset for this outline"),
            )
    for label, result in (("cut line", cut_check), ("finished outline", check)):
        for issue in result.issues:
            warnings.append(
                ImportWarning(
                    "invalid_geometry",
                    f"{pid}: {label}: {issue}",
                    severity="error",
                    piece_id=pid,
                    provenance=raw.cut.provenance,
                )
            )
    holes: list[FinishedHole] = []
    for hole in raw.holes:
        hole_cut = orient_ccw(hole.cut.points)
        if hole.sew is not None:
            finished = orient_ccw(hole.sew.points)
            hole_source: OutlineSource = "sew"
        else:
            finished = offset_polygon(hole_cut, raw.seam_allowance)
            hole_source = "inset"
        hole_check = validate_outline(finished, True)
        for issue in hole_check.issues:
            warnings.append(
                ImportWarning(
                    "invalid_geometry",
                    f"{pid}: hole {hole.cut.provenance.entity_id}: {issue}",
                    severity="error",
                    piece_id=pid,
                    provenance=hole.cut.provenance,
                )
            )
        holes.append(FinishedHole(finished, hole_cut, hole_source, hole.cut.provenance))
    lo = outline.min(axis=0)
    hi = outline.max(axis=0)
    origin = np.array([(lo[0] + hi[0]) / 2.0, lo[1]])
    return FinishedPiece(
        piece_id=pid,
        kind=raw.kind,
        quantity=raw.quantity,
        mirrored=raw.mirrored,
        outline=outline,
        cut_outline=cut,
        outline_source=source,
        holes=holes,
        seam_allowance=raw.seam_allowance,
        measured_allowance=measured,
        check=check,
        cut_check=cut_check,
        origin=origin,
        material_zone=raw.material_zone,
        grain=raw.grain,
        grain_source=raw.grain_source,
        provenance=raw.cut.provenance,
        sew_provenance=raw.sew.provenance if raw.sew is not None else None,
        entities=raw.entities,
        corner_angle_deg=raw.corner_angle_deg,
        label_text=raw.label.text if raw.label is not None else None,
    )


def build_finished_pieces(
    imported: PatternImport,
) -> tuple[dict[str, FinishedPiece], list[ImportWarning]]:
    """Finished geometry for every imported piece.

    Parameters
    ----------
    imported : PatternImport
        Import result.

    Returns
    -------
    (dict of str to FinishedPiece, list of ImportWarning)
        Pieces keyed by id and the warnings raised while building them.
    """
    warnings: list[ImportWarning] = []
    pieces = {raw.piece_id: build_finished_piece(raw, warnings) for raw in imported.pieces}
    return pieces, warnings
