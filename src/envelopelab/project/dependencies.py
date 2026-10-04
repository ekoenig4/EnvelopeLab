"""Dependency graph of derived design artifacts and their staleness.

A project holds one *design state* (the design document, the pattern annotations and
the special shapes).
Everything derived from it (flat patterns, the seam graph, the as-sewn rest mesh,
simulation results, flattening, nesting and exports) is an *artifact*. Each artifact
depends on a set of *input groups* (slices of the design state, e.g. ``geometry`` or
``seam_allowance``) and on upstream artifacts:

.. code-block:: text

    geometry ──► profile
    geometry, seam_allowance, manual_outlines, labels, grain, row_zones,
      tape_paths, feature_locations, parachute, scoop ──► patterns ──► nesting ──► export
    geometry, manual_outlines, tape_paths, feature_locations, tapes,
      vent_openings ──► assembly
    assembly, grain, row_zones ──► rest_mesh ──► simulation
    operating, materials, fabric_properties, tapes, seam_construction ──► simulation
    geometry, manual_outlines ──► flattening
    materials, fabric_properties ──► nesting
    meta, rigging, turning_vents, scale_variants ──► export
    geometry, row_zones, materials, shapes ──► shapes

The *fingerprint* of an artifact is the SHA-256 of its own input slices and the
fingerprints of its upstream artifacts. An artifact built with fingerprint ``f`` is
*current* while the design's fingerprint for it is still ``f`` and *stale* otherwise, so
an edit that is undone makes the artifact current again, and a seam-allowance change
(which only the ``patterns`` branch reads) never touches the rest mesh or simulations.

``materials`` is the design's zone-to-fabric-id map. The fabrics themselves live in the
fabric library shared by all designs, outside the project file, so their values form the
separate *external* group ``fabric_properties`` (:data:`EXTERNAL_GROUPS`), supplied by
whoever resolves the ids (the session, from the application's library). Editing a library
fabric therefore marks the simulations and nesting built from it stale without changing
the design. An external group whose hash is not supplied is left out of the fingerprints,
so code that works without a library gets the same fingerprints as before the group
existed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

ArtifactStatus = Literal["current", "stale", "not built"]

#: Input groups of the design state (see :func:`input_groups`).
INPUT_GROUPS: tuple[str, ...] = (
    "geometry",
    "seam_allowance",
    "seam_construction",
    "manual_outlines",
    "labels",
    "grain",
    "row_zones",
    "tape_paths",
    "feature_locations",
    "tapes",
    "materials",
    "operating",
    "features",
    "meta",
    "rigging",
    "scale_variants",
    "parachute",
    "turning_vents",
    "vent_openings",
    "scoop",
    "shapes",
)

#: Input groups supplied from outside the project file (see module docstring).
EXTERNAL_GROUPS: tuple[str, ...] = ("fabric_properties",)


@dataclass(frozen=True)
class ArtifactSpec:
    """One node of the dependency graph.

    Attributes
    ----------
    name : str
        Artifact name.
    title : str
        Human-readable name.
    inputs : tuple of str
        Input groups read directly.
    upstream : tuple of str
        Artifacts this one is built from.
    """

    name: str
    title: str
    inputs: tuple[str, ...]
    upstream: tuple[str, ...] = ()


#: The artifact graph, in topological order.
ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("profile", "Meridian profile", ("geometry",)),
    ArtifactSpec(
        "patterns",
        "Flat patterns",
        (
            "geometry",
            "seam_allowance",
            "manual_outlines",
            "labels",
            "grain",
            "row_zones",
            "tape_paths",
            "feature_locations",
            "parachute",
            "scoop",
        ),
    ),
    ArtifactSpec(
        "assembly",
        "Assembly (seam graph)",
        (
            "geometry",
            "manual_outlines",
            "tape_paths",
            "feature_locations",
            "features",
            "tapes",
            "vent_openings",
        ),
    ),
    ArtifactSpec("rest_mesh", "Rest mesh", ("grain", "row_zones"), ("assembly",)),
    ArtifactSpec(
        "simulation",
        "Simulation",
        ("operating", "materials", "fabric_properties", "tapes", "seam_construction"),
        ("rest_mesh",),
    ),
    ArtifactSpec("flattening", "Flattening", ("geometry", "manual_outlines")),
    ArtifactSpec("nesting", "Nesting", ("materials", "fabric_properties"), ("patterns",)),
    ArtifactSpec(
        "export", "Export", ("meta", "rigging", "turning_vents", "scale_variants"), ("nesting",)
    ),
    ArtifactSpec("shapes", "Special shapes", ("geometry", "row_zones", "materials", "shapes")),
)

_BY_NAME: dict[str, ArtifactSpec] = {a.name: a for a in ARTIFACTS}


def artifact(name: str) -> ArtifactSpec:
    """The artifact called ``name`` (``KeyError`` if unknown)."""
    return _BY_NAME[name]


def canonical_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON form of ``value`` (sorted keys, compact)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()


def input_groups(
    design: Mapping[str, Any],
    patterns: Mapping[str, Any],
    shapes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Split a design state into its input groups.

    Parameters
    ----------
    design : mapping
        Design document as JSON data (``DesignDocument.model_dump(by_alias=True,
        mode="json")``); lengths in m, temperatures in K, pressures in Pa.
    patterns : mapping
        Pattern annotations as JSON data (``PatternSet.model_dump(mode="json")``).
    shapes : sequence of mapping
        Special shapes as JSON data (``ShapeSpec.model_dump(mode="json")``); m, deg.

    Returns
    -------
    dict of str to Any
        One JSON-ready slice per name in :data:`INPUT_GROUPS`.
    """
    gores = design.get("gores") or {}
    rows: Mapping[str, Mapping[str, Any]] = patterns.get("rows", {})

    def per_row(key: str) -> dict[str, Any]:
        # Default values are left out, so that creating a row's annotation entry (e.g. for
        # its seam allowance) does not look like a change of its grain or zone.
        return {
            letter: row[key]
            for letter, row in sorted(rows.items())
            if row.get(key) not in (None, [], 0.0)
        }

    seam_types = design.get("seam_types", [])
    return {
        "geometry": {
            "envelope_type": design.get("envelope_type"),
            "count": gores.get("count"),
            "points": gores.get("meridian_profile_control_points"),
            # A row's zone is a material choice (row_zones), not geometry.
            "rows": [
                {k: v for k, v in r.items() if k != "zone"} for r in gores.get("panel_rows") or []
            ]
            if gores.get("panel_rows") is not None
            else None,
            "mouth_diameter": gores.get("mouth_diameter"),
            "crown_ring": gores.get("crown_ring"),
            "parachute_hole_diameter": gores.get("parachute_hole_diameter"),
            "seal_overlap": gores.get("seal_overlap"),
            "special": design.get("special"),
            # Only a set loft enters, so designs without one keep their fingerprints.
            **({"loft": gores["loft"]} if gores.get("loft") is not None else {}),
        },
        "seam_allowance": {
            "seam_types": [s.get("allowance") for s in seam_types],
            "rows": per_row("seam_allowance"),
        },
        "seam_construction": [{k: v for k, v in s.items() if k != "allowance"} for s in seam_types],
        "manual_outlines": per_row("manual_outline"),
        "labels": {"text": per_row("label_text"), "notches": per_row("notches")},
        "grain": per_row("grain_angle_deg"),
        "row_zones": {
            "patterns": per_row("zone"),
            "design": {
                r["letter"]: r["zone"] for r in gores.get("panel_rows") or [] if r.get("zone")
            },
        },
        "tape_paths": per_row("tape_paths"),
        "feature_locations": per_row("feature_locations"),
        "tapes": design.get("tapes"),
        "materials": design.get("zones"),
        "operating": design.get("operating"),
        "features": design.get("features"),
        "meta": {k: v for k, v in (design.get("meta") or {}).items() if k == "name"},
        "rigging": design.get("rigging"),
        "scale_variants": design.get("scale_variants"),
        "parachute": design.get("parachute"),
        "turning_vents": design.get("turning_vents") or [],
        "scoop": design.get("scoop"),
        # Only vents simulated open change the sewn assembly.
        "vent_openings": [
            {k: v[k] for k in ("name", "seam", "rows")}
            for v in design.get("turning_vents") or []
            if v.get("simulate_open")
        ],
        "shapes": [dict(s) for s in shapes],
    }


