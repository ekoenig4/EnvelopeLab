r"""Input model of the preview membrane solver.

A :class:`SolverModel` is the as-sewn envelope: a triangulated mesh whose triangles keep
their flat (as-cut) rest shape, grain direction and material zone; tape and cable paths
along mesh edges; seam lines (for seam factor-of-safety checks); boundary conditions;
loads; operating conditions; and solver settings. Everything is SI (m, N, Pa, kg, K).

Build one directly from arrays or from the as-sewn rest model of a build pack with
:func:`model_from_rest_model`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import numpy.typing as npt

from envelopelab.atmosphere import G0, gas_density, isa
from envelopelab.materials.membrane import MembraneMaterial, SourceTag, TapeMaterial
from envelopelab.solvers.membrane import FloatArray, IntArray

if TYPE_CHECKING:
    from envelopelab.assembly.rest_model import RestModel

DampingKind = Literal["kinetic", "viscous"]


class ModelError(ValueError):
    """Raised when a solver model is inconsistent (bad indices, missing materials)."""


def _int_array(values: npt.ArrayLike, width: int | None = None) -> IntArray:
    arr = np.asarray(values, dtype=np.int64)
    if width is not None:
        arr = arr.reshape(-1, width)
    return arr


@dataclass
class CableSet:
    """Tension-only bars along mesh edges (load tapes, webbing, rigging cables).

    Attributes
    ----------
    name : str
        Identifier (e.g. the seam id the tape is sewn into).
    edges : ndarray of int, shape (e, 2)
        Node pairs.
    material : TapeMaterial
        Axial stiffness (N), strength (N) and linear mass (kg/m).
    rest_lengths : ndarray, shape (e,), optional
        Unstressed lengths, m. Default: edge lengths at the initial positions.
    """

    name: str
    edges: IntArray
    material: TapeMaterial
    rest_lengths: FloatArray | None = None

    def __post_init__(self) -> None:
        self.edges = _int_array(self.edges, 2)


@dataclass
class SeamLine:
    """A sewn seam checked for factor of safety (strength = efficiency x fabric strength).

    Attributes
    ----------
    name : str
        Seam id.
    edges : ndarray of int, shape (e, 2)
        Mesh edges along the seam.
    """

    name: str
    edges: IntArray

    def __post_init__(self) -> None:
        self.edges = _int_array(self.edges, 2)


@dataclass
class NodeConstraint:
    """Fixed or prescribed nodes (mouth ring, crown attachment points, supports).

    Attributes
    ----------
    name : str
        Group name used in the force-balance table (e.g. ``"mouth"``).
    nodes : ndarray of int
        Constrained nodes.
    positions : ndarray, shape (k, 3), optional
        Prescribed positions, m. Default: the initial positions (fixed nodes).
    dofs : tuple of bool
        Which of x, y, z are constrained (default all three).
    """

    name: str
    nodes: IntArray
    positions: FloatArray | None = None
    dofs: tuple[bool, bool, bool] = (True, True, True)

    def __post_init__(self) -> None:
        self.nodes = _int_array(self.nodes).ravel()
        if self.positions is not None:
            self.positions = np.asarray(self.positions, dtype=np.float64).reshape(-1, 3)
            if len(self.positions) != len(self.nodes):
                raise ModelError(f"constraint {self.name}: one position per node required")


@dataclass
class SymmetryPlane:
    """Nodes that stay on a plane (symmetry of standard-gore validation cases).

    Attributes
    ----------
    name : str
        Group name.
    nodes : ndarray of int
        Nodes on the plane; they move in-plane only.
    normal : tuple of float
        Plane normal (normalised internally), dimensionless.
    point : tuple of float
        A point on the plane, m.
    """

    name: str
    nodes: IntArray
    normal: tuple[float, float, float]
    point: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        self.nodes = _int_array(self.nodes).ravel()
        if np.linalg.norm(self.normal) < 1e-12:
            raise ModelError(f"symmetry plane {self.name}: zero normal")


@dataclass
class PointLoad:
    """Dead forces at nodes (rigging, appendage attachment points).

    Attributes
    ----------
    name : str
        Load name.
    nodes : ndarray of int
        Loaded nodes.
    force : ndarray, shape (3,) or (k, 3)
        Force per node, N.
    """

    name: str
    nodes: IntArray
    force: FloatArray

    def __post_init__(self) -> None:
        self.nodes = _int_array(self.nodes).ravel()
        self.force = np.broadcast_to(
            np.asarray(self.force, dtype=np.float64), (len(self.nodes), 3)
        ).copy()


@dataclass
class LineLoad:
    """Dead force per unit length along mesh edges (tape-mounted appendages, skirts).

    Attributes
    ----------
    name : str
        Load name.
    edges : ndarray of int, shape (e, 2)
        Loaded edges.
    force_per_length : ndarray, shape (3,)
        Force per unit length measured at the initial positions, N/m.
    """

    name: str
    edges: IntArray
    force_per_length: FloatArray

    def __post_init__(self) -> None:
        self.edges = _int_array(self.edges, 2)
        self.force_per_length = np.asarray(self.force_per_length, dtype=np.float64).reshape(3)


@dataclass
class DistributedLoad:
    """Dead traction over triangles (coatings, scoops, lumped appendage mass).

    Attributes
    ----------
    name : str
        Load name.
    triangles : ndarray of int
        Loaded triangles.
    traction : ndarray, shape (3,)
        Force per unit rest area, Pa (N/m^2).
    """

    name: str
    triangles: IntArray
    traction: FloatArray

    def __post_init__(self) -> None:
        self.triangles = _int_array(self.triangles).ravel()
        self.traction = np.asarray(self.traction, dtype=np.float64).reshape(3)


@dataclass
class PressureClosure:
    """An opening closed by a cap that is not meshed (parachute, end cap).

    The internal pressure on a flat fan cap over the opening is transferred to the ring
    nodes in proportion to their tributary length, and the cap is counted in the volume.

    Attributes
    ----------
    name : str
        Opening name.
    nodes : ndarray of int
        Nodes of the opening loop (any order).
    """

    name: str
    nodes: IntArray

    def __post_init__(self) -> None:
        self.nodes = _int_array(self.nodes).ravel()


@dataclass(frozen=True)
class OperatingConditions:
    r"""Gas densities, gravity and pressure datum.

    The internal-minus-ambient pressure is

    .. math:: \Delta p(z) = p_0 + (\rho_{amb} - \rho_{int})\, g\, \max(z - z_{mouth}, 0)

    Attributes
    ----------
    ambient_density, internal_density : float
        kg/m^3.
    mouth_height : float
        Height of the zero-pressure level (the mouth), m.
    gravity : float
        m/s^2; acts along -z.
    uniform_pressure : float
        Additional uniform pressure :math:`p_0`, Pa (0 for an open hot-air envelope;
        used by closed analytic benchmarks).
    self_weight : bool
        Include fabric and tape weight.
    internal_temperature : float, optional
        Envelope gas temperature, K (checked against each fabric's service limit).
    ambient_temperature : float, optional
        K, for the record.
    source : {"datasheet", "measured", "assumed"}
        Provenance of the conditions.
    label : str
        Load-case name.
    """

    ambient_density: float
    internal_density: float
    mouth_height: float = 0.0
    gravity: float = G0.value
    uniform_pressure: float = 0.0
    self_weight: bool = True
    internal_temperature: float | None = None
    ambient_temperature: float | None = None
    source: SourceTag = "assumed"
    label: str = "load case"

    @classmethod
    def hot_air(
        cls,
        internal_temperature: float,
        altitude: float = 0.0,
        temperature_offset: float = 0.0,
        mouth_height: float = 0.0,
        self_weight: bool = True,
        label: str | None = None,
    ) -> OperatingConditions:
        """Hot-air envelope in the ISA at a pressure altitude.

        Parameters
        ----------
        internal_temperature : float
            Mean internal gas temperature, K.
        altitude : float
            Geopotential pressure altitude, m.
        temperature_offset : float
            ISA temperature deviation, K.
        mouth_height : float
            Height of the mouth in model coordinates, m.
        self_weight : bool
            Include fabric and tape weight.
        label : str, optional
            Load-case name.

        Returns
        -------
        OperatingConditions
            Dry-air densities from :func:`envelopelab.atmosphere.gas_density`.
        """
        ambient = isa(altitude, temperature_offset)
        rho_int = gas_density(ambient.pressure, internal_temperature)
        return cls(
            ambient_density=ambient.density,
            internal_density=rho_int,
            mouth_height=mouth_height,
            self_weight=self_weight,
            internal_temperature=internal_temperature,
            ambient_temperature=ambient.temperature,
            source="datasheet",
            label=label
            or (
                f"hot air {internal_temperature - 273.15:.0f} degC internal, ISA"
                f"{temperature_offset:+.0f} K at {altitude:.0f} m"
            ),
        )

    @property
    def pressure_gradient(self) -> float:
        """:math:`(\\rho_{amb} - \\rho_{int}) g`, Pa/m."""
        return (self.ambient_density - self.internal_density) * self.gravity

    def pressure(self, z: npt.ArrayLike) -> FloatArray:
        """Internal-minus-ambient pressure at heights ``z`` (m), Pa."""
        height = np.maximum(np.asarray(z, dtype=np.float64) - self.mouth_height, 0.0)
        return self.uniform_pressure + self.pressure_gradient * height

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary with units."""
        return {
            "label": self.label,
            "ambient_density_kg_m3": self.ambient_density,
            "internal_density_kg_m3": self.internal_density,
            "pressure_gradient_pa_m": self.pressure_gradient,
            "mouth_height_m": self.mouth_height,
            "gravity_m_s2": self.gravity,
            "uniform_pressure_pa": self.uniform_pressure,
            "self_weight": self.self_weight,
            "internal_temperature_k": self.internal_temperature,
            "ambient_temperature_k": self.ambient_temperature,
            "source": self.source,
        }


@dataclass(frozen=True)
class SolverSettings:
    """Dynamic-relaxation settings.

    Attributes
    ----------
    tolerance : float
        Converged when :math:`\\|R_{free}\\| / \\|F_{ext}\\|` falls below this,
        dimensionless (AGENTS.md default 1e-6).
    max_iterations : int
        Iteration limit.
    damping : {"kinetic", "viscous"}
        Kinetic damping (energy-peak resets, default) or viscous damping.
    viscous_damping : float
        Damping coefficient per fictitious time step for ``viscous``, dimensionless.
    mass_factor : float
        Multiplier on the Gershgorin fictitious masses (1 = factor-of-2 margin on the
        explicit stability limit), dimensionless.
    tension_field : bool
        Release compressive principal stress (wrinkling). False keeps a linear-elastic
        membrane that carries compression.
    slack_stiffness_ratio : float
        :math:`\\kappa`, residual stiffness in released directions, dimensionless.
    progress_interval : int
        Iterations between progress callbacks and cancellation checks.
    time_limit : float, optional
        Wall-time limit, s.
    wrinkle_tolerance : float
        Compression below this fraction of the local major resultant is not a finding,
        dimensionless.
    """

    tolerance: float = 1e-6
    max_iterations: int = 200_000
    damping: DampingKind = "kinetic"
    viscous_damping: float = 0.02
    mass_factor: float = 1.0
    tension_field: bool = True
    slack_stiffness_ratio: float = 1e-3
    progress_interval: int = 200
    time_limit: float | None = None
    wrinkle_tolerance: float = 1e-2

    def __post_init__(self) -> None:
        if self.tolerance <= 0.0 or self.max_iterations < 1:
            raise ModelError("tolerance must be positive and max_iterations >= 1")
        if self.mass_factor < 0.5:
            raise ModelError("mass_factor below 0.5 violates the explicit stability limit")
        if not 0.0 <= self.slack_stiffness_ratio < 1.0:
            raise ModelError("slack_stiffness_ratio must be in [0, 1)")

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dictionary."""
        return dict(self.__dict__)


@dataclass
class SolverModel:
    """The as-sewn envelope handed to :func:`envelopelab.solvers.dynamic_relaxation.solve`.

    Attributes
    ----------
    positions : ndarray, shape (n, 3)
        Initial 3D node positions (starting guess), m.
    triangles : ndarray of int, shape (m, 3)
        Node indices, counter-clockwise in the flat frame (outward normals).
    rest_uv : ndarray, shape (m, 3, 2)
        Flat rest corner coordinates, m.
    grain : ndarray, shape (m, 2)
        Warp direction in the flat frame of each triangle.
    tri_zone : ndarray of int, shape (m,)
        Index into ``zone_names``.
    zone_names : list of str
        Material zone per index.
    materials : dict of str to MembraneMaterial
        Material of each zone.
    cables, seams, constraints, symmetry, point_loads, line_loads, distributed_loads,
    closures : lists
        See the element classes.
    conditions : OperatingConditions
        Load case.
    name : str
        Model name.
    source_hash : str
        Content hash of the design the model came from ("" for synthetic models).
    """

    positions: FloatArray
    triangles: IntArray
    rest_uv: FloatArray
    grain: FloatArray
    tri_zone: IntArray
    zone_names: list[str]
    materials: dict[str, MembraneMaterial]
    conditions: OperatingConditions
    cables: list[CableSet] = field(default_factory=list)
    seams: list[SeamLine] = field(default_factory=list)
    constraints: list[NodeConstraint] = field(default_factory=list)
    symmetry: list[SymmetryPlane] = field(default_factory=list)
    point_loads: list[PointLoad] = field(default_factory=list)
    line_loads: list[LineLoad] = field(default_factory=list)
    distributed_loads: list[DistributedLoad] = field(default_factory=list)
    closures: list[PressureClosure] = field(default_factory=list)
    name: str = "model"
    source_hash: str = ""

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=np.float64).reshape(-1, 3)
        self.triangles = _int_array(self.triangles, 3)
        self.rest_uv = np.asarray(self.rest_uv, dtype=np.float64).reshape(-1, 3, 2)
        m = len(self.triangles)
        self.grain = np.broadcast_to(np.asarray(self.grain, dtype=np.float64), (m, 2)).copy()
        self.tri_zone = np.broadcast_to(_int_array(self.tri_zone), (m,)).copy()
        self.validate()

    @classmethod
    def uniform(
        cls,
        positions: npt.ArrayLike,
        triangles: npt.ArrayLike,
        rest_uv: npt.ArrayLike,
        material: MembraneMaterial,
        conditions: OperatingConditions,
        grain: tuple[float, float] = (1.0, 0.0),
        zone: str = "fabric",
        **kwargs: Any,
    ) -> SolverModel:
        """Model with one material zone and one grain direction for every triangle.

        Parameters
        ----------
        positions : array_like, shape (n, 3)
            Initial positions, m.
        triangles : array_like of int, shape (m, 3)
            Node indices.
        rest_uv : array_like, shape (m, 3, 2)
            Flat rest coordinates, m.
        material : MembraneMaterial
            Fabric of every triangle.
        conditions : OperatingConditions
            Load case.
        grain : tuple of float
            Warp direction in every triangle's flat frame.
        zone : str
            Zone name.
        **kwargs
            Other :class:`SolverModel` fields (cables, constraints, loads, ...).

        Returns
        -------
        SolverModel
            The model.
        """
        tri = _int_array(triangles, 3)
        m = len(tri)
        return cls(
            positions=np.asarray(positions, dtype=np.float64),
            triangles=tri,
            rest_uv=np.asarray(rest_uv, dtype=np.float64),
            grain=np.tile(np.asarray(grain, dtype=np.float64), (m, 1)),
            tri_zone=np.zeros(m, dtype=np.int64),
            zone_names=[zone],
            materials={zone: material},
            conditions=conditions,
            **kwargs,
        )

    @property
    def n_nodes(self) -> int:
        """Number of nodes."""
        return len(self.positions)

    @property
    def n_triangles(self) -> int:
        """Number of membrane triangles."""
        return len(self.triangles)

    def validate(self) -> None:
        """Check indices, shapes and material assignments.

        Raises
        ------
        ModelError
            On the first inconsistency found.
        """
        n, m = self.n_nodes, self.n_triangles
        if len(self.rest_uv) != m:
            raise ModelError("rest_uv needs one entry per triangle")
        if m and (self.triangles.min() < 0 or self.triangles.max() >= n):
            raise ModelError("triangle node index out of range")
        if m and (self.tri_zone.min() < 0 or self.tri_zone.max() >= len(self.zone_names)):
            raise ModelError("tri_zone index out of range")
        missing = [z for z in self.zone_names if z not in self.materials]
        if missing:
            raise ModelError(f"no material for zones: {', '.join(missing)}")
        if not np.all(np.isfinite(self.positions)):
            raise ModelError("positions must be finite")
        groups: list[tuple[str, IntArray]] = [(c.name, c.edges) for c in self.cables]
        groups += [(s.name, s.edges) for s in self.seams]
        groups += [(c.name, c.nodes) for c in self.constraints]
        groups += [(s.name, s.nodes) for s in self.symmetry]
        groups += [(p.name, p.nodes) for p in self.point_loads]
        groups += [(line.name, line.edges) for line in self.line_loads]
        groups += [(c.name, c.nodes) for c in self.closures]
        for name, idx in groups:
            if idx.size and (idx.min() < 0 or idx.max() >= n):
                raise ModelError(f"{name}: node index out of range")
        for load in self.distributed_loads:
            if load.triangles.size and (load.triangles.min() < 0 or load.triangles.max() >= m):
                raise ModelError(f"{load.name}: triangle index out of range")
        for cable in self.cables:
            if cable.rest_lengths is not None:
                cable.rest_lengths = np.asarray(cable.rest_lengths, dtype=np.float64).ravel()
                if len(cable.rest_lengths) != len(cable.edges):
                    raise ModelError(f"{cable.name}: one rest length per edge required")
                if np.any(cable.rest_lengths <= 0.0):
                    raise ModelError(f"{cable.name}: rest lengths must be positive")

    def content_hash(self) -> str:
        """SHA-256 of the numerical model content (reproducibility metadata)."""
        digest = hashlib.sha256()
        for arr in (self.positions, self.rest_uv, self.grain):
            digest.update(np.ascontiguousarray(np.round(arr, 12)).tobytes())
        digest.update(np.ascontiguousarray(self.triangles).tobytes())
        digest.update(np.ascontiguousarray(self.tri_zone).tobytes())
        for zone in self.zone_names:
            digest.update(repr((zone, self.materials[zone])).encode())
        for cable in self.cables:
            digest.update(repr((cable.name, cable.material)).encode())
            digest.update(np.ascontiguousarray(cable.edges).tobytes())
        digest.update(repr(self.conditions).encode())
        for group in (
            self.constraints,
            self.symmetry,
            self.point_loads,
            self.line_loads,
            self.distributed_loads,
            self.closures,
        ):
            digest.update(repr(group).encode())
        digest.update(self.source_hash.encode())
        return digest.hexdigest()


def edge_rest_lengths(edges: IntArray, triangles: IntArray, rest_uv: FloatArray) -> FloatArray:
    """Flat (as-cut) length of mesh edges, averaged over the triangles that share them.

    Parameters
    ----------
    edges : ndarray of int, shape (e, 2)
        Node pairs.
    triangles : ndarray of int, shape (m, 3)
        Mesh triangles.
    rest_uv : ndarray, shape (m, 3, 2)
        Flat corner coordinates, m.

    Returns
    -------
    ndarray, shape (e,)
        Rest lengths, m. For a seam the two sides are averaged (seam ease is shared).

    Raises
    ------
    ModelError
        If an edge is not an edge of any triangle.
    """
    total: dict[tuple[int, int], list[float]] = {}
    for t, tri in enumerate(triangles):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            key = (min(tri[a], tri[b]), max(tri[a], tri[b]))
            length = float(np.linalg.norm(rest_uv[t, a] - rest_uv[t, b]))
            total.setdefault((int(key[0]), int(key[1])), []).append(length)
    out = np.empty(len(edges))
    for k, (i, j) in enumerate(edges):
        key = (int(min(i, j)), int(max(i, j)))
        if key not in total:
            raise ModelError(f"edge ({i}, {j}) is not a mesh edge")
        out[k] = float(np.mean(total[key]))
    return out


def model_from_rest_model(
    rest: RestModel,
    materials: Mapping[str, MembraneMaterial],
    conditions: OperatingConditions,
    tapes: Mapping[str, TapeMaterial] | None = None,
    fixed_openings: Sequence[str] = ("mouth",),
    closed_openings: Sequence[str] = (),
    default_grain: tuple[float, float] = (1.0, 0.0),
    name: str = "build pack",
) -> SolverModel:
    """Solver model from the as-sewn rest model of a build pack.

    Parameters
    ----------
    rest : RestModel
        Output of the pattern-import pipeline (flat rest triangles, grain, zones, seams,
        openings, initial guess).
    materials : mapping of str to MembraneMaterial
        Material per zone name; every zone used by the mesh must be present.
    conditions : OperatingConditions
        Load case.
    tapes : mapping of str to TapeMaterial, optional
        Material per ``load_tape`` name. Every seam with a load tape becomes a
        :class:`CableSet` with the flat seam length as rest length; a tape name without a
        material raises.
    fixed_openings : sequence of str
        Openings whose nodes are fixed (the mouth ring by default).
    closed_openings : sequence of str
        Openings closed by an unmeshed cap (e.g. a parachute over the crown ring).
    default_grain : tuple of float
        Warp direction for instances without a grain arrow.
    name : str
        Model name.

    Returns
    -------
    SolverModel
        With one :class:`SeamLine` per sewn seam.

    Raises
    ------
    ModelError
        For unknown openings, zones without material or tapes without material.
    """
    mesh = rest.mesh
    grain_inst = mesh.instance_grain.copy()
    unknown = np.isnan(grain_inst[:, 0])
    grain_inst[unknown] = default_grain
    zone_names = sorted(set(mesh.instance_zones))
    zone_of_inst = np.array([zone_names.index(z) for z in mesh.instance_zones], dtype=np.int64)
    tapes = tapes or {}
    cables: list[CableSet] = []
    seams: list[SeamLine] = []
    missing: list[str] = []
    for seam in rest.assembly.graph.seams:
        edges = mesh.seam_edges.get(seam.seam_id)
        if edges is None or not len(edges):
            continue
        seams.append(SeamLine(seam.seam_id, edges))
        tape = seam.props.load_tape
        if tape is None:
            continue
        if tape not in tapes:
            missing.append(tape)
            continue
        lengths = edge_rest_lengths(edges, mesh.triangles, mesh.rest_uv)
        cables.append(CableSet(seam.seam_id, edges, tapes[tape], lengths))
    if missing:
        raise ModelError(f"no tape material for: {', '.join(sorted(set(missing)))}")
    constraints = []
    closures = []
    for opening in (*fixed_openings, *closed_openings):
        if opening not in mesh.openings:
            raise ModelError(f"unknown opening {opening!r}; have {sorted(mesh.openings)}")
    for opening in fixed_openings:
        constraints.append(NodeConstraint(opening, np.unique(mesh.openings[opening])))
    for opening in closed_openings:
        closures.append(PressureClosure(opening, np.unique(mesh.openings[opening])))
    return SolverModel(
        positions=rest.positions,
        triangles=mesh.triangles,
        rest_uv=mesh.rest_uv,
        grain=grain_inst[mesh.tri_instance],
        tri_zone=zone_of_inst[mesh.tri_instance],
        zone_names=zone_names,
        materials={z: materials[z] for z in zone_names if z in materials},
        conditions=conditions,
        cables=cables,
        seams=seams,
        constraints=constraints,
        closures=closures,
        name=name,
        source_hash=rest.imported.content_hash,
    )
