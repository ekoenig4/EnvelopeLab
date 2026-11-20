# Colouring the panels

The **Colours** mode lets you try colour schemes on every panel of the balloon: the
envelope's gores and rows and the pieces of every special shape. Colours are for display
only. They do not change fabrics, material zones, mass, patterns or simulations, and
painting never makes a result stale. Choose each panel's fabric in **Materials** as before.

## The balloon in 3D
Beside the grid the balloon is drawn in 3D, painted as you go (drag to turn, wheel to
zoom). With **Show on the 3D views** on (the default), the colours also appear in every
other 3D view: the balloon beside the Shape, Patterns and Rigging editors, Special shapes
▸ On the balloon, and the design surface and special shapes in 3D / Simulation. Panels
you have not coloured keep their usual fabric shades; turn the option off to see only the
fabric colours. Result colourings (stress, factor of safety) still replace them while
they are shown.

## The panel grid
The envelope is drawn as its gores side by side at their true flat width, cut at the row
seams, with gore numbers on top and row letters on the left. Each special shape follows on
the right as a grid: one column per gore or panel round the shape, one band per tier (`A`
at the rim, then one band above each horizontal split), and its cap as a band on top.

* **Wheel**: zoom about the pointer; **right or middle drag**: pan; **double click** or
  **Fit**: show everything again.
* Hold the pointer over a panel to see its name and colour. The panels a click would paint
  are outlined in orange.

## Tools
| Tool | Key | A click paints |
|---|---|---|
| Paint | P | the panel clicked; drag to paint every panel you pass over |
| Fill row | R | every panel of the row clicked (on a shape: every piece of the tier) |
| Fill gore | G | every row of the gore clicked (on a shape: every tier of the piece) |
| Eyedropper | I | nothing: it takes the panel's colour, then returns to the previous tool |

**Repeat every N gores** also paints every N-th gore round from the one clicked (on a
shape, every N-th piece), for repeating patterns such as alternating gores (2) or a
stripe in every fourth gore (4). **Fill everything** paints every panel; **Clear all**
removes every colour. Every paint is one step in **Edit ▸ Undo**.

## The colour picker
* **Current colour**: the large swatch and its code. Type a code such as `#4472c4` (or
  `4472c4`, `#47c`) and press Enter to use it. **No colour** makes clicks clear panels.
* **Theme colours**: ten base colours with lighter tints and darker shades below each.
* **Standard colours**: ten saturated colours.
* **Recent colours**: the last colours you painted with (kept between sessions).
* **Colours in this design**: every colour on the balloon, most used first. Right click
  one to replace it everywhere with the current colour, or to clear it.
* **More colours…**: any colour from a colour wheel, RGB, HSV or HTML code, or picked from
  anywhere on the screen.

## Saving
Colours are saved in the project file (format 8). A design with no coloured panel saves
as before. Removing a row or a shape keeps its colours until your next paint, so undoing
the removal brings them back.

Colours are not yet shown in the build pack.
