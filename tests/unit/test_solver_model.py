"""Unit tests: building a solver model from a build pack's as-sewn rest model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.assembly.pipeline import import_build_pack
from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.model import ModelError, OperatingConditions, model_from_rest_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GENERIC_FABRIC = MembraneMaterial.isotropic("fabric", 1.0e5, 0.3, areal_mass=0.065)
GENERIC_TAPE = TapeMaterial(
    "tape", MaterialValue(5.0e4, "N", "assumed"), MaterialValue(7.0e3, "N", "assumed")
)


def test_rest_model_adapter_maps_grain_zones_tapes_and_openings() -> None:
    built = import_build_pack(FIXTURES / "standard_gore" / "build-pack.yaml")
    assert built.rest_model is not None
    cond = OperatingConditions.hot_air(373.15)
    with pytest.raises(ModelError, match="no tape material"):
        model_from_rest_model(built.rest_model, {"default": GENERIC_FABRIC}, cond)
    tapes = {name: GENERIC_TAPE for name in ("webbing", "25 mm tape", "25 mm load tape")}
    model = model_from_rest_model(
        built.rest_model, {"default": GENERIC_FABRIC}, cond, tapes, closed_openings=("crown",)
    )
    mesh = built.rest_model.mesh
    assert model.name == "build pack"
    assert model.n_triangles == len(mesh.triangles)
    assert np.allclose(model.grain, mesh.instance_grain[mesh.tri_instance])
    assert [c.name for c in model.constraints] == ["mouth"]
    assert [c.name for c in model.closures] == ["crown"]
    assert {c.material.name for c in model.cables} == {GENERIC_TAPE.name}
    assert len(model.seams) == len(mesh.seam_edges)
    # Tape rest lengths are the flat (as-cut) seam lengths.
    vertical = next(c for c in model.cables if ":v:" in c.name)
    seam = next(s for s in built.assembly.graph.seams if s.seam_id == vertical.name)
    assert vertical.rest_lengths is not None
    assert vertical.rest_lengths.sum() == pytest.approx(
        built.assembly.graph.chain_length(seam.side_a), rel=1e-3
    )
    with pytest.raises(ModelError, match="unknown opening"):
        model_from_rest_model(
            built.rest_model, {"default": GENERIC_FABRIC}, cond, tapes, fixed_openings=("vent",)
        )