def group_hashes(groups: Mapping[str, Any]) -> dict[str, str]:
    """Hash of every input group."""
    return {name: canonical_hash(value) for name, value in groups.items()}


def fingerprints(hashes: Mapping[str, str]) -> dict[str, str]:
    """Fingerprint of every artifact from the input-group hashes.

    Parameters
    ----------
    hashes : mapping of str to str
        Output of :func:`group_hashes`, optionally with hashes of
        :data:`EXTERNAL_GROUPS` added; an external group that is missing is left out.

    Returns
    -------
    dict of str to str
        Artifact name to fingerprint (hex SHA-256).
    """
    out: dict[str, str] = {}
    for spec in ARTIFACTS:
        parts = {
            "inputs": {
                g: hashes[g] for g in spec.inputs if g in hashes or g not in EXTERNAL_GROUPS
            },
            "upstream": {u: out[u] for u in spec.upstream},
        }
        out[spec.name] = canonical_hash(parts)
    return out


def artifact_inputs(name: str) -> set[str]:
    """Every input group ``name`` reads, directly or through its upstream artifacts."""
    spec = artifact(name)
    out = set(spec.inputs)
    for up in spec.upstream:
        out |= artifact_inputs(up)
    return out


def changed_groups(before: Mapping[str, str], after: Mapping[str, str]) -> set[str]:
    """Input groups whose hash differs between two states."""
    return {g for g in INPUT_GROUPS if before.get(g) != after.get(g)}


