"""Analysis-run manifest: everything needed to repeat a structural solve.

A manifest records the design content hash, the numerical model hash, the source tags of
every fabric and tape property, the load case, the solver with its version and settings,
the mesh size and settings, the git commit, the Python and dependency versions, the
platform and the random seed. Two runs with the same :meth:`RunManifest.fingerprint` had
identical inputs; :meth:`RunManifest.differences` names what changed between two runs.

File format ``envelopelab.run-manifest`` version 1 is JSON.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from envelopelab.solvers.model import SolverModel

MANIFEST_FORMAT = "envelopelab.run-manifest"
MANIFEST_VERSION = 1
#: Fields that describe when/where a run happened rather than what was run.
_VOLATILE = ("created", "platform")


@dataclass
class RunManifest:
    """Reproducibility record of one solve (see module docstring).

    Attributes
    ----------
    solver : str
        Solver identifier.
    solver_version : str
        Solver version string.
    solver_settings : dict
        Settings that influence the result.
    design_content_hash : str
        SHA-256 of the build pack (mapping and source files), "" for synthetic models.
    model_content_hash : str
        SHA-256 of the numerical solver model.
    materials : dict
        Per zone, every fabric property with value, unit and source tag.
    tapes : dict
        Per tape set, every tape property with value, unit and source tag.
    load_case : dict
        Operating conditions with units.
    mesh : dict
        Node, element and tape-element counts, plus mesh settings when known.
    git_commit : str
        Commit of the EnvelopeLab source.
    python : str
        Python version.
    dependencies : dict
        Versions of the packages that influence the result.
    random_seed : int or None
        Seed (None: the solve uses no random numbers).
    platform : str
        Operating system and machine.
    created : str
        ISO timestamp (UTC).
    """

    solver: str
    solver_version: str
    solver_settings: dict[str, Any]
    design_content_hash: str
    model_content_hash: str
    materials: dict[str, Any]
    tapes: dict[str, Any]
    load_case: dict[str, Any]
    mesh: dict[str, Any]
    git_commit: str
    python: str
    dependencies: dict[str, str]
    random_seed: int | None = None
    platform: str = field(default_factory=lambda: f"{platform.system()} {platform.machine()}")
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary including format, version and fingerprint."""
        out: dict[str, Any] = {"format": MANIFEST_FORMAT, "format_version": MANIFEST_VERSION}
        out.update(asdict(self))
        out["fingerprint"] = self.fingerprint()
        return out

    def fingerprint(self) -> str:
        """SHA-256 of every input-defining field (excludes timestamp and platform)."""
        data = {k: v for k, v in asdict(self).items() if k not in _VOLATILE}
        text = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()

    def differences(self, other: RunManifest) -> list[str]:
        """Names of input-defining fields that differ from ``other``."""
        mine, theirs = asdict(self), asdict(other)
        return [k for k in mine if k not in _VOLATILE and mine[k] != theirs[k]]

    def save(self, path: str | Path) -> Path:
        """Write the manifest as JSON and return the path."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> RunManifest:
        """Read a manifest written by :meth:`save`.

        Raises
        ------
        ValueError
            On a wrong format, version or a fingerprint that does not match the content.
        """
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.pop("format", None) != MANIFEST_FORMAT:
            raise ValueError(f"{path}: not an {MANIFEST_FORMAT} file")
        if data.pop("format_version", None) != MANIFEST_VERSION:
            raise ValueError(f"{path}: unsupported manifest version")
        stored = data.pop("fingerprint", None)
        manifest = cls(**data)
        if stored != manifest.fingerprint():
            raise ValueError(f"{path}: fingerprint does not match the manifest content")
        return manifest


def manifest_for(
    model: SolverModel,
    solver: str,
    metadata: dict[str, Any] | None = None,
    solver_version: str | None = None,
    solver_settings: dict[str, Any] | None = None,
    mesh_options: dict[str, Any] | None = None,
) -> RunManifest:
    """Build the manifest of a solve of ``model``.

    Parameters
    ----------
    model : SolverModel
        Solved model (hashes, materials, tapes, load case, mesh size).
    solver : str
        Solver identifier.
    metadata : dict, optional
        Preview-solver result metadata; supplies settings, versions and commit.
    solver_version : str, optional
        Overrides the version (default: the installed EnvelopeLab version).
    solver_settings : dict, optional
        Overrides the settings from ``metadata``.
    mesh_options : dict, optional
        Mesh settings used to build the model (e.g. ``MeshOptions.model_dump()``).

    Returns
    -------
    RunManifest
        The record.
    """
    from envelopelab.assembly.rest_model import dependency_versions, git_commit

    meta = metadata or {}
    deps = dict(meta.get("dependencies") or dependency_versions())
    python = str(deps.pop("python", platform.python_version()))
    mesh: dict[str, Any] = {
        "nodes": model.n_nodes,
        "triangles": model.n_triangles,
        "tape_elements": int(sum(len(c.edges) for c in model.cables)),
    }
    if mesh_options is not None:
        mesh["options"] = mesh_options
    return RunManifest(
        solver=solver,
        solver_version=solver_version or str(deps.get("envelopelab", "unknown")),
        solver_settings=dict(solver_settings or meta.get("settings") or {}),
        design_content_hash=model.source_hash,
        model_content_hash=model.content_hash(),
        materials={z: model.materials[z].sources() for z in model.zone_names},
        tapes={c.name: c.material.sources() for c in model.cables},
        load_case=model.conditions.as_dict(),
        mesh=mesh,
        git_commit=str(meta.get("git_commit") or git_commit()),
        python=python,
        dependencies=deps,
        random_seed=meta.get("random_seed"),
    )
