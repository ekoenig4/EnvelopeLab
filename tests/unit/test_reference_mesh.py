"""Reference-mesh import, registration, signed distance and volume notation."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import pytest

from envelopelab.io.reference_mesh import (
    CUBIC_FOOT,
    ReferenceMesh,
    ReferenceMeshError,
    deviation_stats,
    icp,
    open3d_available,
    parse_volume_notation,
    read_mesh,
    signed_distance,
    title_text,
    write_ply,
    write_stl,
)
from envelopelab.solvers.results import write_obj
from envelopelab.validation.meshes import sphere


def _mesh() -> ReferenceMesh:
    s = sphere(2.0, 12)
    return ReferenceMesh(s.positions, s.triangles, "sphere")


def test_obj_stl_ply_round_trips(tmp_path: Path) -> None:
    m = _mesh()
    for path in (
        write_obj(tmp_path / "m.obj", m.vertices, m.triangles),
        write_stl(tmp_path / "m.stl", m),
        write_ply(tmp_path / "m.ply", m),
    ):
        back = read_mesh(path)
        assert len(back.triangles) == len(m.triangles), path
        assert back.volume == pytest.approx(m.volume, rel=1e-5), path
    scaled = read_mesh(tmp_path / "m.ply", scale=1e-3)
    assert scaled.volume == pytest.approx(m.volume * 1e-9, rel=1e-5)


def test_binary_ply_and_ascii_stl(tmp_path: Path) -> None:
    m = _mesh()
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(m.vertices)}\nproperty float x\nproperty float y\nproperty float z\n"
        f"element face {len(m.triangles)}\nproperty list uchar int vertex_indices\nend_header\n"
    ).encode()
    body = m.vertices.astype("<f4").tobytes()
    body += b"".join(struct.pack("<Biii", 3, *map(int, t)) for t in m.triangles)
    (tmp_path / "b.ply").write_bytes(header + body)
    assert read_mesh(tmp_path / "b.ply").volume == pytest.approx(m.volume, rel=1e-5)
    lines = ["solid s"]
    for t in m.triangles:
        lines += ["facet normal 0 0 0", "outer loop"]
        lines += [f"vertex {x} {y} {z}" for x, y, z in m.vertices[t]]
        lines += ["endloop", "endfacet"]
    (tmp_path / "a.stl").write_text("\n".join(lines + ["endsolid s"]), encoding="ascii")
    assert read_mesh(tmp_path / "a.stl").volume == pytest.approx(m.volume, rel=1e-9)
    (tmp_path / "x.dxf").write_text("0\nEOF\n", encoding="ascii")
    with pytest.raises(ReferenceMeshError):
        read_mesh(tmp_path / "x.dxf")


def test_signed_distance_on_a_sphere() -> None:
    m = _mesh()
    pts = np.array([[0.0, 0.0, 2.5], [0.0, 0.0, 1.5], [3.0, 0.0, 0.0]])
    d = signed_distance(pts, m)
    # Faceted sphere: within the chord sagitta of the analytic value.
    assert d == pytest.approx([0.5, -0.5, 1.0], abs=0.02)
    stats = deviation_stats(d)
    assert stats.max_outside == pytest.approx(1.0, abs=0.02)
    assert stats.max_inside == pytest.approx(-0.5, abs=0.02)


def test_scipy_icp_recovers_a_known_rigid_motion() -> None:
    """An ellipsoid (no rotational symmetry) moved by 5 deg and 0.2 m is registered back."""
    m = _mesh()
    ref = ReferenceMesh(m.vertices * np.array([1.0, 0.7, 0.5]), m.triangles)
    a = math.radians(5.0)
    rot = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1.0]])
    moved = ref.vertices @ rot.T + np.array([0.2, -0.1, 0.05])
    reg = icp(moved, ref, threshold=1.0, max_iterations=200, backend="scipy")
    assert reg.backend.startswith("scipy")
    assert reg.rmse < 5e-3
    assert np.allclose(reg.apply(moved), ref.vertices, atol=2e-2)


@pytest.mark.skipif(not open3d_available(), reason="Open3D (optional) not installed")
def test_open3d_icp_recovers_a_known_rigid_motion() -> None:
    m = _mesh()
    ref = ReferenceMesh(m.vertices * np.array([1.0, 0.7, 0.5]), m.triangles)
    moved = ref.vertices + np.array([0.1, 0.0, 0.0])
    reg = icp(moved, ref, threshold=0.5, backend="open3d")
    assert reg.backend.startswith("open3d")
    assert np.allclose(reg.apply(moved), ref.vertices, atol=5e-2)


def test_volume_notation() -> None:
    assert parse_volume_notation("“Alien” Special Shape — 2,550 m³") == pytest.approx(2550.0)
    assert parse_volume_notation("volume 2610 m3 at 25 C") == pytest.approx(2610.0)
    assert parse_volume_notation("a 90,000 cu ft envelope") == pytest.approx(90000 * CUBIC_FOOT)
    assert parse_volume_notation("no volume here") is None


def test_title_text_reads_html_headings(tmp_path: Path) -> None:
    page = tmp_path / "p.html"
    page.write_text(
        "<html><title>Concept</title><body><b>Thing — 1,234 m³</b></body></html>", encoding="utf-8"
    )
    text = title_text(page)
    assert "Concept" in text and parse_volume_notation(text) == pytest.approx(1234.0)
