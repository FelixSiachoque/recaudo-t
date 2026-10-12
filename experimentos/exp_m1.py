"""Experimento M1 – Cambio de tarifas de la alcaldía (modificabilidad).

Cambio controlado (resolución ficticia de la alcaldía):
  * El pasaje de estudiante en hora valle baja de 2100 a 1950.
  * Se crea el tipo de usuario "discapacidad": 1600 en pico y 1500 en valle.

Se hace el MISMO cambio dos veces mientras el central atiende consultas
de tarifa a 50 solicitudes/s:
  * Línea base (TARIFAS_MODO=codigo): se edita recaudo/tarifas_codigo.py y hay
    que reiniciar el servicio para que el cambio entre en vigor.
  * Táctica (TARIFAS_MODO=config, diferir el enlace): se edita la copia de
    config/tarifas.json que lee el servicio; no se toca código ni se reinicia.

Se mide: archivos de código modificados, líneas modificadas (diff), si hubo
reinicio, tiempo desde el cambio hasta que la nueva tarifa responde,
solicitudes fallidas durante el cambio y regresiones en las tarifas que no
debían cambiar. El archivo de código se restaura al final.
"""
import difflib
import itertools
import json
import os
import shutil
import threading
import time

from experimentos.metricas import actualizar_resumen, carpeta, guardar_json
from experimentos.procesos import URL, Sistema
from recaudo.comun import RAIZ
from simuladores.carga import ejecutar, guardar_csv

TASA, DURACION, MOMENTO_CAMBIO = 50, 20, 6
RUTA_CODIGO = os.path.join(RAIZ, "recaudo", "tarifas_codigo.py")
RUTA_CONFIG = os.path.join(RAIZ, "config", "tarifas.json")

COMBOS = [(t, f) for t in ("general", "estudiante", "adulto_mayor", "discapacidad") for f in ("pico", "valle")]
ESPERADO_ANTES = {("general", "pico"): 3200, ("general", "valle"): 2950, ("estudiante", "pico"): 2250,
                  ("estudiante", "valle"): 2100, ("adulto_mayor", "pico"): 2000, ("adulto_mayor", "valle"): 1800}
ESPERADO_DESPUES = {**ESPERADO_ANTES, ("estudiante", "valle"): 1950,
                    ("discapacidad", "pico"): 1600, ("discapacidad", "valle"): 1500}
CAMBIADOS = {("estudiante", "valle"), ("discapacidad", "pico"), ("discapacidad", "valle")}


def cambio_en_codigo(texto):
    """Lo que haría un desarrollador a mano en el archivo de código."""
    texto = texto.replace(
        '            if franja == "pico":\n                return 2250\n            return 2100\n',
        '            if franja == "pico":\n                return 2250\n            return 1950\n')
    texto = texto.replace(
        '            return 1800\n        raise',
        '            return 1800\n        elif tipo == "discapacidad":\n'
        '            if franja == "pico":\n                return 1600\n            return 1500\n        raise')
    return texto


def cambio_en_config(texto):
    """Lo que haría un operador a mano en el archivo de configuración."""
    texto = texto.replace('"version": "2026-10-A"', '"version": "2026-11-B"')
    texto = texto.replace('"estudiante":   {"pico": 2250, "valle": 2100},',
                          '"estudiante":   {"pico": 2250, "valle": 1950},')
    texto = texto.replace('"adulto_mayor": {"pico": 2000, "valle": 1800}\n',
                          '"adulto_mayor": {"pico": 2000, "valle": 1800},\n'
                          '    "discapacidad": {"pico": 1600, "valle": 1500}\n')
    json.loads(texto)  # el archivo editado debe seguir siendo JSON válido
    return texto


def guardar_diff(antes, despues, nombre_archivo, ruta_diff):
    diff = list(difflib.unified_diff(antes.splitlines(True), despues.splitlines(True),
                                     fromfile=f"a/{nombre_archivo}", tofile=f"b/{nombre_archivo}"))
    with open(ruta_diff, "w", encoding="utf-8") as f:
        f.writelines(diff)
    agregadas = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    borradas = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return agregadas, borradas


