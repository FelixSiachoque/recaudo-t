"""Corre todos los experimentos en orden y genera evidencias/ (≈ 15 minutos).

    python run.py experimentos            todo
    python run.py experimentos s1 d2      solo los indicados (m1, s1, d2, compromiso)
"""
import os
import sys
import time

from experimentos import exp_compromiso, exp_d2, exp_m1, exp_s1
from experimentos.metricas import DIR_EVIDENCIAS

EXPERIMENTOS = {"m1": exp_m1, "s1": exp_s1, "d2": exp_d2, "compromiso": exp_compromiso}


def main():
    elegidos = sys.argv[1:] or list(EXPERIMENTOS)
    os.makedirs(DIR_EVIDENCIAS, exist_ok=True)
    inicio = time.time()
    for nombre in elegidos:
        print(f"\n=== Experimento {nombre.upper()} ===")
        EXPERIMENTOS[nombre].main()
    try:
        from experimentos import graficas
        print("\n=== Gráficas ===")
        graficas.generar()
    except ImportError:
        print("matplotlib no está instalado: se omiten las gráficas (los CSV sí quedaron).")
    print(f"\nListo en {(time.time() - inicio) / 60:.1f} min. Resultados en evidencias/resumen.json")


if __name__ == "__main__":
    main()
