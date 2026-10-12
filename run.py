"""RECAUDO-T – comando único.

    python run.py               levanta todo el sistema (Ctrl+C para detener)
    python run.py experimentos  corre todos los experimentos y genera evidencias/
    python run.py pruebas       corre las pruebas de regresión de tarifas

Solo requiere Python 3.10+ (librería estándar). Las gráficas usan matplotlib
si está instalado (pip install matplotlib); sin él, se generan los CSV igual.
"""
import os
import signal
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)


def levantar():
    from experimentos.procesos import URL, Sistema
    s = Sistema(os.path.join(RAIZ, "logs"))

    def detener(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, detener)
    try:
        s.levantar()
        print("\nSistema RECAUDO-T arriba:")
        for k, u in URL.items():
            print(f"  {k:8s} {u}")
        print("\nPruebe:  python -m simuladores.usuarios --tarjetas 50")
        print("         python -m simuladores.atacante_clones --clonadas 20")
        print("Bitácoras en logs/. Ctrl+C para detener.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        s.detener_todo()


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else "sistema"
    if accion == "experimentos":
        sys.exit(subprocess.call([sys.executable, "-m", "experimentos.run_all"] + sys.argv[2:], cwd=RAIZ))
    elif accion == "pruebas":
        sys.exit(subprocess.call([sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=RAIZ))
    else:
        levantar()
