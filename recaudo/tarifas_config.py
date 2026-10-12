"""TÁCTICA M1 – Diferir el enlace (modificabilidad).

Las reglas tarifarias NO están en el código: se leen de config/tarifas.json
en tiempo de ejecución. El motor revisa la fecha de modificación del archivo
(como máximo cada INTERVALO_REVISION segundos) y, si cambió, lo vuelve a
cargar sin reiniciar el servicio. Si el archivo nuevo es inválido, se
conserva la versión anterior y se deja constancia en la bitácora.
"""
import json
import os
import threading
import time

from .comun import RAIZ, Bitacora

RUTA_DEFECTO = os.path.join(RAIZ, "config", "tarifas.json")
INTERVALO_REVISION = 0.5  # segundos


class ConfigInvalida(Exception):
    pass


def validar(datos):
    if not isinstance(datos.get("tarifas"), dict) or not datos["tarifas"]:
        raise ConfigInvalida("falta la sección 'tarifas'")
    for tipo, franjas in datos["tarifas"].items():
        for franja in ("pico", "valle"):
            v = franjas.get(franja)
            if not isinstance(v, int) or v < 0:
                raise ConfigInvalida(f"{tipo}.{franja} debe ser un entero >= 0")
    t = datos.get("transbordos", {})
    for k in ("primero", "segundo_o_mas"):
        if not isinstance(t.get(k), int) or t[k] < 0:
            raise ConfigInvalida(f"transbordos.{k} debe ser un entero >= 0")
    return datos


class TarifasConfig:
    modo = "config"

    def __init__(self, ruta=None):
        self.ruta = ruta or os.environ.get("TARIFAS_PATH", RUTA_DEFECTO)
        self.bitacora = Bitacora("tarifas.jsonl")
        self._lock = threading.Lock()
        self._mtime = None
        self._ultima_revision = 0.0
        self._datos = None
        self._recargar(forzar=True)

    @property
    def version(self):
        return self._datos.get("version", "?")

    def _recargar(self, forzar=False):
        mtime = os.path.getmtime(self.ruta)
        if not forzar and mtime == self._mtime:
            return
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = validar(json.load(f))
        except (ValueError, ConfigInvalida) as e:
            self.bitacora.escribir("tarifas_rechazadas", motivo=str(e))
            if self._datos is None:
                raise
            self._mtime = mtime  # no reintentar el mismo archivo malo
            return
        with self._lock:
            self._datos, self._mtime = datos, mtime
        self.bitacora.escribir("tarifas_cargadas", version=datos.get("version"))

    def _revisar_cambios(self):
        ahora = time.monotonic()
        if ahora - self._ultima_revision >= INTERVALO_REVISION:
            self._ultima_revision = ahora
            self._recargar()

    def calcular(self, tipo, franja, transbordos=0):
        self._revisar_cambios()
        datos = self._datos
        transbordos = int(transbordos)
        if transbordos == 1:
            return datos["transbordos"]["primero"]
        if transbordos >= 2:
            return datos["transbordos"]["segundo_o_mas"]
        if tipo not in datos["tarifas"]:
            raise ValueError(f"tipo de usuario desconocido: {tipo}")
        return datos["tarifas"][tipo]["pico" if franja == "pico" else "valle"]
