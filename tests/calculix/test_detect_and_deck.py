"""Unit tests: CalculiX detection, deck writing and output parsing (mostly without ccx)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from calculix_adapter import (
    SETUP_MESSAGE,
    CalculixNotFoundError,
    CalculixRunError,
    CalculixSettings,
    find_calculix,
    require_calculix,
    run_calculix,
)
from calculix_adapter.analysis import describe_crash
from calculix_adapter.deck import DeckInput, LoadStep, _f, write_deck
from calculix_adapter.detect import ENV_VAR
from calculix_adapter.results import read_cvg, read_element_stress, steps_completed
from envelopelab.materials.membrane import MembraneMaterial
from envelopelab.solvers.model import NodeConstraint, OperatingConditions, SolverModel
from envelopelab.validation.meshes import sheet


def test_missing_ccx_gives_the_setup_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "no-such-ccx"))
    assert find_calculix() is None
    with pytest.raises(CalculixNotFoundError) as info:
        require_calculix()
    assert "apt-get install calculix-ccx" in str(info.value)
    assert "ENVELOPELAB_CCX" in SETUP_MESSAGE
    mesh = sheet(1.0, 1.0, 1, 1)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        MembraneMaterial.isotropic("f", 1e5),
        OperatingConditions(1.2, 1.2, self_weight=False),
        constraints=[NodeConstraint("all", np.arange(4))],
    )
    with pytest.raises(CalculixNotFoundError):
        run_calculix(model)


def test_envelopelab_core_does_not_import_the_adapter() -> None:
    import subprocess
    import sys

    code = (
        "import sys, envelopelab.solvers.dynamic_relaxation, envelopelab.assembly.pipeline, "
        "envelopelab.validation.comparison; print('calculix_adapter' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_reals_always_carry_a_decimal_point() -> None:
    assert _f(1000.0) == "1000."
    assert _f(-3.0) == "-3."
    assert _f(0.25) == "0.25"
    assert "e" in _f(1e-9)


def _deck(**kw: object) -> DeckInput:
    mesh = sheet(1.0, 1.0, 1, 1)
    m, n = len(mesh.triangles), len(mesh.positions)
    axes = np.tile(np.eye(3), (m, 1, 1))
    loads = np.zeros((n, 3))
    loads[2, 2] = 5.0
    base = dict(
        reference=mesh.positions,
        triangles=mesh.triangles,
        axes=axes,
        material=np.tile([[1e5, 2.4e4, 1e3], [2.4e4, 8e4, -2e3], [1e3, -2e3, 5e3]], (m, 1, 1)),
        transverse=np.full(m, 1e5),
        initial_stress=np.zeros((m, 3, 3)),
        steps=[LoadStep("inflation", loads)],
        tape_edges=np.array([[0, 1]]),
        tape_rest=np.array([1.0]),
        tape_ref=np.array([1.0]),
        tape_ea=np.array([5e4]),
        fixed=[(0, 1), (0, 2), (0, 3)],
    )
    base.update(kw)
    return DeckInput(**base)  # type: ignore[arg-type]


def test_deck_contains_every_model_part(tmp_path: Path) -> None:
    text = write_deck(_deck(), tmp_path / "a.inp").read_text()
    assert "*ELEMENT,TYPE=M3D3,ELSET=EFABRIC" in text
    assert text.count("*ORIENTATION") == 2  # one per element
    assert text.count("*MEMBRANE SECTION") == 2
    # 21 anisotropic constants (per mm thickness: resultant / 1e-3 m), coupling kept.
    assert (
        "*ELASTIC,TYPE=ANISO\n100000000.,24000000.,80000000.,0.,0.,100000000.,1000000.,-2000000."
        in text
    )
    assert "\n0.,5000000.,0.,0.,0.,0.,100000000.,0.\n0.,0.,0.,0.,100000000.\n" in text
    assert "*SPRING,ELSET=T1,NONLINEAR" in text
    assert "*INITIAL CONDITIONS,TYPE=STRESS" in text
    assert "*DLOAD" not in text  # pressure enters as nodal loads (M3D3 + P crashes ccx)
    assert "3,3,5." in text
    assert "1,1,1,0." in text and "SPRING1" not in text
    assert text.count("*STEP,NLGEOM") == 1 and "U,RF" in text


def test_release_deck_starts_balanced_and_adds_springs(tmp_path: Path) -> None:
    n = 4
    start, end = np.zeros((n, 3)), np.zeros((n, 3))
    start[3, 0] = 2.0
    end[2, 2] = 5.0
    steps = [LoadStep("balanced start", start, instant=True), LoadStep("release", end)]
    text = write_deck(_deck(steps=steps, stabilization=1e3), tmp_path / "b.inp").read_text()
    assert text.count("*STEP,NLGEOM") == 2
    first, second = text.split("** step: release")
    assert "AMPLITUDE=STEP" in first and "4,1,2." in first
    assert "AMPLITUDE=STEP" not in second
    assert "3,3,5." in second and "4,1," not in second
    assert "*AMPLITUDE" not in text  # CalculiX's RF output ignores amplitude loads
    assert text.count("*ELEMENT,TYPE=SPRING1") == 3
    assert "\n1000.\n" in text
    # Output is requested only in the last step.
    assert "U,RF" not in first and "U,RF" in second


def test_held_deck_fixes_every_node_without_springs(tmp_path: Path) -> None:
    text = write_deck(_deck(hold_all=True, stabilization=1e3), tmp_path / "c.inp").read_text()
    assert "NALL,1,3,0." in text
    assert "SPRING1" not in text


def test_oblique_symmetry_plane_becomes_an_equation(tmp_path: Path) -> None:
    normal = np.array([1.0, 1.0, 0.0]) / np.sqrt(2.0)
    axis = np.array([0.0, 1.0, 0.0])
    deck = _deck(equations=[(1, normal), (2, axis)])
    text = write_deck(deck, tmp_path / "d.inp").read_text()
    assert "*EQUATION\n2\n2,1,0.707106781187,2,2,0.707106781187" in text
    assert "3,2,2,0." in text


def test_parsers_read_the_last_block(tmp_path: Path) -> None:
    dat = tmp_path / "x.dat"
    dat.write_text(
        " stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) for set E and time 0.5\n\n"
        "         1   1  1.0E+00  0.0 0.0 0.0 0.0 0.0\n"
        "         1   2  1.0E+00  0.0 0.0 0.0 0.0 0.0\n\n"
        " stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) for set E and time 1.0\n\n"
        "         1   1  2.0E+00  4.0 0.0 1.0 0.0 0.0\n"
        "         1   2  4.0E+00  4.0 0.0 1.0 0.0 0.0\n"
    )
    s = read_element_stress(dat, 1)
    assert s[0, 0, 0] == pytest.approx(3.0)
    assert s[0, 0, 1] == s[0, 1, 0] == pytest.approx(1.0)
    sta = tmp_path / "x.sta"
    sta.write_text(
        "SUMMARY OF JOB INFORMATION\n"
        "  STEP      INC     ATT  ITRS     TOT TIME     STEP TIME      INC TIME\n"
        "     1          1     1     3  0.100000E+01  0.100000E+01  0.100000E+01\n"
        "     2          1     1     2  0.150000E+01  0.500000E+00  0.500000E+00\n"
    )
    assert steps_completed(sta, 1)
    assert not steps_completed(sta, 2)
    assert read_cvg(tmp_path / "missing.cvg") == []


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script as a fake ccx")
def test_explicit_executable_and_version(tmp_path: Path) -> None:
    fake = tmp_path / "ccx"
    fake.write_text("#!/bin/sh\necho 'This is Version 2.99'\n")
    fake.chmod(0o755)
    found = find_calculix(fake)
    assert found is not None and found.version == "2.99"


@pytest.mark.parametrize(
    ("code", "words"),
    [
        (-11, "segmentation fault (SIGSEGV)"),
        (-9, "killed (SIGKILL)"),
        (-6, "aborted (SIGABRT)"),
        (0xC0000005, "access violation (0xC0000005)"),
        (0xC00000FD, "stack overflow (0xC00000FD)"),
        (-1073741819, "access violation (0xC0000005)"),  # same status, signed
    ],
)
def test_crash_exit_codes_are_named(code: int, words: str) -> None:
    assert words in (describe_crash(code) or "")


@pytest.mark.parametrize("code", [0, 1, 201])
def test_ordinary_exit_codes_are_not_crashes(code: int) -> None:
    assert describe_crash(code) is None


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script as a fake ccx")
def test_silent_crash_names_the_signal_and_keeps_the_files(tmp_path: Path) -> None:
    """A ccx that dies before printing anything still gives a usable error."""
    fake = tmp_path / "ccx"
    # Answers the version query, then dies like a crashed ccx: no output at all.
    fake.write_text(
        '#!/bin/sh\nif [ "$1" = "-v" ]; then echo "This is Version 2.21"; exit 0; fi\n'
        "kill -SEGV $$\n"
    )
    fake.chmod(0o755)
    mesh = sheet(1.0, 1.0, 1, 1)
    model = SolverModel.uniform(
        mesh.positions,
        mesh.triangles,
        mesh.rest_uv,
        MembraneMaterial.isotropic("f", 1e5),
        OperatingConditions(1.2, 1.2, self_weight=False),
        constraints=[NodeConstraint("all", np.arange(4))],
    )
    work = tmp_path / "work"
    with pytest.raises(CalculixRunError) as info:
        run_calculix(model, CalculixSettings(executable=str(fake)), workdir=work)
    message = str(info.value)
    assert "segmentation fault (SIGSEGV)" in message
    assert "printed nothing" in message
    assert str(work) in message
    assert (work / "job.inp").is_file()
    assert (work / "job.log").is_file()
