# Mesh shape to revolved profile

Module: `envelopelab.features.mesh_profile` (edit:
`envelopelab.project.edits.convert_mesh_to_revolved`).

A mesh (free-form) shape is a closed triangle mesh in its own frame: \(z\) along the
shape's axis out of the envelope, origin at the base point. When the mesh is round about
that axis, such as an antenna's stalk and ball, it can be replaced by a revolved shape.
Revolved shapes are cut into gores with exact seam lengths instead of flattened panels,
can be split across into tiers, and are edited by their profile.

## Fit

1. **Top.** The profile ends where the axis leaves the mesh: the largest height \(z_t\)
   of the triangles whose plan view contains the axis (barycentric coordinates of the
   origin in each triangle's plan).
2. **Sections.** Planes \(z = h\) cut the mesh at 240 heights (assumed) from the base
   circle \(h = 0\) to just below \(z_t\). Each cut is a set of segments \(j\) with length
   \(\ell_j\) and end radii \(\rho_{j,0}, \rho_{j,1}\); the section's radius is their
   length-weighted mean distance from the axis,

   \[ \bar\rho(h) = \frac{\sum_j \ell_j\,\tfrac12(\rho_{j,0} + \rho_{j,1})}{\sum_j \ell_j}. \]

3. **Points.** The curve \((\bar\rho(h), h)\), closed by the tip \((0, z_t)\), is
   resampled at \(n\) points equally spaced along its arc length (the base point and the
   tip included). The points are joined by the revolved shape's spline; if that spline
   would cross the axis, by straight segments.

## Deviation

Every mesh vertex with \(z \ge 0\) is compared with the fitted revolved surface: the
distance of \((\sqrt{x^2 + y^2},\ z)\) from the profile curve in the meridian plane. The
largest and RMS distances measure both the fit and how far the mesh is from round, and
are always shown before converting. A largest deviation above 5 % (assumed) of the widest
radius is reported as *not round*: an ear, a face or a mushroom cap that overhangs its
stem is not a surface of revolution, and converting it changes its shape.

More points follow the mesh more closely. For a stalk-and-ball antenna with sharp
corners in its outline, the largest deviation is about 9 % of the widest radius with 8
points, 5 % with 12 and 2.4 % with 24 (`tests/unit/test_mesh_profile.py`); a smooth
outline needs fewer.

## Assumptions and valid range

* The axis of revolution is the shape's own axis through its base point, as the mesh was
  placed; a mesh modelled off that axis is refused.
* Each section is one loop round the axis.
* The mesh's facets are taken as the surface: a coarse mesh is fitted as the polyhedron it
  is.

## Conversion

The mesh shape is replaced by a revolved shape with the same name, placement, fabric,
feed holes, cap, seam turn, panel widths, group and mirror link; its panels become gores
(at least 3). The edit is one undo step, which brings the mesh back. A linked mirror twin
follows. The edit checks that the profile makes a valid revolved shape (base on the base
circle, every point but the tip off the axis) before it changes anything.

References: J. O'Rourke, *Computational Geometry in C*, 2nd ed., Cambridge University
Press, 1998 (plane sections of polyhedra); M. P. do Carmo, *Differential Geometry of
Curves and Surfaces*, Prentice-Hall, 1976 (surfaces of revolution).
