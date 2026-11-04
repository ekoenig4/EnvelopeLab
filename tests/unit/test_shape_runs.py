"""Special-shape simulations kept with a project (format version 3)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.metrics import appendage_metrics
from envelopelab.features.primitives import Dome, Placement, design_primitive, primitive_appendage
from envelopelab.features.scene import simulated_display
from envelopelab.project.model import (
    PROJECT_FORMAT_VERSION,
    ShapeRunRecord,
    dump_project,
    load_project_text,
)
from envelopelab.project.session import ProjectSession
from envelopelab.project.shape_runs import (
    AUTO_MESH_MAX,
    AUTO_MESH_MIN,
    auto_mesh_size,
    display_arrays,
    display_from_arrays,
    shape_run_record,
)
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import OperatingConditions
from envelopelab.solvers.simulation import from_preview
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.35 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture(scope="module")
def solved() -> tuple[ShapeRunRecord, dict[str, np.ndarray]]:
    design = design_primitive(
        Dome("pod", Placement(2, EQUATOR), 0.6, 0.4, gores=6), SPHERE, feed_hole_radius=0.15
    )
    am = build_appendage(
        primitive_appendage(design, 0.25, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    result = from_preview(am.model, solve(am.model))
    metrics = appendage_metrics(am, result)
    record, arrays = shape_run_record("pod", "key-1", design, am, result, metrics, 0.25, "hash")
    # The display arrays are the solved skin split into its pieces.
    shown = simulated_display(design, am, result)
    assert np.allclose(arrays["points"], shown.points)
    return record, arrays


def test_auto_mesh_size_aims_for_forty_rim_elements() -> None:
    small = design_primitive(Dome("a", Placement(2, EQUATOR), 0.3, 0.2), SPHERE)
    mid = design_primitive(Dome("b", Placement(2, EQUATOR), 1.0, 0.6), SPHERE)
    big = design_primitive(Dome("c", Placement(2, EQUATOR), 2.5, 1.0), SPHERE)
    assert (AUTO_MESH_MIN, AUTO_MESH_MAX) == (0.10, 0.30)
    assert auto_mesh_size(small) == AUTO_MESH_MIN  # 1.9 m rim
    assert auto_mesh_size(mid) == pytest.approx(round(mid.footprint_length / 40, 3))
    assert AUTO_MESH_MIN < auto_mesh_size(mid) < AUTO_MESH_MAX
    assert auto_mesh_size(big) == AUTO_MESH_MAX  # 15.7 m rim / 40 = 0.39 m


def test_every_shape_result_warns_that_its_peaks_depend_on_the_mesh(
    solved: tuple[ShapeRunRecord, dict[str, np.ndarray]],
) -> None:
    record, _ = solved
    warning = [f for f in record.findings if f.code == "peak_values_mesh_dependent"]
    assert len(warning) == 1 and warning[0].severity == "warning"


def test_record_carries_the_solve_and_its_provenance(
    solved: tuple[ShapeRunRecord, dict[str, np.ndarray]],
) -> None:
    record, _ = solved
    assert record.shape == "pod" and record.simulation_key == "key-1"
    assert record.solver == "envelopelab-preview" and record.pieces == 6
    assert record.mesh_target_mm == 250.0
    assert record.iterations > 0 and record.n_nodes > 0 and record.run_time > 0
    assert set(record.metrics) >= {"projected_height_m", "chamber_pressure_pa"}
    assert "skin" in record.fos
    assert "assumed" in record.material_sources
    assert record.manifest  # git commit, versions, seed
    if not record.converged:
        assert any(f.severity == "error" for f in record.findings)


def test_display_arrays_round_trip(solved: tuple[ShapeRunRecord, dict[str, np.ndarray]]) -> None:
    _, arrays = solved
    shown = display_from_arrays(arrays)
    again = display_arrays(shown)
    # The display's own arrays (the run also keeps the skin results, skin_*).
    for key, value in again.items():
        assert np.array_equal(arrays[key], value), key
    assert shown.pieces == 6 and len(shown.seams) == 6


def test_kept_shape_run_survives_save_and_reopen(
    tmp_path: Path, solved: tuple[ShapeRunRecord, dict[str, np.ndarray]]
) -> None:
    record, arrays = solved
    s = ProjectSession.open(FIXTURE)
    s.add_shape_run(record, arrays)
    # A newer simulation of the same shape replaces the older one.
    newer = record.model_copy(update={"run_id": record.run_id + "-2"})
    s.add_shape_run(newer, arrays)
    assert [r.run_id for r in s.project.shape_runs] == [newer.run_id]
    path = s.save(tmp_path / "p.elproj")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format_version"] == PROJECT_FORMAT_VERSION == 3
    assert raw["shape_runs"][0]["result_file"].endswith(f"{newer.run_id}.npz")
    reopened = ProjectSession.open(path)
    kept = reopened.shape_run("pod")
    assert kept is not None and kept.metrics == record.metrics
    loaded = reopened.run_arrays(kept.run_id)
    assert loaded is not None and np.array_equal(loaded["triangles"], arrays["triangles"])
    assert reopened.shape_run("other") is None


def test_version_2_file_reads_without_shape_runs() -> None:
    s = ProjectSession.open(FIXTURE)
    data = json.loads(dump_project(s.project))
    data["format_version"] = 2
    del data["shape_runs"]
    project = load_project_text(json.dumps(data))
    assert project.format_version == 3 and project.shape_runs == []
    with pytest.raises(ValueError, match="version"):
        load_project_text(json.dumps({**data, "format_version": 4}))


def test_shape_runs_keep_skin_results_for_colour_maps(
    solved: tuple[ShapeRunRecord, dict[str, np.ndarray]],
) -> None:
    from envelopelab.project.run_fields import (
        FIELD_LABELS,
        shape_missing_fields,
        shape_run_fields,
    )

    record, arrays = solved
    k = len(arrays["triangles"])
    assert arrays["skin_principal"].shape == (k, 2)
    assert arrays["skin_strength"].shape == (k, 2)
    assert arrays["skin_fabric_resultants"].shape == (k, 3)
    assert arrays["skin_wrinkle_state"].shape == (k,)
    assert arrays["skin_initial_points"].shape == arrays["points"].shape
    fields = shape_run_fields(arrays)
    assert set(fields) == set(FIELD_LABELS) - {"deviation"}
    # The shape summary's skin factor is the conservative min(N_ult) / N1 bound, so it is
    # never above the lowest warp or weft factor of any skin triangle.
    low = min(float(fields["fos_warp"].values.min()), float(fields["fos_weft"].values.min()))
    assert record.fos["skin"] <= low * (1.0 + 1e-12)
    assert shape_missing_fields(arrays) == {}
    old = {k: v for k, v in arrays.items() if not k.startswith("skin_")}
    assert "run it again" in shape_missing_fields(old)["fos_warp"]


def test_shape_deviation_from_its_designed_skin(
    solved: tuple[ShapeRunRecord, dict[str, np.ndarray]],
) -> None:
    from envelopelab.features.scene import designed_display
    from envelopelab.project.run_fields import shape_run_fields

    _, arrays = solved
    design = design_primitive(
        Dome("pod", Placement(2, EQUATOR), 0.6, 0.4, gores=6), SPHERE, feed_hole_radius=0.15
    )
    shown = designed_display(design)
    dev = shape_run_fields(arrays, shown.points, shown.triangles)["deviation"].values
    assert dev.shape == (len(arrays["points"]),) and np.isfinite(dev).all()
    # An inflated dome skin bulges out of its design somewhere, within a fraction of its
    # 0.4 m height.
    assert dev.max() > 0.0 and np.abs(dev).max() < 0.2
