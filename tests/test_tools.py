"""Tests for tools.py (author: Misghana).

Each test compares a tool with a result we know is correct: numbers given in
the challenge document, or simple hand calculations. Run from the
hackathon_geobalance folder with:  python -m pytest tests   (or: python tests/test_tools.py)

Test groups:
    1. Challenge document: the demand files give the published totals.
    2. Hand calculations: each tool matches a result worked out by hand.
    3. Limits: breaking a challenge limit gives a warning, never a silent cap.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)   # so the test finds tools.py one folder up

import tools  # noqa: E402  # pylint: disable=wrong-import-position,import-error

DATA = os.path.join(ROOT, "data")


def _read(name, col):
    """Read one numeric column from a CSV file in the data folder."""
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        return [float(r[col]) for r in csv.DictReader(f)]


# --- 1. Known results from the challenge document ----------------------------

def test_heating_demand_matches_document():
    """Heating file: 365 days, 30 MW peak and 111.67 GWh per year."""
    heat = _read("gemini_heating_demand_daily_2027.csv", "heating_demand_MWth")
    assert len(heat) == 365
    assert abs(max(heat) - 30.0) < 0.01                 # peak 30.0 MWth
    assert abs(sum(heat) * 24 / 1000 - 111.67) < 0.05   # MW x 24 h / 1000 = GWh


def test_cooling_demand_matches_document():
    """Cooling file: 365 days, 10 MW peak and 23.74 GWh per year."""
    cool = _read("gemini_cooling_demand_daily_2027.csv", "cooling_demand_MWcool")
    assert len(cool) == 365
    assert abs(max(cool) - 10.0) < 0.01                 # peak 10.0 MWcool
    assert abs(sum(cool) * 24 / 1000 - 23.74) < 0.05    # MW x 24 h / 1000 = GWh


def test_reservoir_temperature_from_gradient():
    """Gradient 30 degC/km from 12 degC: 87 degC at 2,500 m and 114 degC at 3,400 m."""
    assert tools.reservoir_temperature_c(2500)["temperature_c"] == 87.0   # 12 + 30 x 2.5
    assert tools.reservoir_temperature_c(3400)["temperature_c"] == 114.0  # 12 + 30 x 3.4


# --- 2. Hand calculations -----------------------------------------------------

def test_doublet_heat_hand_calc():
    """One doublet: 300 m3/h x 1030 kg/m3 x 4000 J/kgK x 40 K = 13.73 MW."""
    r = tools.doublet_heat_mw(300, 40)
    assert abs(r["heat_mw"] - 13.733) < 0.01
    assert not r["warnings"]          # 300 m3/h and 40 K are exactly at the limits


def test_heat_pump_energy_balance():
    """Heat pump at COP 3: 30 MW out = 20 MW geothermal + 10 MW electricity."""
    r = tools.heat_pump(30, cop=3.0)
    assert abs(r["electricity_mw"] - 10.0) < 1e-9
    assert abs(r["geothermal_heat_mw"] + r["electricity_mw"] - 30.0) < 1e-9


def test_absorption_chiller_needs_735_m3h_for_10_mw():
    """10 MW cooling at COP 0.7 needs 14.29 MW heat, about 735 m3/h brine (87 -> 70 degC)."""
    r = tools.absorption_chiller(10)
    assert abs(r["geothermal_heat_mw"] - 14.286) < 0.01
    assert abs(r["brine_flow_m3h"] - 734) < 2


def test_pressure_check_300_m3h_is_within_limits():
    """Darcy doublet: 300 m3/h needs about 52 bar, inside the pressure limits."""
    r = tools.doublet_pressure_and_pump(300)
    assert 50 < r["total_dp_bar"] < 55        # about 52 bar
    assert not r["warnings"]                  # inside the limits from P. Andersen


def test_gas_engine_returns_expected_keys():
    """Gas engine returns electricity, heat, CO2 and warnings, all with sensible signs."""
    r = tools.gas_engine(300)
    for key in ("electricity_mw", "heat_mw", "co2_t_per_h", "warnings"):
        assert key in r
    assert r["electricity_mw"] > 0 and r["co2_t_per_h"] > 0


# --- 3. Limits must give warnings, never silent caps -------------------------

def test_flow_above_max_gives_warning():
    """350 m3/h is above the 300 m3/h limit, so a warning is expected."""
    assert tools.doublet_heat_mw(350)["warnings"]


def test_flow_below_min_gives_warning():
    """30 m3/h is below the 50 m3/h minimum, so a warning is expected."""
    assert tools.doublet_heat_mw(30)["warnings"]


def test_brine_cooling_above_40_gives_warning():
    """Cooling the brine by 45 K breaks the 40 K limit, so a warning is expected."""
    assert tools.doublet_heat_mw(300, 45)["warnings"]


def test_low_permeability_breaks_pressure_limits():
    """With 50 mD instead of 200 mD the pressure limits are broken, so a warning is expected."""
    assert tools.doublet_pressure_and_pump(300, perm_md=50)["warnings"]


if __name__ == "__main__":
    # Run without pytest: call every test_ function and report the count.
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
    print(f"All {len(tests)} tests passed")
