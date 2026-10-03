# Designs from a shape file

A shape file stores a balloon shape as a normalized gore table, such as the Balloon
Builders Journal spreadsheets, together with the values that fix the design. Use it to
change one value and let EnvelopeLab work out the rest.

1. **File ▸ New design…**, tab **From shape file**, then **Browse…** to a shape file. An
   example is `tests/fixtures/smalley_90k/shape.yaml`. The file's own design is solved and
   shown at once.
2. The table lists every value: gore length, cut stations, volumes, height, diameters,
   tape length and the widest cut gore. Exactly **three** are ticked **Hold**; the rest are
   computed. Choose *SI* or *Imperial* units for display.
3. Change the design:
   * *Scale to a mouth diameter*: untick *Nominal volume*, type the mouth diameter (typing
     a value ticks Hold) and press **Solve**. The gore length is solved, and with it the
     volume and height. The shape stays the same.
   * *Same volume, different mouth*: keep *Nominal volume*, untick *Mouth station* and type
     the mouth diameter. The mouth is cut lower or higher on the same shape.
   * *Exact spreadsheet cut*: hold *Gore length* instead of the volume (see below).
4. Set the gore count, the seam allowance per gore edge, the number of panel rows and the
   fabric, then press **OK**. The result is an ordinary standard-gore design that opens in
   the editor with the same volume and height as the tab showed.

The status line says which values were solved and whether the solve **converged**. If a
target cannot be reached, for example a mouth wider than the shape allows, the status line
says **NOT CONVERGED** and gives the reachable range, and no design is made.

!!! note "Volume vs. the spreadsheet"
    EnvelopeLab integrates the volume of the smooth shape. The Balloon Builders Journal
    coefficient (0.12586 for the Smalley table) is about 0.15 % lower, so a design that holds
    the same volume has gores about 0.05 % (14 mm on a 27 m gore) shorter than the
    spreadsheet's. Hold the gore length to reproduce the spreadsheet's cut exactly.

A shape file can also define the gore **loft** (the lobe bulge between load tapes) along
the shape; the design gets it for its own cut, and the volumes in the table include it.

To write your own shape file, see the [format](../formats/shape-file.md).