def downstream(artifacts: Iterable[str]) -> set[str]:
    """The given artifacts and everything built from them."""
    out = set(artifacts)
    for spec in ARTIFACTS:
        if any(u in out for u in spec.upstream):
            out.add(spec.name)
    return out


def invalidated_by(groups: Iterable[str]) -> set[str]:
    """Artifacts that a change of the given input groups makes stale.

    Parameters
    ----------
    groups : iterable of str
        Changed input groups.

    Returns
    -------
    set of str
        Every artifact that reads one of the groups, directly or through an upstream
        artifact.
    """
    changed = set(groups)
    unknown = changed - set(INPUT_GROUPS) - set(EXTERNAL_GROUPS)
    if unknown:
        raise KeyError(f"unknown input group(s): {', '.join(sorted(unknown))}")
    direct = {a.name for a in ARTIFACTS if changed.intersection(a.inputs)}
    return downstream(direct)


class ArtifactTracker:
    """Fingerprints at which artifacts were last built.

    Parameters
    ----------
    current : callable
        Returns the current fingerprints (:func:`fingerprints` of the design state).
    """

    def __init__(self, current: Callable[[], Mapping[str, str]]) -> None:
        self._current = current
        self._built: dict[str, str] = {}

    def mark_built(self, name: str, fingerprint: str | None = None) -> str:
        """Record that ``name`` was built now (or from the state with ``fingerprint``)."""
        artifact(name)
        value = fingerprint if fingerprint is not None else self._current()[name]
        self._built[name] = value
        return value

    def forget(self, name: str) -> None:
        """Mark ``name`` as not built."""
        self._built.pop(name, None)

    def clear(self) -> None:
        """Forget every artifact (e.g. after opening another project)."""
        self._built.clear()

    def built_fingerprint(self, name: str) -> str | None:
        """Fingerprint ``name`` was built with, or None."""
        return self._built.get(name)

    def status(self, name: str) -> ArtifactStatus:
        """``current``, ``stale`` or ``not built``."""
        built = self._built.get(name)
        if built is None:
            return "not built"
        return "current" if built == self._current()[name] else "stale"

    def statuses(self) -> dict[str, ArtifactStatus]:
        """Status of every artifact."""
        return {a.name: self.status(a.name) for a in ARTIFACTS}
