"""Import a build pack, assemble it and produce the as-sewn rest model.

``import_build_pack`` runs the whole chain for one build-pack YAML file:

1. DXF import with the ``import`` mapping (:mod:`envelopelab.io.pattern_import`);
2. finished outlines (:mod:`envelopelab.assembly.pieces`);
3. instances and seam graph from the ``assembly`` section
   (:mod:`envelopelab.assembly.seam_graph`);
4. seam-length audit (:mod:`envelopelab.assembly.audit`);
5. Gmsh triangulation, virtual sewing and mesh validation
   (:mod:`envelopelab.assembly.mesh`);
6. initial 3D guess and rest model (:mod:`envelopelab.assembly.initial_shape`,
   :mod:`envelopelab.assembly.rest_model`).

``write_reports`` writes the import reports. The command-line entry point is
``envelopelab-import build-pack.yaml out/``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from envelopelab.assembly.audit import SeamAudit, audit_assembly
from envelopelab.assembly.initial_shape import initial_positions
from envelopelab.assembly.mesh import MeshReport, RestMesh, sew, validate_mesh
from envelopelab.assembly.pieces import FinishedPiece, build_finished_pieces
from envelopelab.assembly.rest_model import RestModel
from envelopelab.assembly.seam_graph import Assembly, build_assembly
from envelopelab.assembly.spec import AssemblySpec, MeshOptions, load_assembly_spec
from envelopelab.io.pattern_import import (
    ImportMapping,
    ImportWarning,
    PatternImport,
    import_patterns,
    load_mapping,
)


@dataclass
class BuildPackResult:
    """Everything produced from one build-pack YAML file.

    ``mesh``, ``mesh_report`` and ``rest_model`` are None when meshing was skipped.
    """

    config_path: Path
    mapping: ImportMapping
    spec: AssemblySpec
    imported: PatternImport
    pieces: dict[str, FinishedPiece]
    assembly: Assembly
    audit: SeamAudit
    mesh: RestMesh | None = None
    mesh_report: MeshReport | None = None
    rest_model: RestModel | None = None
    warnings: list[ImportWarning] = field(default_factory=list)

    @property
    def status(self) -> str:
        """``PASS`` when there are no errors and every mesh check passes, else ``FAIL``.

        A skipped mesh gives ``INCOMPLETE``: the result is not verified.
        """
        if any(w.severity == "error" for w in self.warnings) or self.audit.error_count:
            return "FAIL"
        if self.mesh_report is None:
            return "INCOMPLETE"
        return "PASS" if self.mesh_report.passed else "FAIL"


def _usage_warnings(pieces: dict[str, FinishedPiece], assembly: Assembly) -> list[ImportWarning]:
    used = Counter(inst.piece.piece_id for inst in assembly.instances.values())
    out: list[ImportWarning] = []
    for pid, piece in pieces.items():
        n = used.get(pid, 0)
        notes = f" ({piece.notes[0]})" if piece.notes else ""
        if n == 0:
            out.append(
                ImportWarning(
                    "assumption",
                    f"piece {pid} (quantity {piece.quantity}, {piece.kind}) is not used by the "
                    f"assembly and is not in the seam graph or mesh{notes}",
                    piece_id=pid,
                )
            )
        elif n != piece.quantity:
            out.append(
                ImportWarning(
                    "quantity",
                    f"piece {pid}: label quantity {piece.quantity}, assembled {n}{notes}",
                    piece_id=pid,
                )
            )
    return out


def import_build_pack(
    config_path: str | Path,
    *,
    mesh: bool = True,
    mesh_options: MeshOptions | None = None,
) -> BuildPackResult:
    """Run import, assembly, audit and (optionally) meshing for a build pack.

    Parameters
    ----------
    config_path : str or Path
        Build-pack YAML file with ``import`` and ``assembly`` sections.
    mesh : bool
        Triangulate, sew, validate and build the rest model.
    mesh_options : MeshOptions, optional
        Overrides ``assembly.mesh``.

    Returns
    -------
    BuildPackResult
        All intermediate and final results with the collected warnings.
    """
    path = Path(config_path)
    mapping = load_mapping(path)
    spec = load_assembly_spec(path)
    if mesh_options is not None:
        spec.mesh = mesh_options
    imported = import_patterns(mapping)
    pieces, piece_warnings = build_finished_pieces(imported)
    for pid, piece in pieces.items():
        notes = mapping.piece_options(pid).notes
        if notes:
            piece.notes.append(notes)
    assembly = build_assembly(spec, pieces)
    audit = audit_assembly(assembly)
    warnings = [*imported.warnings, *piece_warnings, *assembly.warnings]
    warnings += _usage_warnings(pieces, assembly)
    for row in audit.rows:
        if any("check the seam pairing" in f for f in row.findings):
            warnings.append(
                ImportWarning(
                    "ambiguous_seam",
                    f"seam {row.seam_id}: sides differ by {row.rel_mismatch * 100:.1f} %; the "
                    "pairing may be wrong",
                    severity="error",
                )
            )
    result = BuildPackResult(
        path, mapping, spec, imported, pieces, assembly, audit, warnings=warnings
    )
    if mesh:
        result.mesh = sew(assembly)
        result.mesh_report = validate_mesh(result.mesh, assembly)
        positions = initial_positions(result.mesh, assembly, result.warnings)
        result.rest_model = RestModel(
            result.mesh, positions, assembly, result.mesh_report, imported
        )
    return result


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: import a build pack and write the reports."""
    from envelopelab.assembly.reports import overall_status, write_reports

    parser = argparse.ArgumentParser(
        prog="envelopelab-import",
        description="Import DXF patterns, sew them virtually and write import reports.",
    )
    parser.add_argument("config", type=Path, help="build-pack YAML file")
    parser.add_argument("out", type=Path, help="output directory for reports")
    parser.add_argument("--no-mesh", action="store_true", help="skip meshing")
    parser.add_argument("--target-edge-mm", type=float, help="override target edge length")
    args = parser.parse_args(argv)
    options = None
    if args.target_edge_mm:
        options = load_assembly_spec(args.config).mesh.model_copy(
            update={"target_edge_length_mm": args.target_edge_mm}
        )
    result = import_build_pack(args.config, mesh=not args.no_mesh, mesh_options=options)
    paths = write_reports(result, args.out)
    print(f"status: {overall_status(result)}")
    print(f"reports: {paths['index']}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
