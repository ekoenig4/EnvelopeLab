"""What kind of value each design field holds, and what a new one looks like.

Generic editors (the Properties panel) build their widgets from the design schema instead
of guessing from the current value: a field that is ``None`` now may hold a number, a
choice or a whole section. :func:`field_info` reads the type of any field of
:class:`~envelopelab.design.model.DesignDocument` from its path in the JSON data, and
:func:`new_value` gives the value for adding an optional section or a list entry. The
values come from the rigging defaults (``envelopelab.rigging.defaults``), from the last
entry of the list (duplicated under a free name), or from :data:`NEW_ENTRIES`.
"""

from __future__ import annotations

import copy
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from envelopelab.design.model import DesignDocument
from envelopelab.rigging import defaults

Path = Sequence[str | int]
FieldKind = Literal[
    "number", "integer", "text", "bool", "choice", "object", "objects", "scalars", "mapping"
]


@dataclass(frozen=True)
class FieldInfo:
    """Kind of value a design field holds.

    Attributes
    ----------
    kind : str
        ``number`` (float), ``integer``, ``text``, ``bool``, ``choice`` (one of
        ``choices``), ``object`` (a section), ``objects`` (a list of sections), ``scalars``
        (a list of ``item_kind`` values) or ``mapping`` (name to ``item_kind`` value).
    optional : bool
        The field may be ``None`` (cleared or removed).
    choices : tuple of str
        Allowed values of a ``choice`` field.
    item_kind : str
        Kind of the entries of a ``scalars`` or ``mapping`` field.
    model : type of BaseModel or None
        Model of an ``object`` field or of the entries of an ``objects`` field.
    """

    kind: FieldKind
    optional: bool = False
    choices: tuple[str, ...] = field(default=())
    item_kind: FieldKind = "text"
    model: type[BaseModel] | None = None


def _strip_none(annotation: Any) -> tuple[Any, bool]:
    args = typing.get_args(annotation)
    if typing.get_origin(annotation) in (typing.Union, types.UnionType) and type(None) in args:
        rest = [a for a in args if a is not type(None)]
        return (rest[0] if len(rest) == 1 else typing.Union[tuple(rest)]), True  # noqa: UP007
    return annotation, False


def _scalar_kind(annotation: Any) -> FieldKind:
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if typing.get_origin(annotation) is Literal:
        return "choice"
    return "text"


def _info(annotation: Any) -> FieldInfo:
    inner, optional = _strip_none(annotation)
    origin = typing.get_origin(inner)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return FieldInfo("object", optional, model=inner)
    if origin is list:
        (item,) = typing.get_args(inner)
        if isinstance(item, type) and issubclass(item, BaseModel):
            return FieldInfo("objects", optional, model=item)
        return FieldInfo("scalars", optional, item_kind=_scalar_kind(item))
    if origin is dict:
        _, value = typing.get_args(inner)
        return FieldInfo("mapping", optional, item_kind=_scalar_kind(value))
    kind = _scalar_kind(inner)
    choices = tuple(str(c) for c in typing.get_args(inner)) if kind == "choice" else ()
    return FieldInfo(kind, optional, choices)


def _field(model: type[BaseModel], key: str) -> Any:
    for name, spec in model.model_fields.items():
        if key in (name, spec.alias):
            return spec.annotation
    raise KeyError(f"{model.__name__} has no field {key!r}")


def field_info(path: Path) -> FieldInfo:
    """Kind of the design field at ``path`` (keys and list indices of the JSON data).

    Raises
    ------
    KeyError
        When the path names no field of the design schema.
    """
    if not path:
        return FieldInfo("object", model=DesignDocument)
    info = FieldInfo("object", model=DesignDocument)
    for key in path:
        if info.kind == "object" and isinstance(key, str):
            assert info.model is not None
            info = _info(_field(info.model, key))
        elif info.kind == "objects" and isinstance(key, int):
            info = FieldInfo("object", model=info.model)
        elif info.kind == "scalars" and isinstance(key, int):
            info = FieldInfo(info.item_kind)
        elif info.kind == "mapping" and isinstance(key, str):
            info = FieldInfo(info.item_kind)
        else:
            raise KeyError(f"no design field at {'/'.join(map(str, path))}")
    return info


