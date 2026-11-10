"""GeoBalance surface tools (author: Misghana; hand calculations).

Used by the agent next to GEMINI and as an independent cross-check of
GEMINI results. Units: MW, degC, m3/h, m, bar.

Every tool returns a dict with a 'warnings' list: limits are reported,
never silently capped, so the agent can see and fix them.

Given values come from the GEMINI challenge document; values marked
"our assumption" are ours and are listed in the report.
"""
import math

SURFACE_T = 12.0      # degC (given)
GRADIENT = 30.0       # degC/km (given)
RHO = 1030.0          # kg/m3 brine (given)
CP = 4000.0           # J/(kg K) brine, our assumption
MIN_FLOW, MAX_FLOW = 50.0, 300.0   # m3/h per doublet (given)
MAX_BRINE_DT = 40.0   # degC producer -> injector (given)
CO2_KG_PER_NM3 = 44.01 / 22.414    # kg CO2 per Nm3 of CH4 burned or CO2 released


def _mw(flow_m3h, dT):  # pylint: disable=invalid-name  # dT is the usual physics symbol
    """Heat carried by a brine flow: Q = (flow / 3600) x rho x cp x dT, in MW.

    Args:
        flow_m3h: brine flow in m3/h.
        dT: temperature drop of the brine in K (same as degC difference).
    """
    return flow_m3h / 3600 * RHO * CP * dT / 1e6


def _flow(mw, dT):  # pylint: disable=invalid-name  # dT is the usual physics symbol
    """Brine flow in m3/h needed to deliver `mw` MW with a temperature drop dT (K).

    This is the inverse of `_mw`.
    """
    return mw * 1e6 / (RHO * CP * dT) * 3600


def reservoir_temperature_c(depth_m=2500):
    """Reservoir temperature from the geothermal gradient.

    T = 12 degC + 30 degC/km x depth. Example: 2,500 m gives 87 degC,
    3,400 m gives 114 degC.

    Args:
        depth_m: true vertical depth of the reservoir in m.

    Returns:
        dict with 'temperature_c' and an empty 'warnings' list.
    """
    return {"temperature_c": SURFACE_T + GRADIENT * depth_m / 1000, "warnings": []}


def doublet_heat_mw(flow_m3h=300, brine_cooling_c=40):
    """Heat one doublet delivers when its brine is cooled by `brine_cooling_c`.

    Example: 300 m3/h cooled by 40 K gives about 13.7 MW.
    Warnings (no capping) if the flow is outside 50-300 m3/h or the brine
    cooling is above 40 K, the limits given in the challenge.

    Args:
        flow_m3h: brine flow per doublet in m3/h.
        brine_cooling_c: producer temperature minus injector temperature, in K.

    Returns:
        dict with 'heat_mw' and 'warnings'.
    """
    w = []
    if flow_m3h > MAX_FLOW:
        w.append(f"Flow {flow_m3h:.0f} m3/h > max {MAX_FLOW:.0f} m3/h per doublet")
    if 0 < flow_m3h < MIN_FLOW:
        w.append(f"Flow {flow_m3h:.0f} m3/h < min stable {MIN_FLOW:.0f} m3/h")
    if brine_cooling_c > MAX_BRINE_DT:
        w.append(f"Brine cooling {brine_cooling_c:.0f} C > max {MAX_BRINE_DT:.0f} C")
    return {"heat_mw": _mw(flow_m3h, brine_cooling_c), "warnings": w}


def heat_pump(heat_demand_mw, cop=3.0):
    """Split a heat-pump output into geothermal source heat and electricity.

    Energy balance: output = source heat + electricity, with
    electricity = output / COP. Example: 30 MW at COP 3 = 20 MW geothermal
    + 10 MW electricity. Warns if COP > 5, which is optimistic for 100 degC.

    Args:
        heat_demand_mw: heat the heat pump must deliver, in MW.
        cop: coefficient of performance (our assumption: 3.0).

    Returns:
        dict with 'geothermal_heat_mw', 'electricity_mw' and 'warnings'.
    """
    w = []
    if cop > 5.0:
        w.append(f"COP {cop} is optimistic for 100 C supply")
    return {"geothermal_heat_mw": heat_demand_mw * (cop - 1) / cop,
            "electricity_mw": heat_demand_mw / cop, "warnings": w}