def correr(modo):
    tactica = modo == "config"
    d = carpeta("m1", "con_tactica" if tactica else "linea_base")
    ciclo = itertools.cycle(COMBOS)
    peticiones = []
    for i in range(TASA * DURACION):
        t, f = next(ciclo)
        peticiones.append(("GET", URL["central"] + f"/tarifa?tipo={t}&franja={f}", None,
                           {"tipo": t, "franja": f}))

    env = {"TARIFAS_MODO": modo}
    if tactica:
        ruta_cfg = os.path.join(d, "tarifas_en_uso.json")
        shutil.copy(RUTA_CONFIG, ruta_cfg)
        env["TARIFAS_PATH"] = ruta_cfg
    original_codigo = open(RUTA_CODIGO, encoding="utf-8").read()

    s = Sistema(d)
    marcas = {}

    def aplicar_cambio(t0):
        time.sleep(max(0, t0 + MOMENTO_CAMBIO - time.time()))
        marcas["t_cambio"] = time.time()
        if tactica:
            antes = open(ruta_cfg, encoding="utf-8").read()
            despues = cambio_en_config(antes)
            marcas["lineas"] = guardar_diff(antes, despues, "config/tarifas.json",
                                            os.path.join(d, "cambio.diff"))
            with open(ruta_cfg, "w", encoding="utf-8") as f:
                f.write(despues)
            marcas["reinicio"] = False
        else:
            despues = cambio_en_codigo(original_codigo)
            marcas["lineas"] = guardar_diff(original_codigo, despues, "recaudo/tarifas_codigo.py",
                                            os.path.join(d, "cambio.diff"))
            with open(RUTA_CODIGO, "w", encoding="utf-8") as f:
                f.write(despues)
            # sin la táctica el cambio solo entra en vigor reiniciando el servicio
            marcas["t_parada"] = time.time()
            s.detener("central")
            s.iniciar("central", "recaudo.central", env, esperar=False)
            marcas["t_listo"] = s.esperar_listo("central")
            marcas["reinicio"] = True

    try:
        s.iniciar("central", "recaudo.central", env)
        t0 = time.time() + 0.3
        h = threading.Thread(target=aplicar_cambio, args=(t0,), daemon=True)
        h.start()
        filas = ejecutar(peticiones, TASA, hilos=16, timeout=2)
        h.join()
    finally:
        s.detener_todo()
        with open(RUTA_CODIGO, "w", encoding="utf-8") as f:
            f.write(original_codigo)  # restaurar el código original

    for f in filas:
        f["t_s"] = round(f["ts_envio"] - t0, 3)
    guardar_csv(filas, os.path.join(d, "consultas.csv"))
    valores = filas

    t_cambio = marcas["t_cambio"]
    nuevos = [f for f in valores if f["ts_envio"] >= t_cambio and (f["tipo"], f["franja"]) in CAMBIADOS
              and f["valor"] == ESPERADO_DESPUES[(f["tipo"], f["franja"])]]
    t_vigente = min((f["ts_envio"] for f in nuevos), default=None)
    caidas = [f for f in filas if f["status"] == 0]
    regresiones = [f for f in valores if (f["tipo"], f["franja"]) in ESPERADO_ANTES
                   and (f["tipo"], f["franja"]) not in CAMBIADOS and f["status"] == 200
                   and f["valor"] != ESPERADO_ANTES[(f["tipo"], f["franja"])]]
    res = {
        "modo": modo,
        "archivos_de_codigo_modificados": 0 if tactica else 1,
        "archivos_de_configuracion_modificados": 1 if tactica else 0,
        "lineas_agregadas": marcas["lineas"][0],
        "lineas_borradas": marcas["lineas"][1],
        "requirio_reinicio": marcas["reinicio"],
        "segundos_servicio_caido": round(marcas["t_listo"] - marcas["t_parada"], 3) if not tactica else 0.0,
        "segundos_hasta_tarifa_vigente": round(t_vigente - t_cambio, 3) if t_vigente else None,
        "solicitudes": len(filas),
        "solicitudes_fallidas_por_caida": len(caidas),
        "regresiones_en_tarifas_no_modificadas": len(regresiones),
    }
    guardar_json(res, os.path.join(d, "resultado.json"))
    return res


def main():
    print("M1 – línea base (tarifas en el código)...")
    base = correr("codigo")
    print("M1 – con la táctica (diferir el enlace)...")
    tac = correr("config")
    actualizar_resumen("m1", {"linea_base": base, "con_tactica": tac})
    print(f"  base: reinicio={base['requirio_reinicio']}, fallidas={base['solicitudes_fallidas_por_caida']}, "
          f"vigente en {base['segundos_hasta_tarifa_vigente']} s | táctica: fallidas="
          f"{tac['solicitudes_fallidas_por_caida']}, vigente en {tac['segundos_hasta_tarifa_vigente']} s")


if __name__ == "__main__":
    main()
