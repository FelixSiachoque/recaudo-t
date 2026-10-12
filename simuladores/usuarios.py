"""Usuarios legítimos: viajes con tiempos de desplazamiento realistas.

Uso directo (con el sistema arriba):
    python -m simuladores.usuarios --tarjetas 200 --tasa 20
"""
import argparse
import random

from recaudo.antifraude import cargar_estaciones
from simuladores.carga import ejecutar

T0 = 1_791_000_000  # inicio del reloj simulado (s)
VALIDADOR_POR_ZONA = {"VA": "http://127.0.0.1:8101", "VB": "http://127.0.0.1:8102"}


def validador_de(estacion):
    """E01-E06 los atiende el validador VA; E07-E12 el VB."""
    return "VA" if int(estacion[1:]) <= 6 else "VB"


def distancia(est, a, b):
    return ((est[a]["x"] - est[b]["x"]) ** 2 + (est[a]["y"] - est[b]["y"]) ** 2) ** 0.5


def viajes_legitimos(n_tarjetas, semilla=1, prefijo="L", ventana_s=3600):
    rnd = random.Random(semilla)
    est = cargar_estaciones()
    ids = list(est)
    eventos = []
    for k in range(n_tarjetas):
        tarjeta = f"{prefijo}{k:05d}"
        tipo = rnd.choice(["general", "general", "estudiante", "adulto_mayor"])
        a, b = rnd.sample(ids, 2)
        t1 = T0 + rnd.uniform(0, ventana_s)
        # velocidad comercial de 20 km/h más tiempo en la ciudad
        t2 = t1 + distancia(est, a, b) / 20 * 3600 + rnd.uniform(300, 1800)
        for estacion, t in ((a, t1), (b, t2)):
            eventos.append({"tarjeta": tarjeta, "estacion": estacion, "ts": round(t, 1),
                            "tipo": tipo, "franja": "pico", "rol": "legitimo"})
    eventos.sort(key=lambda e: e["ts"])
    return eventos


def a_peticiones(eventos, urls=VALIDADOR_POR_ZONA):
    pet = []
    for e in eventos:
        v = validador_de(e["estacion"])
        body = {k: e[k] for k in ("tarjeta", "estacion", "ts", "tipo", "franja")}
        pet.append(("POST", urls[v] + "/tap", body,
                    {"tarjeta": e["tarjeta"], "estacion": e["estacion"], "ts_sim": e["ts"],
                     "rol": e["rol"], "validador": v}))
    return pet


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tarjetas", type=int, default=100)
    ap.add_argument("--tasa", type=float, default=20)
    a = ap.parse_args()
    filas = ejecutar(a_peticiones(viajes_legitimos(a.tarjetas)), a.tasa)
    ok = sum(f["status"] == 200 for f in filas)
    print(f"{ok}/{len(filas)} validaciones aceptadas")