def absorption_chiller(cooling_demand_mw, cop=0.7, t_in_c=87, drive_min_c=80, t_out_c=70):
    """Geothermal heat and brine flow needed by an absorption chiller.

    Heat in = cooling / COP. The brine enters at `t_in_c` and leaves at
    `t_out_c`. Example: 10 MW cooling at COP 0.7 needs 14.3 MW heat and
    about 735 m3/h brine (87 -> 70 degC). Warns if the brine is colder than
    the chiller drive temperature (80 degC).

    Args:
        cooling_demand_mw: cooling to deliver, in MW.
        cop: chiller COP (our assumption: 0.7, single effect).
        t_in_c: brine temperature into the chiller, degC.
        drive_min_c: lowest brine temperature that can drive the chiller, degC.
        t_out_c: brine temperature out of the chiller, degC.

    Returns:
        dict with 'geothermal_heat_mw', 'brine_flow_m3h', 'brine_out_c', 'warnings'.
    """
    w = []
    if t_in_c < drive_min_c:
        w.append(f"Brine {t_in_c:.0f} C below chiller drive temperature {drive_min_c:.0f} C")
    heat = cooling_demand_mw / cop
    dT = max(t_in_c - t_out_c, 0.1)  # pylint: disable=invalid-name  # avoid divide by zero
    return {"geothermal_heat_mw": heat, "brine_flow_m3h": _flow(heat, dT),
            "brine_out_c": t_out_c, "warnings": w}


def electric_chiller(cooling_demand_mw, cop=5.0):
    """Electricity an electric chiller needs: cooling / COP (our assumption: COP 5).

    Returns:
        dict with 'electricity_mw' and an empty 'warnings' list.
    """
    return {"electricity_mw": cooling_demand_mw / cop, "warnings": []}


def summer_cascade(cooling_mw, heating_mw, n_doublets=2,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                   flow_per_doublet=300, t_res_c=87, hp_cop=3.0):
    """Summer cascade: absorption chiller first, then heat pump on the cooler brine.

    Stage 1: the hot brine drives the absorption chiller (t_res -> 70 degC).
    Stage 2: the heat pump takes heat from 70 degC down to t_res - 40 degC.
    Cooling the chiller cannot cover goes to an electric chiller, with a warning.

    Args:
        cooling_mw: cooling demand, MW.
        heating_mw: heating demand, MW.
        n_doublets: number of doublets in operation.
        flow_per_doublet: brine flow per doublet, m3/h.
        t_res_c: brine temperature at the plant, degC.
        hp_cop: heat-pump COP.

    Returns:
        dict with absorption and electric cooling, chiller power,
        heat-pump electricity and 'warnings'.
    """
    w = []
    flow = n_doublets * flow_per_doublet
    if flow_per_doublet > MAX_FLOW:
        w.append("Flow per doublet above 300 m3/h")
    abs_cool = min(cooling_mw, _mw(flow, t_res_c - 70) * 0.7)
    elec_cool = cooling_mw - abs_cool
    hp_source = _mw(flow, 70 - (t_res_c - MAX_BRINE_DT))
    hp = heat_pump(heating_mw, hp_cop)
    if hp["geothermal_heat_mw"] > hp_source:
        w.append("Heat pump source heat exceeds stage-2 brine heat")
    if elec_cool > 0:
        w.append(f"{elec_cool:.1f} MW cooling not covered by absorption -> electric chiller")
    return {"absorption_cooling_mw": abs_cool, "electric_chiller_cooling_mw": elec_cool,
            "electric_chiller_power_mw": electric_chiller(elec_cool)["electricity_mw"],
            "heat_pump_electricity_mw": hp["electricity_mw"], "warnings": w}


