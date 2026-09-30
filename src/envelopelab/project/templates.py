"""New-design templates: standard gore, special shape from a mesh, a saved project as a
template, design from measurements.

Every value a template fills in without the user's input is a generic default the user is
expected to review (tape classes, seam type, rigging names, the default parachute, red
line and flying wires of :mod:`envelopelab.rigging.defaults`). Fabric properties come
from the fabric library and carry its source tags; the default line and cable strengths
are tagged ``assumed``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from envelopelab.design.model import (
    CURRENT_SCHEMA_VERSION,
    DEFAULT_LOAD_FACTOR,
    DEFAULT_SAFETY_FACTOR,
    DesignDocument,
)
from envelopelab.project.model import DesignState, Project, utc_now

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
        "schema_version": CURRENT_SCHEMA_VERSION,
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
            "load_factor": dict(DEFAULT_LOAD_FACTOR),
            "required_safety_factor": dict(DEFAULT_SAFETY_FACTOR),
            "red_line": None,
            "flying_wires": None,
        },
        "parachute": None,
        "turning_vents": [],
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
    rigging: bool = True,
    row_zones: Sequence[str | None] | None = None,
    extra_zones: dict[str, str] | None = None,
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
    rigging : bool
        Add the default parachute, red line and flying wires
        (:func:`envelopelab.rigging.with_default_rigging`).
    row_zones : sequence of str or None, optional
        Material zone of each row (None: the ``body`` zone).
    extra_zones : dict of str to str, optional
        More zones (name to fabric id) next to ``body``, e.g. ``{"mouth": "nomex"}``.

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
    if row_zones is not None and len(row_zones) != len(row_heights):
        raise ValueError("row_zones and row_heights differ in length")
    zones_of_rows = list(row_zones) if row_zones is not None else [None] * len(row_heights)
    if extra_zones:
        payload["zones"] = {**payload["zones"], **extra_zones}  # type: ignore[dict-item]
    payload["envelope_type"] = "gore"
    payload["gores"] = {
        "count": gore_count,
        "meridian_profile_control_points": [{"x": float(r), "y": float(z)} for r, z in points],
        "panel_rows": [
            {"letter": letters[i], "finished_height": float(h), "zone": zones_of_rows[i]}
            for i, h in enumerate(row_heights)
        ],
        "mouth_diameter": mouth_diameter,
        "crown_ring": top_diameter,
        "parachute_hole_diameter": top_diameter,
        "seal_overlap": 0.1 * top_diameter,
    }
    document = DesignDocument.model_validate(payload)
    if rigging:
        from envelopelab.rigging import with_default_rigging

        document = with_default_rigging(document)
    return document.with_updated_hash()


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


def state_from_template(template: Project, name: str) -> DesignState:
    """The design state of a saved project, as the start of a new design.

    Everything that is designed is kept: the design document (shape, rows and their
    zones, materials, tapes, seams, features, operating conditions, parachute, rigging,
    turning vents, scoop) and the pattern annotations. The copy is a new design: its name
    is ``name``, it gets a new version id, no parent, the current time and a new content
    hash. Snapshots, versions, run records and the provenance log of the template are not
    part of the state and are not copied.

    Parameters
    ----------
    template : Project
        The template project.
    name : str
        Name of the new design.

    Returns
    -------
    DesignState
        Independent copy (editing it does not change ``template``).
    """
    if not name.strip():
        raise ValueError("a design from a template needs a name")
    state = template.state.model_copy(deep=True)
    meta = _meta(name.strip())
    data = state.design.model_dump(by_alias=True, mode="json")
    data["meta"] = meta
    design = DesignDocument.model_validate(data).with_updated_hash()
    return DesignState(design=design, patterns=state.patterns)


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
