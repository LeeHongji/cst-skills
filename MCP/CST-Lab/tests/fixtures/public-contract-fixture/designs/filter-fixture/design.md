---
schema_version: 1
design_id: filter-fixture
topic_id: public-contract-fixture
title: Synthetic two-port contract fixture
model: model.py
ports: 2
acceptance:
- id: interior_return_loss
  metric: s1_1_db
  band_ghz:
  - 1.01
  - 1.09
  comparator: <
  threshold: -8.0
  mode: pointwise
  note: Synthetic threshold selected only to test contract parsing; not measured or
    paper-derived.
- id: interior_insertion_loss
  metric: s2_1_db
  band_ghz:
  - 1.01
  - 1.09
  comparator: '>'
  threshold: -1.0
  mode: pointwise
  note: Synthetic threshold selected only to test contract parsing; not measured or
    paper-derived.
- id: lower_transmission_zero
  metric: s2_1_db
  band_ghz:
  - 0.9
  - 0.99
  comparator: <
  threshold: -40.0
  mode: aggregate
  note: Synthetic threshold selected only to test contract parsing; not measured or
    paper-derived.
  aggregate: min
- id: upper_transmission_zero
  metric: s2_1_db
  band_ghz:
  - 1.15
  - 1.25
  comparator: <
  threshold: -40.0
  mode: aggregate
  note: Synthetic threshold selected only to test contract parsing; not measured or
    paper-derived.
  aggregate: min
---

Test gates do not describe the physical acceptance of the lowpass example.