def gas_engine(flow_m3h, glr=0.8, ch4_fraction=0.8,  # pylint: disable=too-many-arguments,too-many-positional-arguments
               lhv_kwh_nm3=9.97, el_eff=0.40, th_eff=0.45):
    """Burn the associated gas in a gas engine: electricity, heat and CO2.

    Gas flow = brine flow x GLR (0.8 Nm3/m3, given). Fuel power uses the
    methane part only (80%, given). All carbon in the gas ends up as CO2:
    burned CH4 plus the CO2 already in the gas (20%).

    Args:
        flow_m3h: total brine flow, m3/h.
        glr: gas-liquid ratio, Nm3 gas per m3 brine.
        ch4_fraction: methane fraction of the gas.
        lhv_kwh_nm3: lower heating value of methane, kWh/Nm3.
        el_eff: electric efficiency (our assumption: 40%).
        th_eff: heat recovery efficiency (our assumption: 45%).

    Returns:
        dict with 'electricity_mw', 'heat_mw', 'fuel_mw', 'co2_t_per_h', 'warnings'.
    """
    gas_nm3h = flow_m3h * glr
    fuel = gas_nm3h * ch4_fraction * lhv_kwh_nm3 / 1000
    co2_t_h = gas_nm3h * CO2_KG_PER_NM3 / 1000   # all carbon in the gas ends up as CO2
    return {"electricity_mw": fuel * el_eff, "heat_mw": fuel * th_eff,
            "fuel_mw": fuel, "co2_t_per_h": co2_t_h, "warnings": []}


def doublet_pressure_and_pump(flow_m3h=300, perm_md=200,  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
                              thickness_m=100, visc_pa_s=0.4e-3, spacing_m=1500, rw_m=0.1,
                              p_res_bar=250, depth_m=2500,  # pylint: disable=unused-argument
                              wellhead_bar=10, friction_bar=5, pump_eff=0.70):
    """Doublet pressures and pump power (70% efficiency). Limits from P. Andersen (UiS).

    Steady-state doublet (Darcy flow, no skin):
    dp_total = q x mu x ln(spacing / rw) / (pi x k x h).
    Half of dp_total is drawdown at the producer and half is build-up at the
    injector. Warnings if the producer drops below 75% of reservoir pressure
    or the injector rises above +25% (fracturing risk). Example: 300 m3/h in
    200 mD, 100 m thick reservoir needs about 52 bar in total.

    The reservoir pressure p_res_bar is also used as the static column pressure,
    so 250 bar is used consistently (given value). depth_m is kept so the
    agent can pass it, but the pressure already contains the depth effect.

    Args:
        flow_m3h: brine flow, m3/h.
        perm_md: permeability, mD.
        thickness_m: reservoir thickness, m.
        visc_pa_s: brine viscosity, Pa s.
        spacing_m: distance between producer and injector, m (our assumption).
        rw_m: well radius, m.
        p_res_bar: reservoir pressure, bar.
        depth_m: reservoir depth, m (not used in the formula).
        wellhead_bar: wanted producer wellhead pressure, bar (our assumption).
        friction_bar: friction loss per well, bar (our assumption).
        pump_eff: pump efficiency.

    Returns:
        dict with 'total_dp_bar', 'producer_bhp_bar', 'injector_bhp_bar',
        'pump_power_mw' and 'warnings'.
    """
    w = []
    k = perm_md * 9.869e-16          # mD -> m2
    q = flow_m3h / 3600              # m3/h -> m3/s
    dp_total = q * visc_pa_s * math.log(spacing_m / rw_m) / (math.pi * k * thickness_m) / 1e5
    p_prod = p_res_bar - dp_total / 2
    p_inj = p_res_bar + dp_total / 2
    if p_prod < 0.75 * p_res_bar:
        w.append(f"Producer BHP {p_prod:.0f} bar below 75% of reservoir pressure")
    if p_inj > 1.25 * p_res_bar:
        w.append(f"Injector BHP {p_inj:.0f} bar above +25% (fracturing risk)")
    static = p_res_bar
    dp_prod_pump = max(0, static + wellhead_bar + friction_bar - p_prod)
    dp_inj_pump = max(0, p_inj + friction_bar - static)
    pump_mw = q * (dp_prod_pump + dp_inj_pump) * 1e5 / pump_eff / 1e6
    return {"total_dp_bar": round(dp_total, 1), "producer_bhp_bar": round(p_prod, 1),
            "injector_bhp_bar": round(p_inj, 1), "pump_power_mw": round(pump_mw, 2),
            "warnings": w}


if __name__ == "__main__":
    print(reservoir_temperature_c())
    print(doublet_heat_mw(350))
    print(summer_cascade(cooling_mw=10, heating_mw=2.7))
    print(gas_engine(600))
    print(doublet_pressure_and_pump())
