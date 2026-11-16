# Development roadmap

## v0.1 — preliminary DCM model
- Arbitrary number of secondary windings and named isolation groups
- Turns, inductance, estimated total gap and flux-density constraints
- Approximate RMS currents, wire selection and copper DC losses
- Tkinter GUI and JSON/CLI import/export
- ETD core geometry comparison and unit tests

## v0.2 — manufacture-aware winding layout
- Real bobbin catalogs and layer widths
- Wire/enamel grades, insulation layers, margins and barriers
- Isolated sections and winding order, taps and interleaving
- Physical winding fit, creepage/clearance checks as separate requirements

## v0.3 — losses and thermal predictions
- Material-specific ferrite-loss curves versus B, f and temperature
- AC copper resistance, proximity losses, gap fringing
- Thermal network and multi-objective cost/volume/loss ranking

## v0.4 — power-stage integration
- CCM and boundary mode
- Controller current limit and start-up conditions
- Rectifiers, output capacitors, preload, multi-output cross-regulation
- MOSFET overshoot, leakage inductance and RCD/TVS clamp analysis

## Validation
Real results must be cross-checked against manufacturer datasheets,
bench inductance measurements, primary-current waveforms, temperature rise,
insulation requirements and multiple loading combinations.
