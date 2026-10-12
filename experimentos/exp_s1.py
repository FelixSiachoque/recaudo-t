"""Experimento S1 – Detección de tarjetas clonadas (seguridad).

Ataque simulado: 200 tarjetas clonadas. El titular hace 2 viajes reales y el
clon 3 usos en estaciones y horas al azar: 1000 usos de tarjetas atacadas.
Se mezclan con 500 usuarios legítimos (1000 viajes) para medir falsos positivos.

Se corre dos veces: sin la táctica (ANTIFRAUDE=0) y con ella (ANTIFRAUDE=1).
Después se hace un barrido corto: % de clones detectados según cuántas veces
usa el atacante la tarjeta.
"""
import collections
import os
import time

from experimentos.metricas import actualizar_resumen, carpeta, guardar_json, percentil
from experimentos.procesos import URL, Sistema
from recaudo.comun import leer_jsonl, pedir
from simuladores.atacante_clones import ataque
from simuladores.carga import ejecutar, guardar_csv
from simuladores.usuarios import a_peticiones, viajes_legitimos

TASA = 100  # toques por segundo


def correr(antifraude, n_clonadas=200, usos_clon=3, n_legitimos=500, sub="", semilla=7):
    nombre = sub or ("con_tactica" if antifraude else "linea_base")
    d = carpeta("s1", nombre)
    eventos = ataque(n_clonadas, usos_titular=2, usos_clon=usos_clon, semilla=semilla)
    eventos += viajes_legitimos(n_legitimos, semilla=semilla + 1)
    eventos.sort(key=lambda e: e["ts"])

    s = Sistema(d)
    try:
        s.levantar(antifraude=antifraude)
        t_ini = time.time()
        filas = ejecutar(a_peticiones(eventos), TASA)
        dur = time.time() - t_ini
        time.sleep(3)  # deja que los validadores descarguen la última lista negra
        est_central = pedir("GET", URL["central"] + "/estado")[1]
    finally:
        s.detener_todo()
    guardar_csv(filas, os.path.join(d, "solicitudes.csv"))

    clonadas = {e["tarjeta"] for e in eventos if e["tarjeta"].startswith("C")}
    seg = leer_jsonl(os.path.join(d, "seguridad.jsonl"))
    detecciones = {r["tarjeta"]: r for r in seg if r["evento"] == "clon_detectado"}
    por_tx = {f["tx_id"]: f for f in filas if f["tx_id"]}

    # tiempo de detección: desde que el toque sale del simulador hasta el registro en bitácora
    t_det = [(r["ts"] - por_tx[r["tx_id"]]["ts_envio"]) * 1000
             for r in detecciones.values() if r.get("tx_id") in por_tx]

    # propagación: desde la detección hasta que TODOS los validadores tienen la tarjeta
    sincs = {v: [r for r in leer_jsonl(os.path.join(d, f"validador_{v}.jsonl"))
                 if r["evento"] == "lista_negra_sincronizada"] for v in ("VA", "VB")}
    t_prop = []
    for r in detecciones.values():
        tiempos = []
        for v, lista in sincs.items():
            t = next((x["ts"] for x in lista if x["version"] >= r["version_lista_negra"]), None)
            tiempos.append(None if t is None else t - r["ts"])
        if None not in tiempos:
            t_prop.append(max(tiempos))

    usos = collections.Counter()
    for f in filas:
        resultado = "aceptado" if f["status"] == 200 else ("bloqueado" if f["status"] == 403 else "otro")
        usos[(f["rol"], resultado)] += 1

    # usos del clon aceptados ANTES de la detección vs después
    det_ts = {t: r["ts"] for t, r in detecciones.items()}
    clon_aceptado_despues = sum(1 for f in filas if f["rol"] == "clon" and f["status"] == 200
                                and f["tarjeta"] in det_ts and f["ts_envio"] > det_ts[f["tarjeta"]] + 0.05)

    campos_bitacora = ("tarjeta", "estacion_previa", "estacion_actual", "distancia_km",
                       "segundos_entre_usos", "accion", "validador", "ts")
    reconstruibles = sum(all(c in r for c in campos_bitacora) for r in detecciones.values())

    res = {
        "antifraude": bool(antifraude),
        "usos_totales": len(filas),
        "duracion_s": round(dur, 1),
        "tarjetas_clonadas": len(clonadas),
        "clonadas_detectadas": len(clonadas & set(detecciones)),
        "pct_clonadas_detectadas": round(100 * len(clonadas & set(detecciones)) / len(clonadas), 1),
        "falsos_positivos": len(set(detecciones) - clonadas),
        "usos_legitimos": usos[("legitimo", "aceptado")] + usos[("legitimo", "bloqueado")],
        "usos_clon": sum(v for (rol, _), v in usos.items() if rol == "clon"),
        "usos_clon_aceptados": usos[("clon", "aceptado")],
        "usos_clon_bloqueados": usos[("clon", "bloqueado")],
        "pct_usos_clon_bloqueados": round(100 * usos[("clon", "bloqueado")] /
                                          max(1, sum(v for (rol, _), v in usos.items() if rol == "clon")), 1),
        "usos_clon_aceptados_tras_deteccion": clon_aceptado_despues,
        "usos_titular_bloqueados": usos[("titular", "bloqueado")],
        "deteccion_ms_p50": round(percentil(t_det, 50), 2) if t_det else None,
        "deteccion_ms_p95": round(percentil(t_det, 95), 2) if t_det else None,
        "deteccion_ms_max": round(max(t_det), 2) if t_det else None,
        "propagacion_s_p50": round(percentil(t_prop, 50), 2) if t_prop else None,
        "propagacion_s_max": round(max(t_prop), 2) if t_prop else None,
        "detecciones_propagadas_a_todos": len(t_prop),
        "registros_bitacora": len(seg),
        "detecciones_reconstruibles": reconstruibles,
        "lista_negra_central": est_central.get("lista_negra"),
    }
    guardar_json(res, os.path.join(d, "resultado.json"))
    if detecciones:
        with open(os.path.join(d, "muestra_bitacora.jsonl"), "w", encoding="utf-8") as f:
            import json
            for r in list(detecciones.values())[:5]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return res


