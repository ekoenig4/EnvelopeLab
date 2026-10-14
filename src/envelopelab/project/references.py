"""Reference profiles: other envelopes' outlines drawn over the design for comparison.

A reference is made from a shape file, from another project, or from a snapshot of the
design as it is now. It stores its own outline (:class:`~envelopelab.project.model.
ReferenceProfile`), sampled evenly along the tape at :data:`REFERENCE_SAMPLES` points, so
it stays as it was when it was made. It is kept in the project file, not in the design:
it changes nothing in the design or its results.

The comparison reported for a reference is the symmetric Hausdorff distance between its
outline (shifted by its ``z_offset``) and the design's profile, m
(:func:`~envelopelab.geometry.profile_editing.profile_deviation`).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import MeridianProfile
from envelopelab.geometry.profile_editing import profile_deviation
from envelopelab.project.gore_design import design_profile
from envelopelab.project.model import ReferenceProfile, utc_now
from envelopelab.project.session import ProjectSession

#: Points of a stored reference outline (evenly spaced along the tape).
REFERENCE_SAMPLES = 401
#: File suffixes read as shape files; anything else is opened as a project.
SHAPE_FILE_SUFFIXES = (".yaml", ".yml")


def reference_from_design(design: DesignDocument, name: str, source: str) -> ReferenceProfile:
    """A reference holding the design's profile as it is now.

    Parameters
    ----------
    design : DesignDocument
        A standard-gore design, m.
    name, source : str
        Label on the canvas, and where the outline came from.

    Returns
    -------
    ReferenceProfile
        :data:`REFERENCE_SAMPLES` points evenly spaced along the tape, m.

    Raises
    ------
    ValueError
        For a special-shape design (no meridian profile).
    """
    profile = design_profile(design)
    s = np.linspace(0.0, profile.meridian_length, REFERENCE_SAMPLES)
    r = np.clip(profile.radius_at(s), 0.0, None)
    return ReferenceProfile(
        name=name,
        source=source,
        r=[float(v) for v in r],
        z=[float(v) for v in profile.height_at(s)],
    )


def reference_from_file(path: str | Path, name: str | None = None) -> ReferenceProfile:
    """A reference from a shape file (``.yaml``/``.yml``) or a project file.

    Parameters
    ----------
    path : str or Path
        File to read.
    name : str, optional
        Label (default: the file name without its suffix).

    Raises
    ------
    ValueError
        When the file holds no standard-gore profile (the loaders' own errors pass
        through for unreadable files).
    """
    file = Path(path)
    if file.suffix.lower() in SHAPE_FILE_SUFFIXES:
        from envelopelab.io.shape_file import load_shape_file

        design = load_shape_file(file).design()
    else:
        design = ProjectSession.open(file).design
    if design.gores is None:
        raise ValueError(f"{file.name} is not a standard-gore design: it has no profile")
    return reference_from_design(design, name or file.stem, str(file))


def snapshot_reference(design: DesignDocument, name: str | None = None) -> ReferenceProfile:
    """A reference holding the current profile, labelled with the time it was taken."""
    now = utc_now()
    label = name or f"snapshot {now:%H:%M}"
    return reference_from_design(
        design, label, f"snapshot of {design.meta.name} at {now:%Y-%m-%d %H:%M} UTC"
    )


def reference_profile(reference: ReferenceProfile) -> MeridianProfile:
    """The reference's outline as a profile, shifted by its ``z_offset``, m."""
    r = np.asarray(reference.r, dtype=np.float64)
    z = np.asarray(reference.z, dtype=np.float64) + reference.z_offset
    keep = np.concatenate(([True], np.hypot(np.diff(r), np.diff(z)) > 0.0))
    return MeridianProfile.from_points(r[keep], z[keep])


def reference_deviation(reference: ReferenceProfile, design: DesignDocument) -> float:
    """Largest distance between the reference (with its offset) and the design's
    profile, m (symmetric Hausdorff distance)."""
    return profile_deviation(reference_profile(reference), design_profile(design))


def unique_name(name: str, taken: Sequence[str]) -> str:
    """``name``, or ``name (2)``, ``name (3)``, ... when it is already used."""
    if name not in taken:
        return name
    k = 2
    while f"{name} ({k})" in taken:
        k += 1
    return f"{name} ({k})"


def add_reference(session: ProjectSession, reference: ReferenceProfile) -> ReferenceProfile:
    """Add a reference to the project (its name made unique); returns the one added.

    References are editor aids saved with the project, like the constraint locks: they
    are not design edits and do not enter the undo history.
    """
    taken = [ref.name for ref in session.project.references]
    added = reference.model_copy(update={"name": unique_name(reference.name, taken)})
    session.project.references = [*session.project.references, added]
    session.mark_aux_dirty()
    return added


def remove_reference(session: ProjectSession, index: int) -> None:
    """Remove reference ``index``."""
    refs = list(session.project.references)
    if not 0 <= index < len(refs):
        raise IndexError(f"no reference {index}")
    del refs[index]
    session.project.references = refs
    session.mark_aux_dirty()


def update_reference(
    session: ProjectSession,
    index: int,
    name: str | None = None,
    visible: bool | None = None,
    z_offset: float | None = None,
) -> ReferenceProfile:
    """Rename, show or hide, or shift (``z_offset``, m) reference ``index``.

    Raises
    ------
    ValueError
        For an empty or taken name, or a non-finite offset.
    """
    refs = list(session.project.references)
    if not 0 <= index < len(refs):
        raise IndexError(f"no reference {index}")
    update: dict[str, object] = {}
    if name is not None:
        name = name.strip()
        others = [ref.name for k, ref in enumerate(refs) if k != index]
        if not name or name in others:
            raise ValueError(f"reference name {name!r} is empty or already used")
        update["name"] = name
    if visible is not None:
        update["visible"] = bool(visible)
    if z_offset is not None:
        if not np.isfinite(z_offset):
            raise ValueError("the offset must be a finite length")
        update["z_offset"] = float(z_offset)
    refs[index] = ReferenceProfile.model_validate({**refs[index].model_dump(), **update})
    session.project.references = refs
    session.mark_aux_dirty()
    return refs[index]
