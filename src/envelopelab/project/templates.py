"""New-design templates: standard gore, special shape from a mesh, design from measurements.

Every value a template fills in without the user's input is a generic default the user is
expected to review (tape classes, seam type, rigging names); none of them is a material
property. Material properties come from the fabric library and carry its source tags.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from envelopelab.design.model import DesignDocument
from envelopelab.project.model import utc_now

#: Generic tape classes (width m, strength N) used by new designs; review before building.
DEFAULT_TAPES = {
    "vertical": {"class": "vertical load tape", "width": 0.025, "strength": 7000.0},
    "horizontal": {"class": "horizontal tape", "width": 0.025, "strength": 7000.0},
    "rim": {"class": "mouth webbing", "width": 0.05, "strength": 20000.0},
    "hole": {"class": "crown ring tape", "width": 0.025, "strength": 7000.0},
}


def _meta(name: str) -> dict[str, object]:
    now = utc_now().isoformat()
    return {
        "name": name,
        "version_id": f"v1-{uuid.uuid4().hex[:8]}",
        "parent_id": None,
        "content_hash": None,
        "created": now,
        "modified": now,
    }


def _common(
    name: str,
    fabric_id: str,
    seam_allowance: float,
    internal_temperature: float,
    ambient_temperature: float,
    ambient_pressure: float,
    payload_mass: float,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "meta": _meta(name),
        "zones": {"body": fabric_id},
        "tapes": DEFAULT_TAPES,
        "seam_types": [
            {
                "name": "flat felled",
                "allowance": seam_allowance,
                "rows_of_stitching": 2,
                "efficiency": 0.8,
            }
        ],
        "features": [],
        "operating": {
            "ambient_temperature": ambient_temperature,
            "ambient_pressure": ambient_pressure,
            "altitude": 0.0,
            "internal_temperature": internal_temperature,
            "payload_mass": payload_mass,
        },
        "scale_variants": [],
        "rigging": {
            "crown_line": "crown line",
            "red_line": "deflation line",
            "flying_wires": [],
            "parachute_confluence_centering": "centred",
        },
    }


def new_design(
    name: str,
    points: Sequence[tuple[float, float]],
    gore_count: int,
    row_heights: Sequence[float],
    mouth_diameter: float,
    top_diameter: float,
    fabric_id: str = "ripstop_nylon",
    seam_allowance: float = 0.025,
    internal_temperature: float = 373.15,
    ambient_temperature: float = 288.15,
    ambient_pressure: float = 101325.0,
    payload_mass: float = 0.0,
    row_letters: Sequence[str] | None = None,
    seal_overlap: float | None = None,
) -> DesignDocument:
    """A standard-gore design document.

    Parameters
    ----------
    name : str
        Design name.
    points : sequence of (float, float)
        Meridian control points (radius, height), m, mouth first.
    gore_count : int
        Gores N.
    row_heights : sequence of float
        Finished row heights along the tape, m, mouth first.
    mouth_diameter, top_diameter : float
        m (the top opening is the crown ring and parachute hole).
    fabric_id : str
        Fabric of the ``body`` zone.
    seam_allowance : float
        m.
    internal_temperature, ambient_temperature : float
        K.
    ambient_pressure : float
        Pa.
    payload_mass : float
        kg.
    row_letters : sequence of str, optional
        Row letters; default A, B, C, ...
    seal_overlap : float, optional
        Parachute seal overlap, m; default 0.1 of the top diameter.

    Returns
    -------
    DesignDocument
        With its content hash.
    """
    letters = list(row_letters) if row_letters else [chr(ord("A") + i) for i in range(26)]
    if len(row_heights) > len(letters):
        raise ValueError("more rows than row letters")
    payload = _common(
        name,
        fabric_id,
        seam_allowance,
        internal_temperature,
        ambient_temperature,
        ambient_pressure,
        payload_mass,
    )
    payload["envelope_type"] = "gore"
    payload["gores"] = {
        "count": gore_count,
        "meridian_profile_control_points": [{"x": float(r), "y": float(z)} for r, z in points],
        "panel_rows": [
            {"letter": letters[i], "finished_height": float(h)} for i, h in enumerate(row_heights)
        ],
        "mouth_diameter": mouth_diameter,
        "crown_ring": top_diameter,
        "parachute_hole_diameter": top_diameter,
        "seal_overlap": 0.1 * top_diameter if seal_overlap is None else seal_overlap,
    }
    return DesignDocument.model_validate(payload).with_updated_hash()


def special_design_from_mesh(
    name: str,
    mesh_path: str | Path,
    fabric_id: str = "ripstop_nylon",
    seam_allowance: float = 0.025,
    internal_temperature: float = 373.15,
    ambient_temperature: float = 288.15,
    ambient_pressure: float = 101325.0,
) -> DesignDocument:
    """A special-shape design that references an imported mesh (OBJ, STL or PLY).

    The mesh is read once to check that it is a usable triangle mesh; the design stores
    its path. Seam curves and panels are added later (panelling is not automatic).

    Parameters
    ----------
    name : str
        Design name.
    mesh_path : str or Path
        Reference mesh in m.
    fabric_id, seam_allowance, internal_temperature, ambient_temperature, ambient_pressure
        As :func:`new_design` (m, K, Pa).

    Returns
    -------
    DesignDocument
        ``envelope_type == "special"``.

    Raises
    ------
    envelopelab.io.reference_mesh.ReferenceMeshError
        For an unreadable or empty mesh.
    """
    from envelopelab.io.reference_mesh import read_mesh

    read_mesh(mesh_path)
    payload = _common(
        name,
        fabric_id,
        seam_allowance,
        internal_temperature,
        ambient_temperature,
        ambient_pressure,
        0.0,
    )
    payload["envelope_type"] = "special"
    payload["special"] = {
        "mesh_reference": str(mesh_path),
        "seam_curves": [],
        "panel_list": [],
    }
    return DesignDocument.model_validate(payload).with_updated_hash()


MEASUREMENTS_NOT_IMPLEMENTED = (
    "Design from measurements is not implemented yet (planned: fitting a profile to "
    "measured gore widths with envelopelab.geometry.gore.profile_from_gore_widths)."
)


def design_from_measurements(*_args: object, **_kwargs: object) -> DesignDocument:
    """Placeholder for the planned design-from-measurements workflow.

    Raises
    ------
    NotImplementedError
        Always; the wizard shows the message and offers no result.
    """
    raise NotImplementedError(MEASUREMENTS_NOT_IMPLEMENTED)
