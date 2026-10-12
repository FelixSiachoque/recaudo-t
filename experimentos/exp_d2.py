"""Experimento D2 – Validador que sigue operando sin red (disponibilidad).

Un validador recibe 20 toques/s durante 120 s. En el segundo 30 se corta el
enlace con el central y se restablece en el segundo 90 (60 s de caída).
1200 toques durante la caída equivalen a unas 2 h de un bus real
(~10 validaciones por minuto), que es lo que pide la ficha.

Se corre sin la táctica (REINTENTO=0: rechaza si no hay red) y con ella
(REINTENTO=1: cola local + reenvío con espera exponencial + idempotencia).
"""
import collections
import os
import threading
import time

from experimentos.metricas import actualizar_resumen, carpeta, guardar_json, resumen_latencias
from experimentos.procesos import URL, Sistema
from recaudo.comun import leer_jsonl, pedir
from simuladores.carga import ejecutar, guardar_csv
from simuladores.usuarios import T0

TASA, DURACION, INICIO_FALLA, FIN_FALLA = 20, 120, 30, 90


def correr(reintento):
    d = carpeta("d2", "con_tactica" if reintento else "linea_base")
    n = TASA * DURACION
    peticiones = [("POST", URL["VA"] + "/tap",
                   {"tarjeta": f"D{i:05d}", "estacion": "E01", "ts": T0 + i / TASA,
                    "tipo": "general", "franja": "pico"}, {"tarjeta": f"D{i:05d}"})
                  for i in range(n)]
    s = Sistema(d)
    muestras, parar = [], threading.Event()

    def muestrear(t0):
        while not parar.is_set():
            try:
                v = pedir("GET", URL["VA"] + "/estado", timeout=1)[1]
                e = pedir("GET", URL["enlace"] + "/_control/stats", timeout=1)[1]
                muestras.append({"t_s": round(time.time() - t0, 2), "en_cola": v["en_cola"],
                                 "enlace_caido": int(v["enlace_caido"]), "falla_activa": int(e["falla"]),
                                 "reenviadas_validar": e["reenviadas_validar"], "cortadas": e["cortadas"]})
            except OSError:
                pass
            time.sleep(0.5)

    def inyectar_falla(t0):
        time.sleep(max(0, t0 + INICIO_FALLA - time.time()))
        pedir("POST", URL["enlace"] + "/_control/falla", {"activa": True})
        time.sleep(max(0, t0 + FIN_FALLA - time.time()))
        pedir("POST", URL["enlace"] + "/_control/falla", {"activa": False})

    try:
        s.levantar(antifraude=1, reintento=int(reintento), validadores=("VA",))
        t0 = time.time() + 0.3
        hilos = [threading.Thread(target=muestrear, args=(t0,), daemon=True),
                 threading.Thread(target=inyectar_falla, args=(t0,), daemon=True)]
        for h in hilos:
            h.start()
        filas = ejecutar(peticiones, TASA)
        # esperar a que la cola se vacíe (máximo 5 min, la meta de la ficha)
        limite = time.time() + 300
        while time.time() < limite and pedir("GET", URL["VA"] + "/estado")[1]["en_cola"] > 0:
            time.sleep(0.5)
        time.sleep(1.5)
        parar.set()
        if reintento:
            # Prueba de idempotencia: se simula que el validador perdió la
            # confirmación de 100 transacciones y las vuelve a enviar.
            for f in [f for f in filas if f["status"] == 200][:100]:
                i = int(f["tarjeta"][1:])
                pedir("POST", URL["enlace"] + "/validar",
                      {"tx_id": f["tx_id"], "tarjeta": f["tarjeta"], "estacion": "E01",
                       "ts": T0 + i / TASA, "tipo": "general", "franja": "pico",
                       "offline": True, "validador": "VA"})
        est_v = pedir("GET", URL["VA"] + "/estado")[1]
        est_e = pedir("GET", URL["enlace"] + "/_control/stats")[1]
        est_c = pedir("GET", URL["central"] + "/estado")[1]
    finally:
        parar.set()
        s.detener_todo()

    for f in filas:
        f["t_s"] = round(f["ts_envio"] - t0, 3)
    guardar_csv(filas, os.path.join(d, "toques.csv"))
    guardar_csv(muestras, os.path.join(d, "muestras_cola.csv"))

    enl = leer_jsonl(os.path.join(d, "enlace.jsonl"))
    val = leer_jsonl(os.path.join(d, "validador_VA.jsonl"))
    t_on = next(r["ts"] for r in enl if r["evento"] == "falla_on")
    t_off = next(r["ts"] for r in enl if r["evento"] == "falla_off")
    det = next((r["ts"] for r in val if r["evento"] == "falla_detectada" and r["ts"] >= t_on), None)
    reco = next((r["ts"] for r in val if r["evento"] == "reconexion" and r["ts"] >= t_off), None)
    vacia = next((r["ts"] for r in val if r["evento"] == "cola_vacia" and r["ts"] >= t_off), None)

    cobros = [r for r in leer_jsonl(os.path.join(d, "central_tx.jsonl")) if r["evento"] == "cobro"]
    cobros_por_tx = collections.Counter(r["tx_id"] for r in cobros)
    aceptados = [f for f in filas if f["status"] == 200]
    perdidas = [f for f in aceptados if f["tx_id"] not in cobros_por_tx]

    en_falla = [f for f in filas if t_on <= f["ts_envio"] <= t_off]
    res = {
        "reintento": bool(reintento),
        "toques": len(filas),
        "toques_aceptados": len(aceptados),
        "pct_aceptados": round(100 * len(aceptados) / len(filas), 2),
        "toques_durante_falla": len(en_falla),
        "pct_aceptados_durante_falla": round(100 * sum(f["status"] == 200 for f in en_falla) / max(1, len(en_falla)), 2),
        "rechazados_sin_red": sum(f["motivo"] == "sin_conexion" for f in filas),
        "duracion_falla_s": round(t_off - t_on, 2),
        "deteccion_falla_s": round(det - t_on, 3) if det else None,
        "reconexion_s": round(reco - t_off, 3) if reco else None,
        "sincronizacion_s": round(vacia - t_off, 3) if vacia else None,
        "max_en_cola": max((m["en_cola"] for m in muestras), default=0),
        "transacciones_perdidas": len(perdidas),
        "cobros_duplicados": sum(1 for c in cobros_por_tx.values() if c > 1),
        "reenvios_forzados_prueba_idempotencia": 100 if reintento else 0,
        "reenvios_descartados_por_idempotencia": est_c["duplicados_descartados"],
        "intentos_cortados_por_el_enlace": est_e["cortadas"],
        "reintentos_fallidos": est_v.get("reintentos_fallidos", 0),
        "peticiones_validar_al_central": est_e["reenviadas_validar"],
        "latencia_toque": resumen_latencias([f["latencia_ms"] for f in filas if f["status"] == 200]),
        "latencia_toque_durante_falla": resumen_latencias([f["latencia_ms"] for f in en_falla if f["status"] == 200]),
    }
    guardar_json(res, os.path.join(d, "resultado.json"))
    return res


def main():
    print("D2 – línea base (rechaza sin red)...")
    base = correr(0)
    print("D2 – con la táctica (cola local + reintento)...")
    tac = correr(1)
    actualizar_resumen("d2", {"linea_base": base, "con_tactica": tac})
    print(f"  base: {base['pct_aceptados']} % aceptados | táctica: {tac['pct_aceptados']} % aceptados, "
          f"sincronización {tac['sincronizacion_s']} s, perdidas {tac['transacciones_perdidas']}, "
          f"duplicados {tac['cobros_duplicados']}")


if __name__ == "__main__":
    main()
