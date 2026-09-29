r"""One-at-a-time sensitivity sweep of a simulated shape.

Each parameter is moved to a low and a high value with the others at their baseline,
the model is rebuilt by a caller-supplied factory and solved (preview solver by
default), and the report metrics are compared with the baseline. The parameters are the
ones the Reality Check report asks for:

========================  =====================================  ======================
parameter                 how it enters                          default range
========================  =====================================  ======================
internal temperature      :math:`\rho_{int}` and pressure (ISA)  baseline :math:`\pm` 10 K
fabric stiffness          every stiffness of every fabric        :math:`\times` 0.8 / 1.2
material weight           fabric and tape mass                   :math:`\times` 0.8 / 1.2
seam-length error         each rim segment between match points  :math:`\pm` 5 mm
                          sewn long/short (skin scaled so its
                          rim changes by :math:`N e`)
pressure-loss factor      appendage chamber pressure             :math:`\times` 0.5 / 2
========================  =====================================  ======================

A sweep case that does not converge is kept in the table with ``converged = False``; its
numbers are not a prediction. The sensitivity :math:`S = (q_{high} - q_{low}) /
(x_{high} - x_{low})` is reported only when both ends converged.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from envelopelab.materials.membrane import MaterialValue, MembraneMaterial, TapeMaterial
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.model import SolverModel, SolverSettings
from envelopelab.solvers.simulation import SimulationResult, from_preview


@dataclass(frozen=True)
class SweepSettings:
    """Values of the swept parameters (SI).

    Attributes
    ----------
    internal_temperature : float
        K.
    stiffness_factor, weight_factor : float
        Multipliers on fabric stiffness and material mass, -.
    seam_length_error : float
        Length error of every rim segment between match points, m.
    loss_factor : float
        Appendage pressure-loss factor, - (source ``assumed``).
    """

    internal_temperature: float
    stiffness_factor: float = 1.0
    weight_factor: float = 1.0
    seam_length_error: float = 0.0
    loss_factor: float = 0.1


@dataclass(frozen=True)
class SweepDeltas:
    """Low/high offsets of each parameter."""

    temperature: float = 10.0
    stiffness: tuple[float, float] = (0.8, 1.2)
    weight: tuple[float, float] = (0.8, 1.2)
    seam_length: float = 5e-3
    loss_factor: tuple[float, float] = (0.5, 2.0)


PARAMETERS: dict[str, tuple[str, str]] = {
    "internal_temperature": ("internal temperature", "K"),
    "stiffness_factor": ("fabric stiffness factor", "-"),
    "weight_factor": ("material weight factor", "-"),
    "seam_length_error": ("seam-length error per rim segment", "m"),
    "loss_factor": ("appendage pressure-loss factor (assumed)", "-"),
}


def sweep_cases(
    base: SweepSettings, deltas: SweepDeltas | None = None
) -> list[tuple[str, str, SweepSettings]]:
    """(parameter, ``low``/``high``, settings) for every one-at-a-time case."""
    d = deltas or SweepDeltas()
    out = []
    t = base.internal_temperature
    out.append(
        ("internal_temperature", "low", replace(base, internal_temperature=t - d.temperature))
    )
    out.append(
        ("internal_temperature", "high", replace(base, internal_temperature=t + d.temperature))
    )
    out.append(
        (
            "stiffness_factor",
            "low",
            replace(base, stiffness_factor=base.stiffness_factor * d.stiffness[0]),
        )
    )
    out.append(
        (
            "stiffness_factor",
            "high",
            replace(base, stiffness_factor=base.stiffness_factor * d.stiffness[1]),
        )
    )
    out.append(
        ("weight_factor", "low", replace(base, weight_factor=base.weight_factor * d.weight[0]))
    )
    out.append(
        ("weight_factor", "high", replace(base, weight_factor=base.weight_factor * d.weight[1]))
    )
    out.append(
        (
            "seam_length_error",
            "low",
            replace(base, seam_length_error=base.seam_length_error - d.seam_length),
        )
    )
    out.append(
        (
            "seam_length_error",
            "high",
            replace(base, seam_length_error=base.seam_length_error + d.seam_length),
        )
    )
    lo = min(base.loss_factor * d.loss_factor[0], 0.95)
    hi = min(base.loss_factor * d.loss_factor[1], 0.95)
    if base.loss_factor == 0.0:
        lo, hi = 0.0, 0.1
    out.append(("loss_factor", "low", replace(base, loss_factor=lo)))
    out.append(("loss_factor", "high", replace(base, loss_factor=hi)))
    return out


def scaled_material(
    material: MembraneMaterial, stiffness: float = 1.0, weight: float = 1.0
) -> MembraneMaterial:
    """Copy of a fabric with scaled stiffnesses and areal mass (sources kept, noted).

    Parameters
    ----------
    material : MembraneMaterial
        Fabric.
    stiffness, weight : float
        Multipliers, -.

    Returns
    -------
    MembraneMaterial
        Scaled copy; the note of every scaled value records the factor.
    """

    def scale(v: MaterialValue, k: float) -> MaterialValue:
        if k == 1.0:
            return v
        return MaterialValue(
            v.value * k, v.unit, v.source, (v.note + f"; x{k:g} sensitivity").lstrip("; ")
        )

    return replace(
        material,
        stiffness_warp=scale(material.stiffness_warp, stiffness),
        stiffness_weft=scale(material.stiffness_weft, stiffness),
        shear_stiffness=scale(material.shear_stiffness, stiffness),
        areal_mass=scale(material.areal_mass, weight),
    )


def scaled_tape(tape: TapeMaterial, weight: float = 1.0) -> TapeMaterial:
    """Copy of a tape with scaled linear mass."""
    if weight == 1.0:
        return tape
    lm = tape.linear_mass
    return replace(
        tape,
        linear_mass=MaterialValue(
            lm.value * weight,
            lm.unit,
            lm.source,
            (lm.note + f"; x{weight:g} sensitivity").lstrip("; "),
        ),
    )


Metrics = dict[str, float]
Factory = Callable[[SweepSettings], tuple[SolverModel, Callable[[SimulationResult], Metrics]]]


@dataclass
class SweepRow:
    """One solved case.

    Attributes
    ----------
    parameter : str
        Swept parameter (``baseline`` for the baseline row).
    setting : str
        ``baseline``, ``low`` or ``high``.
    value : float
        Parameter value (unit from :data:`PARAMETERS`).
    converged : bool
        The solve converged.
    status : str
        Solver status.
    metrics : dict of str to float
        Report metrics (units in the keys).
    """

    parameter: str
    setting: str
    value: float
    converged: bool
    status: str
    metrics: Metrics


@dataclass
class SensitivityResult:
    """Baseline and one-at-a-time rows, all from the same solver.

    Attributes
    ----------
    solver : str
        Solver of every case (the preview solver unless another was given).
    rows : list of SweepRow
        Baseline first.
    """

    solver: str
    rows: list[SweepRow] = field(default_factory=list)

    @property
    def baseline(self) -> SweepRow:
        """The baseline row."""
        return self.rows[0]

    def sensitivities(self) -> list[dict[str, Any]]:
        """Per parameter and metric: low/high values and the slope (None if unconverged)."""
        out = []
        for name in PARAMETERS:
            lo = next((r for r in self.rows if r.parameter == name and r.setting == "low"), None)
            hi = next((r for r in self.rows if r.parameter == name and r.setting == "high"), None)
            if lo is None or hi is None:
                continue
            for metric in self.baseline.metrics:
                a, b = lo.metrics.get(metric, math.nan), hi.metrics.get(metric, math.nan)
                both = lo.converged and hi.converged and hi.value != lo.value
                out.append(
                    {
                        "parameter": name,
                        "metric": metric,
                        "low_value": lo.value,
                        "high_value": hi.value,
                        "metric_low": a,
                        "metric_baseline": self.baseline.metrics.get(metric, math.nan),
                        "metric_high": b,
                        "converged": both,
                        "slope": (b - a) / (hi.value - lo.value) if both else None,
                    }
                )
        return out

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "solver": self.solver,
            "parameters": {k: {"label": v[0], "unit": v[1]} for k, v in PARAMETERS.items()},
            "rows": [r.__dict__ for r in self.rows],
            "sensitivities": self.sensitivities(),
        }


def sensitivity_sweep(
    factory: Factory,
    base: SweepSettings,
    deltas: SweepDeltas | None = None,
    settings: SolverSettings | None = None,
    parameters: tuple[str, ...] | None = None,
) -> SensitivityResult:
    """Run the one-at-a-time sweep with the preview solver.

    Parameters
    ----------
    factory : callable
        ``factory(settings) -> (model, metrics)``: builds the solver model for a
        parameter set and returns a function computing the report metrics from a result.
    base : SweepSettings
        Baseline parameters.
    deltas : SweepDeltas, optional
        Low/high offsets.
    settings : SolverSettings, optional
        Preview solver settings.
    parameters : tuple of str, optional
        Subset of :data:`PARAMETERS` to sweep (default all).

    Returns
    -------
    SensitivityResult
        Baseline and case rows (preview results, never labelled verified).
    """
    out = SensitivityResult(solver="envelopelab-preview")

    def run(parameter: str, setting: str, s: SweepSettings) -> SweepRow:
        model, metrics = factory(s)
        res = from_preview(model, solve(model, settings))
        value = getattr(s, parameter) if parameter in PARAMETERS else math.nan
        return SweepRow(parameter, setting, float(value), res.converged, res.status, metrics(res))

    out.rows.append(run("baseline", "baseline", base))
    for parameter, setting, s in sweep_cases(base, deltas):
        if parameters is None or parameter in parameters:
            out.rows.append(run(parameter, setting, s))
    return out
