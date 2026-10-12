"""Generador de carga de lazo abierto: envía peticiones a una tasa fija.

Cada petición queda registrada (momento de envío, latencia, código HTTP,
respuesta) para poder calcular las métricas a partir del CSV.
"""
import csv
import itertools
import threading
import time

from recaudo.comun import pedir


def ejecutar(peticiones, tasa, hilos=48, timeout=5.0):
    """peticiones: lista de (metodo, url, body, etiquetas:dict). Devuelve filas."""
    t0 = time.perf_counter() + 0.3
    indice = itertools.count()
    filas = [None] * len(peticiones)

    def trabajador():
        while True:
            i = next(indice)
            if i >= len(peticiones):
                return
            metodo, url, body, etiquetas = peticiones[i]
            espera = t0 + i / tasa - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
            ts_envio = time.time()
            ini = time.perf_counter()
            try:
                status, resp = pedir(metodo, url, body, timeout=timeout)
                error = ""
            except Exception as e:  # se registra, no se oculta
                status, resp, error = 0, {}, type(e).__name__
            lat_ms = (time.perf_counter() - ini) * 1000
            filas[i] = {"i": i, "ts_envio": round(ts_envio, 6), "latencia_ms": round(lat_ms, 3),
                        "status": status, "estado": resp.get("estado", ""),
                        "motivo": resp.get("motivo", ""), "valor": resp.get("valor", ""), "tx_id": resp.get("tx_id", ""),
                        "error": error, **etiquetas}

    ts = [threading.Thread(target=trabajador, daemon=True) for _ in range(hilos)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return filas


def guardar_csv(filas, ruta):
    if not filas:
        return
    campos = list(filas[0].keys())
    for f in filas:
        for k in f:
            if k not in campos:
                campos.append(k)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