def barrido():
    """% de tarjetas clonadas detectadas según cuántas veces usa el atacante el clon."""
    filas = []
    for usos in (1, 2, 3, 4, 5, 6):
        r = correr(1, n_clonadas=150, usos_clon=usos, n_legitimos=150,
                   sub=f"barrido_usos_{usos}", semilla=100 + usos)
        filas.append({"usos_clon": usos, "pct_detectadas": r["pct_clonadas_detectadas"],
                      "falsos_positivos": r["falsos_positivos"],
                      "usos_clon_aceptados": r["usos_clon_aceptados"],
                      "usos_clon_bloqueados": r["usos_clon_bloqueados"]})
        print(f"  barrido usos_clon={usos}: {r['pct_clonadas_detectadas']} % detectadas")
    guardar_csv(filas, os.path.join(carpeta("s1", "barrido", limpiar=False), "barrido_usos_clon.csv"))
    return filas


def main():
    print("S1 – línea base (sin detección)...")
    base = correr(0)
    print("S1 – con la táctica...")
    tac = correr(1)
    print("S1 – barrido por número de usos del clon...")
    bar = barrido()
    actualizar_resumen("s1", {"linea_base": base, "con_tactica": tac, "barrido": bar})
    print(f"  base: {base['pct_usos_clon_bloqueados']} % usos clon bloqueados | "
          f"táctica: {tac['pct_clonadas_detectadas']} % clonadas detectadas, "
          f"FP={tac['falsos_positivos']}, prop máx={tac['propagacion_s_max']} s")


if __name__ == "__main__":
    main()
