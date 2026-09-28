"""As-sewn rest model: the input handed to the inflation solver.

The rest model is the sewn mesh with, for every triangle, its flat rest coordinates (the
geometry that will actually be cut and sewn), panel id, material zone, grain direction
and source pattern id; seam and tape paths for cable elements; designed ease per seam;
the declared openings; an initial 3D guess; and reproducibility metadata (git commit,
dependency versions, design content hash, mapping version, mesh settings, random seed).

It is **not** a solved shape: the metadata says so explicitly and the initial positions
are only a starting point for the solver.

File format ``envelopelab.rest-model`` version 1 is JSON, lengths in m, areas in m^2.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from envelopelab.assembly.mesh import MeshReport, RestMesh
from envelopelab.assembly.seam_graph import Assembly
from envelopelab.geometry.polygon import FloatArray
from envelopelab.io.pattern_import import PatternImport

REST_MODEL_FORMAT = "envelopelab.rest-model"
REST_MODEL_VERSION = 1
_DEPENDENCIES = ("envelopelab", "numpy", "scipy", "ezdxf", "gmsh", "pydantic", "PyYAML")


def git_commit() -> str:
    """Git commit of the working tree the package runs from, or ``"unknown"``."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def dependency_versions() -> dict[str, str]:
    """Installed versions of the packages that influence the result."""
    out = {"python": platform.python_version()}
    for name in _DEPENDENCIES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


@dataclass
class RestModel:
    """In-memory rest model (see module docstring)."""

    mesh: RestMesh
    positions: FloatArray
    assembly: Assembly
    report: MeshReport
    imported: PatternImport

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary following ``envelopelab.rest-model`` v1."""
        mesh = self.mesh
        graph = self.assembly.graph
        seams = []
        for seam in graph.seams:
            if seam.seam_id not in mesh.seam_edges:
                continue
            pairs = mesh.seam_pairs.get(seam.seam_id)
            seams.append(
                {
                    "id": seam.seam_id,
                    "type": seam.seam_type,
                    "attachment": seam.attachment,
                    "edges": mesh.seam_edges[seam.seam_id].tolist(),
                    "length_a_m": graph.chain_length(seam.side_a),
                    "length_b_m": graph.chain_length(seam.side_b) if seam.side_b else None,
                    "designed_ease_m": seam.props.designed_ease_m,
                    "load_tape": seam.props.load_tape,
                    "stitch": seam.props.stitch,
                    "stitch_rows": seam.props.stitch_rows,
                    "allowance_a_m": seam.props.side_allowance_m("a"),
                    "allowance_b_m": seam.props.side_allowance_m("b"),
                    "construction_order": seam.props.construction_order,
                    "orientation": seam.props.orientation,
                    "node_fraction_a": None if pairs is None else pairs[:, 1].round(9).tolist(),
                }
            )
        grains = [
            None if np.isnan(g[0]) else [float(g[0]), float(g[1])] for g in mesh.instance_grain
        ]
        return {
            "format": REST_MODEL_FORMAT,
            "format_version": REST_MODEL_VERSION,
            "status": "as-sewn rest model; initial_positions are a starting guess, not an "
            "inflated or solved shape",
            "metadata": {
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_commit": git_commit(),
                "dependencies": dependency_versions(),
                "design_content_hash": self.imported.content_hash,
                "mapping_version": self.imported.mapping_version,
                "sources": [s.as_dict() for s in self.imported.sources],
                "mesh_options": mesh.options.model_dump(),
                "random_seed": 1,
                "gmsh_runs": mesh.gmsh_runs,
                "run_time_s": round(mesh.run_time, 3),
                "initial_shape": self.assembly.spec.initial_shape.model_dump(),
                "validation": self.report.as_dict(),
            },
            "units": {"length": "m", "area": "m^2"},
            "instances": [
                {
                    "id": iid,
                    "piece": piece,
                    "material_zone": zone,
                    "grain": grain,
                    "source_pattern_id": source,
                }
                for iid, piece, zone, grain, source in zip(
                    mesh.instance_ids,
                    mesh.instance_pieces,
                    mesh.instance_zones,
                    grains,
                    mesh.instance_sources,
                    strict=True,
                )
            ],
            "nodes": {"initial_positions": np.round(self.positions, 9).tolist()},
            "triangles": {
                "nodes": mesh.triangles.tolist(),
                "instance": mesh.tri_instance.tolist(),
                "rest_uv": np.round(mesh.rest_uv, 9).tolist(),
            },
            "seams": seams,
            "tape_paths": {k: v.tolist() for k, v in mesh.tape_edges.items()},
            "openings": {k: v.tolist() for k, v in mesh.openings.items()},
        }


def save_rest_model(model: RestModel, path: str | Path) -> Path:
    """Write a rest model as JSON.

    Parameters
    ----------
    model : RestModel
        Model to write.
    path : str or Path
        Output file.

    Returns
    -------
    Path
        The written file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model.to_dict(), separators=(",", ":")), encoding="utf-8")
    return target


def load_rest_model(path: str | Path) -> dict[str, Any]:
    """Read a rest model written by :func:`save_rest_model`.

    Parameters
    ----------
    path : str or Path
        JSON file.

    Returns
    -------
    dict
        The parsed document (format and version checked).
    """
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != REST_MODEL_FORMAT:
        raise ValueError(f"{path}: not an {REST_MODEL_FORMAT} file")
    if data.get("format_version") != REST_MODEL_VERSION:
        raise ValueError(f"{path}: unsupported rest-model version {data.get('format_version')}")
    return data
