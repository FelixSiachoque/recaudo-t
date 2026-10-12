"""Experimento del compromiso: Seguridad (S1) vs. Desempeño.

La detección de clones corre dentro de cada validación, en el camino crítico.
Se mide cuánto aumenta la latencia de /validar en el servidor central con la
misma carga (viajes legítimos, 250 validaciones/s durante 30 s) en tres
condiciones, 3 repeticiones de cada una, en orden rotado para que el ruido de
la máquina afecte por igual a todas:
  * sin detección (línea base),
  * con detección y estado persistente en SQLite (la implementación real),
  * con detección y estado solo en memoria (referencia: costo del algoritmo).
Además se mide el costo aislado de MotorAntifraude.evaluar() (microbenchmark).
"""
import os
import time

from experimentos.metricas import (actualizar_resumen, carpeta, guardar_json, percentil,
                                   resumen_latencias)
from experimentos.procesos import URL, Sistema
from simuladores.carga import ejecutar, guardar_csv
from simuladores.usuarios import viajes_legitimos

TASA, DURACION, REPETICIONES = 250, 30, 3
CONDICIONES = {"sin_deteccion": {"ANTIFRAUDE": 0},
               "con_deteccion": {"ANTIFRAUDE": 1, "ANTIFRAUDE_PERSISTENCIA": "sqlite"},
               "con_deteccion_memoria": {"ANTIFRAUDE": 1, "ANTIFRAUDE_PERSISTENCIA": "memoria"}}


def peticiones(semilla):
    eventos = viajes_legitimos(TASA * DURACION // 2, semilla=semilla, prefijo="P")
    return [("POST", URL["central"] + "/validar",
             {**{k: e[k] for k in ("tarjeta", "estacion", "ts", "tipo", "franja")},
              "tx_id": f"P{semilla}-{i}"}, {}) for i, e in enumerate(eventos)]


def una_corrida(condicion, rep):
    d = carpeta("compromiso", f"{condicion}_rep{rep}")
    s = Sistema(d)
    try:
        s.iniciar("central", "recaudo.central", {**CONDICIONES[condicion], "TARIFAS_MODO": "config"})
        time.sleep(1)
        t = time.time()
        filas = ejecutar(peticiones(semilla=rep), TASA, hilos=64)
        dur = time.time() - t
    finally:
        s.detener_todo()
    guardar_csv(filas, os.path.join(d, "latencias.csv"))
    ok = [f["latencia_ms"] for f in filas if f["status"] in (200, 403)]
    r = resumen_latencias(ok)
    r.update({"condicion": condicion, "repeticion": rep,
              "throughput_rps": round(len(ok) / dur, 1),
              "no_procesadas": sum(1 for f in filas if f["status"] not in (200, 403))})
    guardar_json(r, os.path.join(d, "resultado.json"))
    return r, ok


def microbenchmark(n=100_000):
    """Costo por llamada de evaluar(), en memoria y con SQLite, fuera de HTTP."""
    import shutil
    import tempfile
    from recaudo import antifraude, comun
    res = {}
    for modo in ("memoria", "sqlite"):
        tmp = tempfile.mkdtemp()
        os.environ["ANTIFRAUDE_PERSISTENCIA"] = modo
        antifraude.DIR_LOGS = tmp
        motor = antifraude.MotorAntifraude(bitacora=comun.Bitacora("micro.jsonl"))
        eventos = viajes_legitimos(n // 2, semilla=99, prefijo="M")
        t = time.perf_counter()
        for e in eventos:
            motor.evaluar(e["tarjeta"], e["estacion"], e["ts"])
        res[modo] = round((time.perf_counter() - t) / len(eventos) * 1e6, 2)
        shutil.rmtree(tmp)
    os.environ.pop("ANTIFRAUDE_PERSISTENCIA", None)
    return res


def main():
    corridas, todas = [], {c: [] for c in CONDICIONES}
    orden = list(CONDICIONES)
    for rep in range(1, REPETICIONES + 1):
        for condicion in orden[rep - 1:] + orden[:rep - 1]:
            print(f"Compromiso – rep {rep}, {condicion}...")
            r, lat = una_corrida(condicion, rep)
            corridas.append(r)
            todas[condicion].extend(lat)
    res = {}
    for c in CONDICIONES:
        x = resumen_latencias(todas[c])
        rs = [k for k in corridas if k["condicion"] == c]
        x["throughput_rps"] = round(sum(k["throughput_rps"] for k in rs) / len(rs), 1)
        x["no_procesadas"] = sum(k["no_procesadas"] for k in rs)
        x["p95_por_repeticion"] = [k["p95_ms"] for k in rs]
        res[c] = x
    sin, con = res["sin_deteccion"], res["con_deteccion"]
    res.update({"corridas": corridas,
                "aumento_media_ms": round(con["media_ms"] - sin["media_ms"], 3),
                "aumento_p50_ms": round(con["p50_ms"] - sin["p50_ms"], 3),
                "aumento_p95_ms": round(con["p95_ms"] - sin["p95_ms"], 3),
                "aumento_p95_pct": round(100 * (con["p95_ms"] - sin["p95_ms"]) / sin["p95_ms"], 1),
                "aumento_p99_ms": round(con["p99_ms"] - sin["p99_ms"], 3),
                "costo_evaluar_us": microbenchmark(), "tasa_rps": TASA, "duracion_s": DURACION,
                "repeticiones": REPETICIONES})
    d = carpeta("compromiso", limpiar=False)
    guardar_json(res, os.path.join(d, "resultado.json"))
    guardar_csv(corridas, os.path.join(d, "corridas.csv"))
    actualizar_resumen("compromiso", res)
    print(f"  p95 sin={sin['p95_ms']} ms con={con['p95_ms']} ms (+{res['aumento_p95_pct']} %), "
          f"evaluar()={res['costo_evaluar_us']} µs")


if __name__ == "__main__":
    main()
