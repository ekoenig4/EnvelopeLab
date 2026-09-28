"""Render docs/formats/pattern-import-mapping.md from the mapping and assembly models.

The field tables are generated from the Pydantic models (names, types, defaults and
descriptions), so the documented format cannot drift from the code.
``scripts/generate_pattern_mapping_docs.py`` writes the page; a test fails when it is
stale.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from envelopelab.assembly.spec import (
    AssemblySpec,
    BoundarySpec,
    EdgeRef,
    FeatureSelector,
    InitialShapeSpec,
    InstanceFeature,
    InstanceOverride,
    InstanceSelect,
    MeshOptions,
    OpeningSpec,
    OpenSeamSpec,
    PartSpec,
    RingBoundaryRef,
    RingSpec,
    SeamProperties,
    SeamSpec,
)
from envelopelab.io.pattern_import import (
    ImportMapping,
    LabelRule,
    LayerMap,
    PieceOptions,
    SourceSpec,
)

IMPORT_MODELS: tuple[type[BaseModel], ...] = (
    ImportMapping,
    LayerMap,
    LabelRule,
    SourceSpec,
    PieceOptions,
)
ASSEMBLY_MODELS: tuple[type[BaseModel], ...] = (
    AssemblySpec,
    RingSpec,
    BoundarySpec,
    OpenSeamSpec,
    SeamProperties,
    SeamSpec,
    EdgeRef,
    RingBoundaryRef,
    InstanceOverride,
    InstanceSelect,
    InstanceFeature,
    FeatureSelector,
    PartSpec,
    OpeningSpec,
    MeshOptions,
    InitialShapeSpec,
)


def _type_name(annotation: Any) -> str:
    text = str(annotation)
    text = re.sub(r"<class '([^']+)'>", r"\1", text)
    text = re.sub(r"\b(?:typing|builtins|pathlib)\.", "", text)
    text = re.sub(r"\benvelopelab(?:\.\w+)+\.(\w+)", r"\1", text)
    text = text.replace("NoneType", "None")
    if text.startswith("Optional[") and text.endswith("]"):
        text = f"{text[len('Optional[') : -1]} | None"
    return text


def _default(field: Any) -> str:
    if field.is_required():
        return "**required**"
    if field.default_factory is not None:
        try:
            value = field.default_factory()
        except TypeError:
            return "(computed)"
        if isinstance(value, BaseModel):
            return "defaults"
        return f"`{value!r}`"
    if field.default is PydanticUndefined:
        return ""
    return f"`{field.default!r}`"


def model_table(model: type[BaseModel]) -> str:
    """Markdown table of a model's fields.

    Parameters
    ----------
    model : type of BaseModel
        Pydantic model.

    Returns
    -------
    str
        Markdown heading, docstring summary and field table.
    """
    doc = (model.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ")
    lines = [f"### `{model.__name__}`", "", doc, "", "| Field | Type | Default | Description |"]
    lines.append("|---|---|---|---|")
    for name, field in model.model_fields.items():
        description = (field.description or "").replace("|", "\\|")
        type_name = _type_name(field.annotation).replace("|", "\\|")
        lines.append(f"| `{name}` | `{type_name}` | {_default(field)} | {description} |")
    return "\n".join(lines) + "\n"


INTRO = """# Pattern import mapping (build-pack YAML)

_The field tables on this page are generated from the Pydantic models in
`envelopelab.io.pattern_import` and `envelopelab.assembly.spec` by
`scripts/generate_pattern_mapping_docs.py`; do not edit by hand._

Every build pack gets one YAML file, stored next to its DXF files, with two sections:

* `import` - how to read the DXF files: which layers carry cut lines, sew lines,
  dimensions, feature marks, tape lines, match marks, notches, grain arrows and labels;
  how labels are parsed (regular expressions); units, seam allowance and per-piece
  overrides.
* `assembly` - how the imported pieces are sewn: gore rings, instance overrides (feature
  openings, embedded marks, material zones), parts, explicit seams with metadata
  (including designed ease), declared openings, mesh settings and the initial-shape
  method.

Nothing about a particular design is built into EnvelopeLab; everything design-specific
belongs in this file. Lengths are in **mm** in the file and converted to SI (m) on load.
`mapping_version` is recorded in the provenance of every imported entity and in the rest
model, so give the file a new version whenever you change it.

## Conventions

* **Pattern frame.** Patterns are read in a frame with +y pointing up the envelope (towards
  the crown), seen from the outside of the fabric. Use `up_axis` and `pattern_face` when a
  pack is drawn differently. Outlines are normalised to counter-clockwise order.
* **Pieces.** Every closed outline on a cut layer is a piece. A cut outline inside another
  one without its own label is a hole of that piece. Sew lines, labels and marks belong to
  the innermost cut outline that contains them.
* **Labels.** Each text entity inside a piece is matched against the `labels` rules in
  order; the first match names the piece. Named groups: `panel` (id), `quantity` (cut
  count) and `mirror` (any match marks the piece as also cut mirrored); `piece_id` is a
  template over the named groups (default `"{panel}"`).
* **Cut and sew lines.** If a piece has a sew line, it is the finished outline. Otherwise
  the cut line is inset by the seam allowance (`seam_allowance_mm`, overridable per file
  and per piece). A zero allowance means the cut line is the finished edge.
* **Flattening.** Circles, arcs, bulges and splines are flattened with a maximum chord
  error of `flatten_tolerance_mm`; a closed curve is shortened by about 2.1 times that
  value (0.1 mm at the default 0.05 mm).
* **Edges.** A finished outline is split into edges at corners (turning angle above
  `corner_angle_deg`, measured over a 20 mm arc window). Four-corner pieces get the edges
  `bottom`, `right`, `top`, `left`; others `e0`, `e1`, ... from the corner nearest the
  bottom-left; outlines without corners have a single edge `loop`.
* **Instances.** Ring panels are named `<ring>/<row>@<gore>` (for example
  `envelope/N@4`); parts use their `name`. Edge references are
  `{instance: ..., edge: ...}` or `{instance: ..., mark: ...}` for embedded marks and
  instance openings.
* **Orientation.** `reversed` (default) means the start of side A is sewn to the end of
  side B, as for two panels lying side by side. `same` is used when an appendage is sewn
  onto a marked line or hole rim, whose loop runs counter-clockwise.
* **Designed ease** (`designed_ease_mm`) is the intended excess length of side B over side
  A. It is not reported as a seam error and is passed to the structural simulation.
* **Attachment seams** (`attachment: true`) sew an appendage onto a line marked on a
  panel surface. The mesh edges along that line have three triangles by design and are
  reported separately from non-manifold edges.
"""


def render_mapping_docs(example: str, example_name: str) -> str:
    """Render the full format page.

    Parameters
    ----------
    example : str
        YAML text of a complete example build-pack file.
    example_name : str
        Path of the example shown in the caption.

    Returns
    -------
    str
        Markdown page.
    """
    parts = [INTRO, "## `import` section\n"]
    parts += [model_table(m) for m in IMPORT_MODELS]
    parts.append("## `assembly` section\n")
    parts += [model_table(m) for m in ASSEMBLY_MODELS]
    parts.append(
        f"## Complete example\n\n`{example_name}` (generic special-shape fixture):\n\n"
        f"```yaml\n{example.rstrip()}\n```\n"
    )
    return "\n".join(parts)
