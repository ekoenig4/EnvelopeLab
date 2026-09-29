r"""Mass and material estimate for a gore envelope, and the resulting lift margin.

Every input material value is a :class:`~envelopelab.materials.MaterialProperty` so its
source tag (``datasheet | measured | assumed``) is carried into the result; nothing here has
a built-in material default.

Model
-----
* Fabric per zone: :math:`A_{cut} = N \sum_{rows\in zone} A_{cut,row}` and
  :math:`m = A_{cut}\, \mu_A`; the seam-allowance area is :math:`A_{cut} - A_{finished}`.
* Vertical tapes: one per gore seam, :math:`L_v = N \sum_{rows} \ell_{side}`.
* Horizontal tapes: one ring on each internal row boundary, length :math:`N w_{full}(s_k)`.
  Rim (mouth) and hole (top) tapes: rings at the first row's bottom and last row's top.
* Thread: :math:`L_t = c\,(n_v L_{seam,v} + n_h L_{seam,h})`, with :math:`c` the thread
  consumed per unit seam length per stitch row (lockstitch ≈ 2.5–3, both threads) and
  :math:`n` the stitch rows of each seam type.
* Parachute (:func:`estimate_parachute_mass`): fabric from the cut areas of its :math:`N_p`
  gores and centre disc; a radial tape on each of the :math:`N_p` radial seams
  (:math:`L = N_p \ell_{radial}`) and a rim tape round the edge; thread on the radial seams
  and the disc seam, as for the envelope.
* Lift margin: :math:`\Delta m = L/g - (m_{envelope} + m_{payload})`, with the parachute
  counted in the envelope mass.

Assumptions: fabric wastage between panels (nesting on the roll) is not included; tape
overlaps at ends and reinforcement patches are not included; thread mass uses the linear
density of the thread.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from envelopelab.atmosphere import G0, gross_lift
from envelopelab.geometry.gore import PanelRow
from envelopelab.geometry.parachute import ParachutePieces
from envelopelab.geometry.polygon import signed_area
from envelopelab.materials.repository import MaterialProperty


@dataclass(frozen=True)
class TapeMasses:
    """Linear mass of each tape class.

    Attributes
    ----------
    vertical, horizontal, rim, hole : MaterialProperty
        Linear mass, kg/m, with source tag.
    """

    vertical: MaterialProperty
    horizontal: MaterialProperty
    rim: MaterialProperty
    hole: MaterialProperty


@dataclass(frozen=True)
class ThreadSpec:
    """Sewing thread consumption.

    Attributes
    ----------
    linear_mass : MaterialProperty
        Thread linear mass, kg/m (1 tex = 1e-6 kg/m).
    consumption_ratio : MaterialProperty
        Thread length per unit seam length per stitch row, dimensionless.
    vertical_rows : int
        Stitch rows on each vertical (gore) seam.
    horizontal_rows : int
        Stitch rows on each horizontal seam.
    """

    linear_mass: MaterialProperty
    consumption_ratio: MaterialProperty
    vertical_rows: int
    horizontal_rows: int


@dataclass(frozen=True)
class ZoneEstimate:
    """Fabric use in one zone (all gores).

    Attributes
    ----------
    finished_area, cut_area : float
        Finished and cut fabric area, m^2.
    mass : float
        Fabric mass (cut area), kg.
    areal_mass : MaterialProperty
        Areal mass used, kg/m^2.
    """

    finished_area: float
    cut_area: float
    mass: float
    areal_mass: MaterialProperty

    @property
    def allowance_area(self) -> float:
        """Seam-allowance fabric area, m^2."""
        return self.cut_area - self.finished_area


@dataclass(frozen=True)
class MassEstimate:
    """Envelope mass breakdown.

    Attributes
    ----------
    zones : dict of str to ZoneEstimate
        Fabric per zone.
    tape_lengths, tape_masses : dict of str to float
        Per tape class (vertical, horizontal, rim, hole): length in m and mass in kg.
    vertical_seam_length, horizontal_seam_length : float
        Total seam lengths, m.
    thread_length, thread_mass : float
        Thread use, m and kg.
    sources : tuple of str
        Distinct source tags of every material value used.
    """

    zones: dict[str, ZoneEstimate]
    tape_lengths: dict[str, float]
    tape_masses: dict[str, float]
    vertical_seam_length: float
    horizontal_seam_length: float
    thread_length: float
    thread_mass: float
    sources: tuple[str, ...]

    @property
    def fabric_mass(self) -> float:
        """Total fabric mass, kg."""
        return sum(zone.mass for zone in self.zones.values())

    @property
    def total_mass(self) -> float:
        """Envelope mass (fabric + tapes + thread), kg."""
        return self.fabric_mass + sum(self.tape_masses.values()) + self.thread_mass


def estimate_mass(
    rows: Sequence[PanelRow],
    n_gores: int,
    row_zones: Sequence[str],
    zone_areal_mass: Mapping[str, MaterialProperty],
    tapes: TapeMasses,
    thread: ThreadSpec,
) -> MassEstimate:
    """Estimate envelope fabric, tape and thread quantities and mass.

    Parameters
    ----------
    rows : sequence of PanelRow
        Panel rows of one gore, mouth first (from :func:`~envelopelab.geometry.gore.split_rows`).
    n_gores : int
        Number of gores N.
    row_zones : sequence of str
        Zone name of each row.
    zone_areal_mass : mapping of str to MaterialProperty
        Fabric areal mass per zone, kg/m^2.
    tapes : TapeMasses
        Tape linear masses, kg/m.
    thread : ThreadSpec
        Thread linear mass (kg/m), consumption ratio and stitch rows.

    Returns
    -------
    MassEstimate
        Areas in m^2, lengths in m, masses in kg.
    """
    if not rows:
        raise ValueError("no panel rows")
    if len(row_zones) != len(rows):
        raise ValueError("row_zones and rows differ in length")
    missing = sorted(set(row_zones) - set(zone_areal_mass))
    if missing:
        raise ValueError(f"no areal mass for zone(s): {', '.join(missing)}")
    zones: dict[str, ZoneEstimate] = {}
    for zone in dict.fromkeys(row_zones):
        members = [row for row, z in zip(rows, row_zones, strict=True) if z == zone]
        finished = n_gores * sum(row.finished_area for row in members)
        cut = n_gores * sum(row.cut_area for row in members)
        areal = zone_areal_mass[zone]
        zones[zone] = ZoneEstimate(finished, cut, cut * areal.value, areal)
    vertical_seam = n_gores * sum(row.side_length for row in rows)
    horizontal_seam = n_gores * sum(row.top_width for row in rows[:-1])
    tape_lengths = {
        "vertical": vertical_seam,
        "horizontal": horizontal_seam,
        "rim": n_gores * rows[0].bottom_width,
        "hole": n_gores * rows[-1].top_width,
    }
    tape_props = {
        "vertical": tapes.vertical,
        "horizontal": tapes.horizontal,
        "rim": tapes.rim,
        "hole": tapes.hole,
    }
    tape_masses = {key: tape_lengths[key] * tape_props[key].value for key in tape_lengths}
    thread_length = thread.consumption_ratio.value * (
        thread.vertical_rows * vertical_seam + thread.horizontal_rows * horizontal_seam
    )
    used = [*zone_areal_mass.values(), *tape_props.values()]
    used += [thread.linear_mass, thread.consumption_ratio]
    return MassEstimate(
        zones=zones,
        tape_lengths=tape_lengths,
        tape_masses=tape_masses,
        vertical_seam_length=vertical_seam,
        horizontal_seam_length=horizontal_seam,
        thread_length=thread_length,
        thread_mass=thread_length * thread.linear_mass.value,
        sources=tuple(sorted({prop.source for prop in used})),
    )


@dataclass(frozen=True)
class ParachuteEstimate:
    """Parachute mass breakdown.

    Attributes
    ----------
    zones : dict of str to ZoneEstimate
        Fabric per zone (gores and centre disc), areas m^2, masses kg.
    tape_lengths, tape_masses : dict of str to float
        ``radial`` and ``rim`` tapes: length m, mass kg.
    seam_length : float
        Radial seams plus the disc seam, m.
    thread_length, thread_mass : float
        Thread use, m and kg.
    sources : tuple of str
        Distinct source tags of every material value used.
    """

    zones: dict[str, ZoneEstimate]
    tape_lengths: dict[str, float]
    tape_masses: dict[str, float]
    seam_length: float
    thread_length: float
    thread_mass: float
    sources: tuple[str, ...]

    @property
    def finished_area(self) -> float:
        """Finished parachute fabric area, m^2."""
        return sum(zone.finished_area for zone in self.zones.values())

    @property
    def fabric_mass(self) -> float:
        """Parachute fabric mass, kg."""
        return sum(zone.mass for zone in self.zones.values())

    @property
    def total_mass(self) -> float:
        """Parachute mass (fabric + tapes + thread), kg."""
        return self.fabric_mass + sum(self.tape_masses.values()) + self.thread_mass


def estimate_parachute_mass(
    pieces: ParachutePieces,
    gore_zone: str,
    centre_zone: str,
    zone_areal_mass: Mapping[str, MaterialProperty],
    radial_tape: MaterialProperty,
    rim_tape: MaterialProperty,
    thread: ThreadSpec,
) -> ParachuteEstimate:
    """Estimate parachute fabric, tape and thread quantities and mass.

    Parameters
    ----------
    pieces : ParachutePieces
        Finished and cut gore and centre-disc outlines, m.
    gore_zone, centre_zone : str
        Zone of the gores and of the centre disc.
    zone_areal_mass : mapping of str to MaterialProperty
        Fabric areal mass per zone, kg/m^2.
    radial_tape, rim_tape : MaterialProperty
        Linear mass of the radial-seam tapes and the rim tape, kg/m.
    thread : ThreadSpec
        Thread linear mass (kg/m) and consumption; radial and disc seams use its vertical
        stitch rows.

    Returns
    -------
    ParachuteEstimate
        Areas in m^2, lengths in m, masses in kg.
    """
    missing = sorted({gore_zone, centre_zone} - set(zone_areal_mass))
    if missing:
        raise ValueError(f"no areal mass for zone(s): {', '.join(missing)}")
    n = pieces.n_gores
    parts = [
        (
            gore_zone,
            n * abs(signed_area(pieces.gore_finished)),
            n * abs(signed_area(pieces.gore_cut)),
        ),
        (
            centre_zone,
            abs(signed_area(pieces.centre_finished)),
            abs(signed_area(pieces.centre_cut)),
        ),
    ]
    finished: dict[str, float] = {}
    cut: dict[str, float] = {}
    for zone, fa, ca in parts:
        finished[zone] = finished.get(zone, 0.0) + fa
        cut[zone] = cut.get(zone, 0.0) + ca
    zones = {
        z: ZoneEstimate(finished[z], cut[z], cut[z] * zone_areal_mass[z].value, zone_areal_mass[z])
        for z in finished
    }
    tape_lengths = {"radial": pieces.radial_seam_length, "rim": pieces.rim_length}
    tape_masses = {
        "radial": tape_lengths["radial"] * radial_tape.value,
        "rim": tape_lengths["rim"] * rim_tape.value,
    }
    seam = pieces.radial_seam_length + pieces.centre_circumference
    thread_length = thread.consumption_ratio.value * thread.vertical_rows * seam
    used = [zone_areal_mass[z] for z in zones] + [radial_tape, rim_tape]
    used += [thread.linear_mass, thread.consumption_ratio]
    return ParachuteEstimate(
        zones=zones,
        tape_lengths=tape_lengths,
        tape_masses=tape_masses,
        seam_length=seam,
        thread_length=thread_length,
        thread_mass=thread_length * thread.linear_mass.value,
        sources=tuple(sorted({prop.source for prop in used})),
    )


@dataclass(frozen=True)
class LiftMargin:
    """Lift available versus mass to be lifted.

    Attributes
    ----------
    gross_lift : float
        Gross lift, N.
    lift_mass : float
        Gross lift expressed as liftable mass L/g, kg.
    total_mass : float
        Envelope plus payload mass, kg.
    """

    gross_lift: float
    lift_mass: float
    total_mass: float

    @property
    def margin(self) -> float:
        """Spare liftable mass, kg (negative: the balloon cannot lift the load)."""
        return self.lift_mass - self.total_mass

    @property
    def ratio(self) -> float:
        """Lift-to-load ratio, dimensionless (>1 lifts)."""
        return self.lift_mass / self.total_mass


def lift_margin(
    volume: float,
    ambient_density: float,
    internal_density: float,
    envelope_mass: float,
    payload_mass: float,
    gravity: float = G0.value,
) -> LiftMargin:
    r"""Lift margin :math:`\Delta m = V(\rho_{amb}-\rho_{int}) - m_{env} - m_{payload}`.

    Parameters
    ----------
    volume : float
        Envelope volume, m^3.
    ambient_density, internal_density : float
        Densities, kg/m^3.
    envelope_mass : float
        Envelope mass, kg.
    payload_mass : float
        Everything else carried (basket, burners, fuel, occupants), kg.
    gravity : float, optional
        Gravitational acceleration, m/s^2.

    Returns
    -------
    LiftMargin
        Gross lift (N), liftable mass and total mass (kg).
    """
    if envelope_mass < 0.0 or payload_mass < 0.0:
        raise ValueError("masses must be non-negative")
    lift = gross_lift(volume, ambient_density, internal_density, gravity)
    return LiftMargin(lift, lift / gravity, envelope_mass + payload_mass)
