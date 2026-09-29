"""CalculiX element checks: the deck's anisotropic material and initial stress reach ccx
as intended (single triangle, small strain). Skipped without ccx."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from calculix_adapter import CalculixInstallation
from calculix_adapter.deck import DeckInput, LoadStep, write_deck
from calculix_adapter.results import read_displacements, read_element_stress, read_reactions

T = 1e-3  # nominal thickness, m
#: Fully populated plane stiffness (N/m), as for a wrinkled element in fabric axes.
D = np.array([[1.0e5, 2.4e4, 1.0e4], [2.4e4, 8.0e4, -6.0e3], [1.0e4, -6.0e3, 3.0e4]])


def _run(ccx: CalculixInstallation, deck: DeckInput, work: Path) -> None:
    import subprocess

    write_deck(deck, work / "job.inp")
    proc = subprocess.run(
        [str(ccx.executable), "-i", "job"], cwd=work, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout[-2000:]


def _triangle(**kw: object) -> DeckInput:
    x = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.3, 0.8, 0.0]])
    base = dict(
        reference=x,
        triangles=np.array([[0, 1, 2]]),
        axes=np.eye(3)[None],
        material=D[None],
        transverse=np.array([1e5]),
        initial_stress=np.zeros((1, 3, 3)),
        steps=[LoadStep("load", np.zeros((3, 3)))],
        tape_edges=np.zeros((0, 2), dtype=np.int64),
        tape_rest=np.zeros(0),
        tape_ref=np.zeros(0),
        tape_ea=np.zeros(0),
        # Statically determinate in-plane support; z held everywhere.
        fixed=[(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)],
        thickness=T,
    )
    base.update(kw)
    return DeckInput(**base)  # type: ignore[arg-type]


def test_anisotropic_material_gives_d_times_strain(
    ccx: CalculixInstallation, tmp_path: Path
) -> None:
    loads = np.zeros((3, 3))
    loads[1, 0] = 2.0
    loads[2, 0] = -0.5
    loads[2, 1] = 1.5
    _run(ccx, _triangle(steps=[LoadStep("load", loads)]), tmp_path)
    u = read_displacements(tmp_path / "job.dat", 3)
    x = np.array([[0.0, 0.0], [1.0, 0.0], [0.3, 0.8]])
    # Constant-strain triangle: grad u from the three nodes (small strain, NLGEOM
    # differences are second order at strains of ~1e-5).
    a = np.column_stack([x[1] - x[0], x[2] - x[0]])
    du = np.column_stack([u[1, :2] - u[0, :2], u[2, :2] - u[0, :2]])
    grad = du @ np.linalg.inv(a)
    eps = 0.5 * (grad + grad.T)
    expected = D @ np.array([eps[0, 0], eps[1, 1], 2.0 * eps[0, 1]])
    s = read_element_stress(tmp_path / "job.dat", 1)[0] * T
    got = np.array([s[0, 0], s[1, 1], s[0, 1]])
    assert np.max(np.abs(eps)) > 1e-6  # the load did strain the element
    assert got == pytest.approx(expected, rel=1e-3, abs=1e-3 * np.abs(expected).max())


def test_held_initial_stress_gives_its_nodal_forces(
    ccx: CalculixInstallation, tmp_path: Path
) -> None:
    sigma = np.array([[120.0, 35.0, 0.0], [35.0, 80.0, 0.0], [0.0, 0.0, 0.0]])  # N/m
    deck = _triangle(initial_stress=sigma[None], hold_all=True)
    _run(ccx, deck, tmp_path)
    rf = read_reactions(tmp_path / "job.dat", 3)
    x = deck.reference
    area = 0.5 * np.linalg.norm(np.cross(x[1] - x[0], x[2] - x[0]))
    normal = np.array([0.0, 0.0, 1.0])
    expected = np.zeros((3, 3))
    for i in range(3):
        j, k = (i + 1) % 3, (i + 2) % 3
        grad = np.cross(normal, x[k] - x[j]) / (2.0 * area)
        expected[i] = area * sigma @ grad
    assert rf == pytest.approx(expected, abs=1e-6 * np.abs(expected).max())
