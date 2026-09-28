"""Parse CalculiX text output (``.dat``, ``.sta``, ``.cvg``) of a verification pass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class CvgRow:
    """One Newton iteration from the ``.cvg`` file.

    Attributes
    ----------
    step, increment, attempt, iteration : int
        CalculiX counters.
    residual_force : float
        Largest residual force in % of the average force (CalculiX measure).
    displacement_correction : float
        Largest displacement correction in % of the largest increment.
    """

    step: int
    increment: int
    attempt: int
    iteration: int
    residual_force: float
    displacement_correction: float


@dataclass(frozen=True)
class StaRow:
    """One converged increment from the ``.sta`` file (step, increment, total time)."""

    step: int
    increment: int
    attempts: int
    iterations: int
    step_time: float


def _last_block(text: str, header: str) -> list[list[str]]:
    """Rows of numbers of the last block whose header line contains ``header``."""
    start = text.rfind(header)
    if start < 0:
        return []
    rows: list[list[str]] = []
    for line in text[start:].splitlines()[1:]:
        parts = line.split()
        if not parts:
            if rows:
                break
            continue
        if not parts[0].lstrip("-").isdigit():
            break
        rows.append(parts)
    return rows


def read_displacements(dat: Path, n_nodes: int) -> FloatArray:
    """Final displacement of nodes 1..n from the ``.dat`` file, m, shape (n, 3)."""
    rows = _last_block(dat.read_text(encoding="utf-8", errors="replace"), "displacements (vx")
    out = np.full((n_nodes, 3), np.nan)
    for r in rows:
        node = int(r[0]) - 1
        if 0 <= node < n_nodes:
            out[node] = [float(v) for v in r[1:4]]
    return out


def read_reactions(dat: Path, n_nodes: int) -> FloatArray:
    """Final reaction forces of nodes 1..n (zero where unconstrained), N, shape (n, 3)."""
    rows = _last_block(dat.read_text(encoding="utf-8", errors="replace"), "forces (fx,fy,fz)")
    out = np.zeros((n_nodes, 3))
    for r in rows:
        node = int(r[0]) - 1
        if 0 <= node < n_nodes:
            out[node] = [float(v) for v in r[1:4]]
    return out


def read_element_stress(dat: Path, n_elements: int) -> FloatArray:
    """Final element stress averaged over integration points, Pa, shape (m, 3, 3).

    Components are in the element's local material axes (CalculiX prints oriented
    elements in their local system).
    """
    rows = _last_block(dat.read_text(encoding="utf-8", errors="replace"), "stresses (elem")
    total = np.zeros((n_elements, 6))
    count = np.zeros(n_elements)
    for r in rows:
        elem = int(r[0]) - 1
        if 0 <= elem < n_elements:
            total[elem] += [float(v) for v in r[2:8]]
            count[elem] += 1
    if np.any(count == 0):
        raise ValueError(f"{dat}: stresses missing for {int(np.sum(count == 0))} elements")
    s = total / count[:, None]
    out = np.empty((n_elements, 3, 3))
    out[:, 0, 0], out[:, 1, 1], out[:, 2, 2] = s[:, 0], s[:, 1], s[:, 2]
    out[:, 0, 1] = out[:, 1, 0] = s[:, 3]
    out[:, 0, 2] = out[:, 2, 0] = s[:, 4]
    out[:, 1, 2] = out[:, 2, 1] = s[:, 5]
    return out


def read_cvg(path: Path) -> list[CvgRow]:
    """Newton iterations from the ``.cvg`` file (empty list when absent)."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 7 and all(p.isdigit() for p in parts[:4]):
            rows.append(
                CvgRow(
                    int(parts[0]),
                    int(parts[1]),
                    int(parts[2]),
                    int(parts[3]),
                    float(parts[5]),
                    float(parts[6]),
                )
            )
    return rows


def read_sta(path: Path) -> list[StaRow]:
    """Converged increments from the ``.sta`` file (empty list when absent)."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 7 and all(p.isdigit() for p in parts[:4]):
            rows.append(
                StaRow(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), float(parts[5]))
            )
    return rows


def steps_completed(path: Path, n_steps: int, tol: float = 1e-9) -> bool:
    """True when every step 1..n_steps reached step time 1 in the ``.sta`` file."""
    done = {r.step for r in read_sta(path) if r.step_time >= 1.0 - tol}
    return all(s in done for s in range(1, n_steps + 1))
