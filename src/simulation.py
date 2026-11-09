"""Simulación de eventos discretos (SimPy) del flujo de pacientes para escenarios what-if.

Idea: los pacientes llegan según la tasa horaria observada, siguen una trayectoria
(muestreada de las variantes reales) y en cada etapa esperan un recurso con capacidad
limitada; el tiempo de servicio se muestrea de las duraciones observadas por etapa.
"""
import numpy as np
import pandas as pd


def fit_inputs(ev: pd.DataFrame, visits: pd.DataFrame, start_col: str = "visit_start_datetime",
               top_variants: int = 15):
    """Extrae del dato real los insumos de la simulación."""
    # Tasa de llegada media por hora del día (pacientes/hora)
    arr = visits.groupby(visits[start_col].dt.floor("h")).size()
    arr = arr.reindex(pd.date_range(arr.index.min(), arr.index.max(), freq="h"), fill_value=0)  # incluye horas sin llegadas
    rate_by_hour = arr.groupby(arr.index.hour).mean().reindex(range(24), fill_value=0).to_dict()
    # Trayectorias y su probabilidad
    trace = ev.groupby("visit_occurrence_id")["etapa"].agg(tuple)
    vc = trace.value_counts().head(top_variants)
    routes, probs = list(vc.index), (vc / vc.sum()).values
    # Tiempos de servicio empíricos por etapa (horas, sin negativos)
    service = {s: g["duracion_h"].clip(lower=0).dropna().values
               for s, g in ev.groupby("etapa")}
    return rate_by_hour, routes, probs, service


def estimate_capacity(ev: pd.DataFrame, q: float = 1.0) -> dict:
    """Capacidad inferida = ocupación máxima observada por etapa (q=1.0). Supuesto a declarar;
    reemplazar por capacidad real (camas, consultorios) si el hospital la entrega."""
    from .flow import census
    occ = census(ev, "visit_detail_start_datetime", "visit_detail_end_datetime", freq="h", group="etapa")
    return occ.groupby("etapa")["ocupacion"].quantile(q).clip(lower=1).round().astype(int).to_dict()


def run(rate_by_hour: dict, routes: list, probs, service: dict, capacity: dict,
        days: int = 30, seed: int = 42, extra_capacity: dict | None = None) -> pd.DataFrame:
    """Corre la simulación y devuelve un registro por paciente-etapa con espera y servicio.

    Usa números aleatorios comunes: con la misma `seed`, base y escenario reciben exactamente
    los mismos pacientes, rutas y tiempos de servicio, así la diferencia se debe solo al cambio.
    Los primeros 3 días se descartan como calentamiento.
    """
    import simpy
    arr_rng = np.random.default_rng(seed)
    cap = {k: v + (extra_capacity or {}).get(k, 0) for k, v in capacity.items()}
    env = simpy.Environment()
    res = {s: simpy.Resource(env, capacity=int(cap.get(s, 1))) for s in service}
    log, warmup = [], 3 * 24
    lam_max = max(max(rate_by_hour.values()), 1e-6)

    def patient(pid, route):
        p_rng = np.random.default_rng([seed, pid])  # servicio propio de cada paciente
        for stage in route:
            dur = float(p_rng.choice(service[stage])) if len(service[stage]) else 0.0
            t0 = env.now
            with res[stage].request() as req:
                yield req
                wait = env.now - t0
                yield env.timeout(dur)
            if t0 >= warmup:
                log.append((pid, stage, t0, wait, dur))

    def arrivals():
        pid = 0
        while True:
            # Poisson no homogéneo por "thinning"
            yield env.timeout(arr_rng.exponential(1 / lam_max))
            if arr_rng.random() <= rate_by_hour.get(int(env.now) % 24, 0) / lam_max:
                route = routes[arr_rng.choice(len(routes), p=probs)]
                env.process(patient(pid, route))
                pid += 1

    env.process(arrivals())
    env.run(until=warmup + days * 24)
    return pd.DataFrame(log, columns=["paciente", "etapa", "llegada_h", "espera_h", "servicio_h"])


def run_reps(*args, reps: int = 10, **kwargs) -> pd.DataFrame:
    """Varias réplicas (semillas distintas) para estimar la variabilidad."""
    return pd.concat([run(*args, seed=s, **kwargs).assign(replica=s) for s in range(reps)],
                     ignore_index=True)


def calibrate(rate_by_hour, routes, probs, service, max_capacity: dict, real_wait: pd.Series,
              days: int = 30, seed: int = 42, max_rounds: int = 2):
    """Busca la 'capacidad efectiva' por etapa que reproduce la espera media real.

    Para cada etapa con espera observada, búsqueda binaria de la capacidad (entre 1 y la
    ocupación máxima) cuya espera simulada quede más cerca de la real, manteniendo fijas
    las demás. Se repite `max_rounds` veces porque las etapas se afectan entre sí.
    Devuelve (capacidad, tabla real vs. simulado).
    """
    cap = {k: int(v) for k, v in max_capacity.items()}
    targets = real_wait.dropna()
    targets = targets[targets.index.isin(cap)].sort_values(ascending=False)

    def sim_wait(c):
        return run(rate_by_hour, routes, probs, service, c, days=days, seed=seed) \
            .groupby("etapa")["espera_h"].mean()

    for _ in range(max_rounds):
        for stage, target in targets.items():
            lo, hi, best = 1, cap[stage], (np.inf, cap[stage])
            while lo <= hi:
                mid = (lo + hi) // 2
                w = sim_wait({**cap, stage: mid}).get(stage, 0.0)
                if abs(w - target) < best[0]:
                    best = (abs(w - target), mid)
                if w > target:      # demasiada espera → más capacidad
                    lo = mid + 1
                else:               # poca espera → menos capacidad
                    hi = mid - 1
            cap[stage] = best[1]

    final = sim_wait(cap)
    table = pd.DataFrame({"capacidad_max_obs": pd.Series(max_capacity), "capacidad_efectiva": pd.Series(cap),
                          "espera_real_h": real_wait, "espera_sim_h": final}).round(2)
    return cap, table


def compare(base: pd.DataFrame, scenario: pd.DataFrame) -> pd.DataFrame:
    """Compara espera media y P90 por etapa entre base y escenario."""
    f = lambda d: d.groupby("etapa")["espera_h"].agg(media="mean", p90=lambda x: x.quantile(0.9))
    b, s = f(base), f(scenario)
    out = b.join(s, lsuffix="_base", rsuffix="_escenario")
    out["reduccion_media_%"] = ((1 - out["media_escenario"] / out["media_base"]) * 100).round(1)
    return out.sort_values("media_base", ascending=False)
