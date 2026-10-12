"""Atacante: usa copias clonadas de tarjetas legítimas en otras estaciones.

Por cada tarjeta clonada, el titular hace sus viajes normales y el clon hace
otros viajes en estaciones al azar dentro de la misma hora. Ni el titular ni
el atacante saben dónde está el otro, igual que en la realidad.

Uso directo (con el sistema arriba):
    python -m simuladores.atacante_clones --clonadas 50
"""
import argparse
import random

from recaudo.antifraude import cargar_estaciones
from simuladores.carga import ejecutar
from simuladores.usuarios import T0, a_peticiones, distancia


def ataque(n_clonadas, usos_titular=2, usos_clon=2, semilla=7, ventana_s=3600):
    rnd = random.Random(semilla)
    est = cargar_estaciones()
    ids = list(est)
    eventos = []
    for k in range(n_clonadas):
        tarjeta = f"C{k:05d}"
        # titular: viajes con tiempos realistas
        a = rnd.choice(ids)
        t = T0 + rnd.uniform(0, ventana_s)
        for _ in range(usos_titular):
            eventos.append({"tarjeta": tarjeta, "estacion": a, "ts": round(t, 1),
                            "tipo": "general", "franja": "pico", "rol": "titular"})
            b = rnd.choice([x for x in ids if x != a])
            t += distancia(est, a, b) / 20 * 3600 + rnd.uniform(300, 1200)
            a = b
        # clon: usos en estaciones y momentos al azar dentro de la ventana
        for _ in range(usos_clon):
            eventos.append({"tarjeta": tarjeta, "estacion": rnd.choice(ids),
                            "ts": round(T0 + rnd.uniform(0, ventana_s), 1),
                            "tipo": "general", "franja": "pico", "rol": "clon"})
    eventos.sort(key=lambda e: e["ts"])
    return eventos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clonadas", type=int, default=50)
    ap.add_argument("--tasa", type=float, default=50)
    a = ap.parse_args()
    filas = ejecutar(a_peticiones(ataque(a.clonadas)), a.tasa)
    bloq = sum(f["status"] == 403 for f in filas if f["rol"] == "clon")
    print(f"usos del clon bloqueados: {bloq}/{sum(f['rol'] == 'clon' for f in filas)}")
