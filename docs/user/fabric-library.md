# Creating fabrics for all your designs

EnvelopeLab keeps your fabrics in one **fabric library** that belongs to you, not to a
design. A fabric you create once can be chosen for a material zone in every design you open,
now or later. Designs only store which fabric id each zone uses.

## Where the library is

The **Materials** panel shows the library file at the top. By default it is
`materials.sqlite` in the application data folder (for example
`~/.local/share/EnvelopeLab/EnvelopeLab/` on Linux). To use another file, for example
one on a shared drive, set **Preferences → Fabric library file** (takes effect at the next
start) or the environment variable `ENVELOPELAB_MATERIAL_LIBRARY`. The preference wins over
the variable.

If the file cannot be opened (damaged, or written by a newer EnvelopeLab), the application
says so at start and uses a temporary library with the example fabrics. Fabrics created
then are **not saved**; the file itself is left untouched.

## Creating a fabric

1. Open the **Materials** panel (in the **Patterns** mode, Ctrl+2).
2. Press **New fabric…**, or select a fabric and press **Duplicate…** to start from its
   values.
3. Enter an id (letters, digits, `_`, `.`, `-`; it cannot be changed later), a name and
   every value. Units are shown beside each field: areal mass g/m², moduli Pa, maximum
   service temperature °C, roll width m, seam efficiency 0–1.
4. Give **every** value a source tag and, if useful, a note:
    * `datasheet`: from the manufacturer's datasheet (note: product and revision);
    * `measured`: you tested it (note: test and date);
    * `assumed`: anything else. Results that depend on an assumed value are marked as
      such.
5. Press **OK**. Values that are not numbers, out of range (for example a seam efficiency
   above 1 or a negative areal mass) or unstable (Poisson's ratio² ≥ warp/weft modulus
   ratio) are listed and nothing is saved until they are fixed.

The new fabric appears in every zone's fabric list and in the new-design wizard.

## Using it in a design

In **Material zones of this design**, pick the fabric for each zone. The live outputs
(envelope mass, lift margin) use its areal mass straight away, and the 2D pattern view fills
the zone with its colour.

## Editing and deleting

Select one of your fabrics and press **Edit…** (or double-click it). The change applies to
**every design** that uses the fabric: simulations and nesting built from the old values
become **[STALE]** so you can re-run them. The design file itself is unchanged, so editing a
fabric never marks a project as having unsaved changes.

**Delete** asks first and names the zones of the open design that use the fabric. Designs
that still name a deleted fabric show it as missing (a tooltip in the zone list) and use the
documented assumed areal mass with a warning.

The three example fabrics (`ripstop_nylon`, `polyester`, `nomex`) are read-only
placeholders tagged `assumed - verify`. Duplicate one to make your own version.

## Sharing designs

A project file stores fabric ids, not fabric values. When you send a design to someone,
they need the same fabrics (same ids) in their library, or they will see the zones as
missing fabrics. Pointing both installations at the same library file (see above) is the
simplest way to share.

See also: [library file format](../formats/fabric-library.md),
[ADR-0009](../adr/ADR-0009-shared-fabric-library.md).
