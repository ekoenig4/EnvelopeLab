# ADR-0003: Pattern import and virtual sewing

- Status: Accepted
- Date: 2026-09-28

## Context
The simulation must start from the flat patterns that will be sewn, not from a designer's
3D reference. Build packs arrive as DXF files with pack-specific layer names and label
formats, sometimes with sew lines and sometimes with cut lines only. Panels must be
triangulated with seam-conforming boundaries and joined into one topological mesh, and
the result handed to the inflation solver with full provenance.

## Decision
- Read DXF with **ezdxf** (MIT): pure Python, supports every entity used by pattern
  software, including bulges, splines and block references.
- Triangulate with **Gmsh** (GPL-2.0-or-later with linking exceptions, compatible with
  GPL-3.0) through its Python API: robust constrained 2D meshing with prescribed boundary
  nodes, holes, embedded lines and size fields. On Linux the Gmsh wheel needs the system
  libraries `libGLU`, `libXcursor`, `libXft` and `libXinerama`; CI installs them.
- Describe each build pack in one **YAML** file (**PyYAML**, MIT) with an `import` section
  (layer roles, label regular expressions, units, allowances) and an `assembly` section
  (rings, instance overrides, parts, seams with metadata and designed ease, openings,
  mesh and initial-shape settings). The format is versioned (`format_version: 1`) and
  documented in `docs/formats/pattern-import-mapping.md`, generated from the models.
- Polygon offsets, validation and corner detection are implemented in
  `envelopelab.geometry.polygon` rather than adding a geometry-kernel dependency.
- The as-sewn rest model is written as JSON, format `envelopelab.rest-model` version 1.

## Consequences
- Supporting a new pack means writing a YAML file, not code; the Alien regression fixture
  checks that a real pack assembles without special cases.
- Gmsh's interior node placement may differ between versions and platforms, so tests and
  generated validation pages rely only on discretisation-independent quantities
  (boundary loops, topology, seam lengths, rest area).
- Changes to the YAML or rest-model formats need a new format version, a migration and an
  ADR.