def _seam_type(_design: DesignDocument) -> dict[str, Any]:
    # A plain seam: 25 mm allowance, two rows of stitching, 80 % efficiency (assumed).
    return {"name": "seam", "allowance": 0.025, "rows_of_stitching": 2, "efficiency": 0.8}


def _panel_zone(design: DesignDocument) -> dict[str, Any]:
    gores = design.gores
    if gores is None:
        raise ValueError("panel zones need a standard-gore design")
    taken = {(z.row, g) for z in gores.panel_zones for g in z.gores}
    free = next(
        (
            (row.letter, gore)
            for row in gores.panel_rows
            for gore in range(1, gores.count + 1)
            if (row.letter, gore) not in taken
        ),
        None,
    )
    if free is None:
        raise ValueError("every panel is already in a panel zone")
    names = {z.name for z in gores.panel_zones}
    return {
        "name": _free_name("panel zone", names),
        "row": free[0],
        "gores": [free[1]],
        "zone": next(iter(design.zones), "body"),
    }


def _feature(_design: DesignDocument) -> dict[str, Any]:
    return {"type": "applique", "host_panels": [], "feed_holes": [], "tapes": [], "notes": None}


def _scale_variant(_design: DesignDocument) -> dict[str, Any]:
    return {"factor_k": 0.1, "model_fabric_override": {}, "fixed_size_overrides": {}}


def _dump(build: Callable[[DesignDocument], BaseModel]) -> Callable[[DesignDocument], Any]:
    return lambda design: build(design).model_dump(by_alias=True, mode="json")


#: New values by schema path (``*`` for a list index): optional sections from the
#: rigging defaults, first list entries where a list is empty.
NEW_ENTRIES: dict[tuple[str, ...], Callable[[DesignDocument], Any]] = {
    ("parachute",): _dump(defaults.default_parachute),
    ("parachute", "crown_ring"): _dump(lambda _d: defaults.crown_ring()),
    ("parachute", "centre_ring"): _dump(lambda _d: defaults.centre_ring()),
    ("rigging", "red_line"): _dump(defaults.default_red_line),
    ("rigging", "flying_wires"): _dump(defaults.default_flying_wires),
    ("scoop",): _dump(defaults.default_scoop),
    ("turning_vents", "*"): lambda d: defaults.turning_vent_pair(d)[0].model_dump(
        by_alias=True, mode="json"
    ),
    ("seam_types", "*"): _seam_type,
    ("gores", "panel_zones", "*"): _panel_zone,
    ("features", "*"): _feature,
    ("scale_variants", "*"): _scale_variant,
}


#: List entries always made by their :data:`NEW_ENTRIES` builder, never by duplicating the
#: last one (a copy would claim the same panels).
BUILT_ENTRIES = {("gores", "panel_zones", "*")}


def _pattern(path: Path) -> tuple[str, ...]:
    return tuple("*" if isinstance(p, int) else p for p in path)


def _get(data: Any, path: Path) -> Any:
    for key in path:
        data = data[key]
    return data


def _free_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    k = 2
    while f"{name} {k}" in taken:
        k += 1
    return f"{name} {k}"


def new_value(design: DesignDocument, path: Path) -> Any:
    """JSON value for a new optional section or list entry at ``path``.

    For a list entry (``path`` ends with the list's length), the last entry is duplicated
    under a free name when there is one (except :data:`BUILT_ENTRIES`); otherwise, and for
    sections, the value comes from :data:`NEW_ENTRIES`.

    Raises
    ------
    KeyError
        When there is no way to make a value for ``path`` (the field is not optional, or no
        default exists for it).
    """
    data = design.model_dump(by_alias=True, mode="json")
    if path and isinstance(path[-1], int) and _pattern(path) not in BUILT_ENTRIES:
        entries = _get(data, path[:-1]) or []
        if entries and isinstance(entries[-1], dict):
            entry = copy.deepcopy(entries[-1])
            if "name" in entry:
                entry["name"] = _free_name(entry["name"], {e.get("name") for e in entries})
            return entry
    build = NEW_ENTRIES.get(_pattern(path))
    if build is None:
        raise KeyError(f"no default for {'/'.join(map(str, path))}")
    return build(design)
