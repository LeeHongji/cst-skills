# Stepped-impedance lowpass / 阶梯阻抗低通

Internally specified two-port verification fixture, not a paper reproduction.
The source preserves the established neutral CST Automation model unchanged.
Length mm, frequency GHz; RO4003C er=3.55, h=0.813 mm, copper 0.035 mm.
TD/Hex solver, frequency 0–7.2 GHz, energy criterion -40 dB.
Acceptance: S21 > -1 dB throughout 0.1–1.5 GHz; S21 < -10 dB throughout
3.6–4.2 GHz. Adjustable parameter l3, proposed review range 13–15 mm; all
other dimensions fixed. These targets do not claim rigorous filter synthesis.

Create it with the bound runtime cst-research.py example --workspace ...
--topic ...; audit with verify-live.py --mode prepare. No approval is included.
