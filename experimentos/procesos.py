"""Arranca y detiene los procesos reales del sistema para cada experimento."""
import os
import subprocess
import sys
import time

from recaudo.comun import RAIZ, pedir

PUERTOS = {"central": 8000, "enlace": 8001, "VA": 8101, "VB": 8102}
URL = {k: f"http://127.0.0.1:{p}" for k, p in PUERTOS.items()}


class Sistema:
    def __init__(self, dir_logs):
        self.dir_logs = dir_logs
        os.makedirs(dir_logs, exist_ok=True)
        self.procs = {}

    def _env(self, extra):
        env = dict(os.environ)
        env.update({"DIR_LOGS": self.dir_logs, "PYTHONUNBUFFERED": "1"})
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def iniciar(self, nombre, modulo, env=None, esperar=True):
        salida = open(os.path.join(self.dir_logs, f"{nombre}.out"), "a")
        p = subprocess.Popen([sys.executable, "-m", modulo], cwd=RAIZ,
                             env=self._env({"PUERTO": PUERTOS[nombre], **(env or {})}),
                             stdout=salida, stderr=subprocess.STDOUT)
        self.procs[nombre] = p
        if esperar:
            self.esperar_listo(nombre)
        return p

    def esperar_listo(self, nombre, limite=10):
        ruta = "/_control/stats" if nombre == "enlace" else "/salud"
        fin = time.time() + limite
        while time.time() < fin:
            try:
                if pedir("GET", URL[nombre] + ruta, timeout=0.5)[0] == 200:
                    return time.time()
            except OSError:
                time.sleep(0.02)
        raise RuntimeError(f"{nombre} no arrancó")

    def detener(self, nombre):
        p = self.procs.pop(nombre, None)
        if p:
            p.terminate()
            p.wait(5)

    def detener_todo(self):
        for n in list(self.procs):
            self.detener(n)

    def levantar(self, antifraude=1, reintento=1, tarifas="config", validadores=("VA", "VB")):
        self.iniciar("central", "recaudo.central",
                     {"ANTIFRAUDE": antifraude, "TARIFAS_MODO": tarifas})
        self.iniciar("enlace", "recaudo.enlace", {"CENTRAL_URL": URL["central"]})
        for v in validadores:
            self.iniciar(v, "recaudo.validador",
                         {"VALIDADOR_ID": v, "REINTENTO": reintento, "CENTRAL_URL": URL["enlace"]})
