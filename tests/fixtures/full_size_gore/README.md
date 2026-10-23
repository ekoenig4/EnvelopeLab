# Generic full-size gore fixture (2600 m³)

`design.elproj` is a full-size standard-gore project made by
`tests/fixtures/generate_generic_fixtures.py full_size_gore`. It is the `smalley_90k`
natural shape (20 gores, cut between its mouth and vent stations) held at 2600 m³ envelope
volume, with 12 equal panel rows, 100 °C internal air at ISA sea level and a 400 kg
payload. The generic `standard_gore` fixture is 161 m³ with 8 gores; this one exercises
the solver at the size and gore count of a real envelope.

`tests/regression/test_full_size_fixture.py` checks the design and that the preview solve
converges.

This is test data, not a reference design, and passing these tests says nothing about its
airworthiness.
