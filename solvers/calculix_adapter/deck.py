"""Write CalculiX input decks (``.inp``) for one verification job.

The fabric is modelled with CalculiX M3D3 membrane elements (no bending) of nominal
thickness ``t``; stress resultants are recovered as :math:`N = \\sigma t`. Every element has
its own orientation (local axis 1 = warp), anisotropic material and initial stress.
Tapes are tension-only SPRINGA elements with a piecewise-linear force-elongation table;
optional SPRING1 elements tie every node to its reference position (stabilisation).

All loads, including the pressure, are nodal forces (``*CLOAD``): CalculiX 2.21 stops with
a segmentation fault for element pressure (``*DLOAD P``) on M3D3 elements, and nodal loads
make the applied force vector exactly known to the adapter. A job is a list of static
NLGEOM steps, each with its own nodal load vector; CalculiX ramps linearly from one step's
loads to the next, except in an ``instant`` step (``AMPLITUDE=STEP``), which a balanced
start needs: its loads equal the internal force of the initial stress from the outset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class LoadStep:
    """One static step: name, nodal load vector (N, shape (n, 3)) at its end, and whether
    the loads are applied at once (``instant``) instead of ramped from the previous step."""

    name: str
    loads: FloatArray
    instant: bool = False


@dataclass
class DeckInput:
    """Everything one CalculiX job needs (SI units).

    Attributes
    ----------
    reference : ndarray, shape (n, 3)
        Reference node positions, m.
    triangles : ndarray of int, shape (m, 3)
        Membrane elements, counter-clockwise (outward normals).
    axes : ndarray, shape (m, 3, 3)
        Rows: local axis 1, local axis 2, normal of each element, reference config.
    material : ndarray, shape (m, 3, 3)
        Plane resultant stiffness of every element in its local axes (Voigt, engineering
        shear: :math:`[N_{11}, N_{22}, N_{12}] = D [E_{11}, E_{22}, 2E_{12}]`), N/m. May be
        fully populated (a wrinkled element's tension-field law is anisotropic).
    transverse : ndarray, shape (m,)
        Through-thickness stiffness resultant (normal and transverse shear), N/m. It is
        decoupled from the membrane (plane stress) and only keeps CalculiX's internal 3D
        expansion of the membrane well conditioned.
    initial_stress : ndarray, shape (m, 3, 3)
        Initial stress resultant in global axes, N/m (in the element plane).
    steps : list of LoadStep
        Static steps in order.
    tape_edges : ndarray of int, shape (k, 2)
        Tape elements.
    tape_rest, tape_ref : ndarray, shape (k,)
        Unstressed and reference length of each tape element, m.
    tape_ea : ndarray, shape (k,)
        Axial stiffness, N.
    fixed : list of (int, int)
        (node, dof 1-3) held at the reference position.
    equations : list of (int, ndarray)
        (node, unit normal) of nodes kept on a plane through their reference position.
    hold_all : bool
        Hold every node (the job's reactions are then the out-of-balance force).
    stabilization : float
        Stiffness of the node-to-reference SPRING1 springs (all nodes and directions),
        N/m; 0 for none.
    thickness : float
        Nominal membrane thickness, m.
    tape_slack_ratio : float
        Compression stiffness of a slack tape as a fraction of :math:`EA/L_0` (0: tension
        only, the preview solver's law).
    initial_increment : float
        First increment as a fraction of each step.
    residual_tolerance : float
        CalculiX field control :math:`R_n^\\alpha` (largest residual / average force).
    max_increments : int
        Increment limit per step.
    """

    reference: FloatArray
    triangles: IntArray
    axes: FloatArray
    material: FloatArray
    transverse: FloatArray
    initial_stress: FloatArray
    steps: list[LoadStep]
    tape_edges: IntArray
    tape_rest: FloatArray
    tape_ref: FloatArray
    tape_ea: FloatArray
    fixed: list[tuple[int, int]] = field(default_factory=list)
    equations: list[tuple[int, FloatArray]] = field(default_factory=list)
    hold_all: bool = False
    stabilization: float = 0.0
    thickness: float = 1e-3
    tape_slack_ratio: float = 0.0
    initial_increment: float = 0.25
    residual_tolerance: float = 1e-5
    max_increments: int = 400

    @property
    def n_steps(self) -> int:
        """Number of CalculiX steps."""
        return len(self.steps)


def _f(value: float) -> str:
    # CalculiX reads a data line of bare integers as integer data (e.g. a *SPRING line
    # "1000" is taken as a DOF line), so every real carries a decimal point or exponent.
    text = f"{value:.12g}"
    return text if any(c in text for c in ".en") else text + "."


def _nodal_loads(loads: FloatArray) -> list[str]:
    lines = []
    for i, vec in enumerate(loads):
        for dof in range(3):
            if vec[dof] != 0.0:
                lines.append(f"{i + 1},{dof + 1},{_f(vec[dof])}")
    return lines


def write_deck(deck: DeckInput, path: Path) -> Path:
    """Write the CalculiX input file.

    Parameters
    ----------
    deck : DeckInput
        Job data.
    path : Path
        Output ``.inp`` file.

    Returns
    -------
    Path
        The written file.
    """
    t = deck.thickness
    n, m = len(deck.reference), len(deck.triangles)
    out: list[str] = ["** EnvelopeLab verification job (generated; do not edit)", "*NODE"]
    out += [f"{i + 1},{_f(x)},{_f(y)},{_f(z)}" for i, (x, y, z) in enumerate(deck.reference)]
    out.append("*ELEMENT,TYPE=M3D3,ELSET=EFABRIC")
    out += [f"{k + 1},{a + 1},{b + 1},{c + 1}" for k, (a, b, c) in enumerate(deck.triangles)]
    out += ["*NSET,NSET=NALL,GENERATE", f"1,{n},1"]
    for k in range(m):
        a, b = deck.axes[k, 0], deck.axes[k, 1]
        d = deck.material[k] / t
        z = deck.transverse[k] / t
        # *ELASTIC,TYPE=ANISO order: D1111 D1122 D2222 D1133 D2233 D3333 D1112 D2212 D3312
        # D1212 D1113 D2213 D3313 D1213 D1313 D1123 D2223 D3323 D1223 D1323 D2323, with
        # engineering shear strain; plane stress: no coupling to the thickness direction.
        aniso = (
            d[0, 0], d[0, 1], d[1, 1], 0.0, 0.0, z, d[0, 2], d[1, 2], 0.0,
            d[2, 2], 0.0, 0.0, 0.0, 0.0, z, 0.0, 0.0, 0.0, 0.0, 0.0, z,
        )  # fmt: skip
        out += [
            f"*ELSET,ELSET=E{k + 1}",
            str(k + 1),
            f"*ORIENTATION,NAME=O{k + 1},SYSTEM=RECTANGULAR",
            ",".join(_f(v) for v in (*a, *b)),
            f"*MATERIAL,NAME=M{k + 1}",
            "*ELASTIC,TYPE=ANISO",
            ",".join(_f(v) for v in aniso[:8]),
            ",".join(_f(v) for v in aniso[8:16]),
            ",".join(_f(v) for v in aniso[16:]),
            f"*MEMBRANE SECTION,ELSET=E{k + 1},MATERIAL=M{k + 1},ORIENTATION=O{k + 1}",
            _f(t),
        ]
    next_id = m + 1
    for j, (i0, i1) in enumerate(deck.tape_edges):
        ea, l0, li = deck.tape_ea[j], deck.tape_rest[j], deck.tape_ref[j]
        k_t = ea / l0
        slack = l0 - li  # elongation (from the reference length) at which tension starts
        lo = -0.9 * li
        hi = slack + l0
        out += [
            f"*ELEMENT,TYPE=SPRINGA,ELSET=T{j + 1}",
            f"{next_id},{i0 + 1},{i1 + 1}",
            f"*SPRING,ELSET=T{j + 1},NONLINEAR",
            f"{_f(deck.tape_slack_ratio * k_t * (lo - slack))},{_f(lo)}",
            f"0.,{_f(slack)}",
            f"{_f(k_t * l0)},{_f(hi)}",
        ]
        next_id += 1
    if deck.stabilization > 0.0 and not deck.hold_all:
        for dof in range(3):
            out.append(f"*ELEMENT,TYPE=SPRING1,ELSET=STAB{dof + 1}")
            out += [f"{next_id + dof * n + i},{i + 1}" for i in range(n)]
            out += [f"*SPRING,ELSET=STAB{dof + 1}", str(dof + 1), _f(deck.stabilization)]
    if deck.hold_all:
        out += ["*BOUNDARY", "NALL,1,3,0."]
    else:
        if deck.fixed:
            out.append("*BOUNDARY")
            out += [f"{node + 1},{dof},{dof},0." for node, dof in deck.fixed]
        for node, normal in deck.equations:
            dofs = [(d, normal[d]) for d in range(3) if abs(normal[d]) > 1e-12]
            if len(dofs) == 1:
                out += ["*BOUNDARY", f"{node + 1},{dofs[0][0] + 1},{dofs[0][0] + 1},0."]
            else:
                terms = ",".join(f"{node + 1},{d + 1},{_f(c)}" for d, c in dofs)
                out += ["*EQUATION", str(len(dofs)), terms]
    out.append("*INITIAL CONDITIONS,TYPE=STRESS")
    for k in range(m):
        s = deck.initial_stress[k] / t
        comps = (s[0, 0], s[1, 1], s[2, 2], s[0, 1], s[0, 2], s[1, 2])
        for ip in (1, 2):
            out.append(f"{k + 1},{ip}," + ",".join(_f(v) for v in comps))
    for index, step in enumerate(deck.steps):
        out += [
            f"** step: {step.name}",
            f"*STEP,NLGEOM,INC={deck.max_increments}" + (",AMPLITUDE=STEP" if step.instant else ""),
            "*STATIC",
            f"{_f(deck.initial_increment)},1.0,1e-7,{_f(deck.initial_increment)}",
            "*CONTROLS,PARAMETERS=FIELD",
            f"{_f(deck.residual_tolerance)},{_f(10 * deck.residual_tolerance)},,,,,,",
            "*CLOAD,OP=NEW",
            *_nodal_loads(step.loads),
        ]
        if index == len(deck.steps) - 1:
            out += ["*NODE PRINT,NSET=NALL", "U,RF", "*EL PRINT,ELSET=EFABRIC", "S"]
        out.append("*END STEP")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
