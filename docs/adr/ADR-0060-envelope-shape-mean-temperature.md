# ADR-0060: Mean gas temperature from the envelope's shape (project format 10)

- Status: Accepted
- Date: 2026-11-24

## Context
The lift charts related the crown (top) temperature to the mean gas temperature by a
fixed, assumed offset of 20 K (ADR-0059). Lift depends on the volume-weighted mean of a
stratified gas, so the offset depends on where the envelope's volume lies in height,
which the design knows. A builder without temperature measurements asked for an estimate
that accounts for the envelope's shape and stays conservative.

## Decision
* New module `envelopelab.stratification` (level 1): the volume by height from the
  design's meridian profile (frustum per segment, scaled to the lofted volume) and an
  assumed linear temperature profile from mouth to crown, the mouth rise a fraction
  \(\varphi\) of the crown's rise above ambient (50 %, tagged assumed). The mean is the
  volume-weighted harmonic mean of the profile.
* The mean used is never less than a floor below the crown: the project's top-to-mean
  offset (20 K, tagged assumed) becomes that floor. The charts can therefore only become
  more conservative than with the fixed offset.
* This is the **default** (`LiftChartSettings.mean_model = "envelope_shape"`). The fixed
  offset stays available (`"fixed_offset"`). `mouth_excess` is a tagged setting.
* Project format **10** (the two settings). Versions 1 to 9 read with the defaults; the
  settings are written only when they differ from them.
* The stratified profile's pressure is computed and shown, but the structural solver keeps
  its uniform internal temperature (a separate, benchmarked change if adopted).

## Consequences
* Default lift-chart results change (a `physics` change): on the generic test envelopes
  the offset at the crown limit becomes 23–31 K instead of 20 K (ambient 30 to 0 °C) and
  the load at the limit falls by 4 % to 10 %.
* The profile's form and \(\varphi\) remain assumptions; a heat-balance model or a
  measured mid-height temperature would replace them. A measured value can be entered with
  its source tag.
* Projects written by this release cannot be opened by older releases (format 10).
