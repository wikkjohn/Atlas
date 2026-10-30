"""Country reference data (Phase 23, roadmap Milestone C step 1).

`data.py` holds the reference data for the 120 countries of the target footprint and the
currencies they use, as version-controlled Python data; `masks.py` validates and generates
document numbers and postal codes from simple masks; `calendar.py` computes holidays and
business days; `loader.py` writes the data into the `countries` and `currencies` tables.

The data is compiled for the simulation. Codes, currencies, minor units, time zones,
calling codes and weekends follow the public standards; regulators and holidays are
recorded as best known; document-number and postal-code masks only approximate the real
formats (lengths and character classes) so that synthetic records look plausible. None of
it is authoritative for real-world use.
"""
