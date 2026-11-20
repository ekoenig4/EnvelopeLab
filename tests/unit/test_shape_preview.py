"""Fast drawing previews of special shapes (preview_primitive, ADR-0051)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.features.primitives import PrimitiveError, preview_primitive
from envelopelab.features.scene import designed_display
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import (
    default_shape,
    envelope_surface,
    shape_design,
    shape_preview,
    to_primitive,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)
SURFACE = envelope_surface(SESSION.design, SESSION.patterns)


@pytest.mark.parametrize("kind", ["dome", "tube", "revolved"])
def test_the_preview_skin_is_the_designed_skin(kind: str) -> None:
    spec = default_shape(kind, SESSION.design, "X")  # type: ignore[arg-type]
    preview = shape_preview(spec, SURFACE)
    full = shape_design(spec, SURFACE)
    assert preview.preview and not full.preview
    # Drawing only: nothing that a result is made of.
    assert preview.pieces == [] and preview.checks == [] and preview.marks == []
    np.testing.assert_allclose(preview.base_point, full.base_point, atol=1e-12)
    np.testing.assert_allclose(preview.axis, full.axis, atol=1e-12)
    a = designed_display(preview, rows=14, per_piece=3)
    b = designed_display(full, rows=14, per_piece=3)
    np.testing.assert_array_equal(a.triangles, b.triangles)
    np.testing.assert_array_equal(a.piece, b.piece)
    # Fewer footprint samples move the skin by well under the geometry tolerance (1 mm).
    assert float(np.abs(a.points - b.points).max()) < 1e-4


def test_a_shape_that_does_not_fit_has_no_preview() -> None:
    spec = default_shape("dome", SESSION.design, "X")
    bad = spec.model_copy(
        update={"placement": spec.placement.model_copy(update={"tape_position": -1.0})}
    )
    with pytest.raises(PrimitiveError):
        preview_primitive(to_primitive(bad), SURFACE)
