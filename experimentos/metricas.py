"""Cálculos de métricas a partir de los CSV y bitácoras de cada experimento."""
import json
import os
import shutil
import statistics

from recaudo.comun import RAIZ

DIR_EVIDENCIAS = os.path.join(RAIZ, "evidencias")


def carpeta(*partes, limpiar=True):
    d = os.path.join(DIR_EVIDENCIAS, *partes)
    if limpiar and os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    return d


def percentil(valores, p):
    """Percentil con interpolación lineal (mismo método que Excel PERCENTILE.INC)."""
    v = sorted(valores)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def resumen_latencias(lat_ms):
    if not lat_ms:
        return {}
    dif = [abs(a - b) for a, b in zip(lat_ms[1:], lat_ms[:-1])]
    return {
        "n": len(lat_ms),
        "media_ms": round(statistics.mean(lat_ms), 3),
        "p50_ms": round(percentil(lat_ms, 50), 3),
        "p95_ms": round(percentil(lat_ms, 95), 3),
        "p99_ms": round(percentil(lat_ms, 99), 3),
        "max_ms": round(max(lat_ms), 3),
        # jitter = variación promedio entre latencias consecutivas (como en RFC 3550)
        "jitter_ms": round(statistics.mean(dif), 3) if dif else 0.0,
        "desv_est_ms": round(statistics.pstdev(lat_ms), 3),
    }


def guardar_json(obj, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def actualizar_resumen(clave, valor):
    ruta = os.path.join(DIR_EVIDENCIAS, "resumen.json")
    datos = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    datos[clave] = valor
    guardar_json(datos, ruta)
