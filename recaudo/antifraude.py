"""TÁCTICA S1 – Detectar ataques + Revocar acceso (seguridad).

Detección: una tarjeta clonada comparte el número con la original, así que en
el momento de leerla no se distinguen. Se distinguen por el patrón de uso: si
la misma tarjeta aparece en dos estaciones separadas por una distancia que no
se puede recorrer en el tiempo transcurrido (velocidad > VELOCIDAD_MAXIMA),
alguna de las dos es un clon.

Reacción: la tarjeta entra a la lista negra (con número de versión). El
servidor central rechaza cualquier uso posterior y los validadores descargan
la lista negra periódicamente para rechazarla localmente, incluso sin red.

Todo queda en la bitácora logs/seguridad.jsonl para poder reconstruir lo
ocurrido (qué tarjeta, dónde, cuándo, qué velocidad, qué se hizo).

Persistencia (ANTIFRAUDE_PERSISTENCIA): con "sqlite" (por defecto) el último
uso de cada tarjeta y la lista negra se escriben en una base SQLite en cada
validación, para que un reinicio del central no borre las tarjetas revocadas.
Con "memoria" solo se guardan en RAM (se usa para comparar el costo).
"""
import json
import math
import os
import sqlite3
import threading

from .comun import DIR_LOGS, RAIZ, Bitacora

VELOCIDAD_MAXIMA_KMH = float(os.environ.get("VELOCIDAD_MAXIMA_KMH", "80"))


def cargar_estaciones():
    with open(os.path.join(RAIZ, "config", "estaciones.json"), encoding="utf-8") as f:
        return json.load(f)["estaciones"]


class MotorAntifraude:
    def __init__(self, bitacora=None):
        self.estaciones = cargar_estaciones()
        self.bitacora = bitacora or Bitacora("seguridad.jsonl")
        self._lock = threading.Lock()
        self._ultimo_uso = {}  # tarjeta -> (estacion, ts_simulado)
        self.lista_negra = {}  # tarjeta -> version en que entró
        self.version = 0
        self.persistencia = os.environ.get("ANTIFRAUDE_PERSISTENCIA", "sqlite")
        self.db = None
        if self.persistencia == "sqlite":
            self._abrir_db(os.path.join(DIR_LOGS, "antifraude.db"))

    def _abrir_db(self, ruta):
        self.db = sqlite3.connect(ruta, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS ultimo_uso (tarjeta TEXT PRIMARY KEY, estacion TEXT, ts REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS lista_negra (tarjeta TEXT PRIMARY KEY, version INTEGER)")
        for tarjeta, est, ts in self.db.execute("SELECT tarjeta, estacion, ts FROM ultimo_uso"):
            self._ultimo_uso[tarjeta] = (est, ts)
        for tarjeta, v in self.db.execute("SELECT tarjeta, version FROM lista_negra"):
            self.lista_negra[tarjeta] = v
            self.version = max(self.version, v)
        if self.lista_negra:
            self.bitacora.escribir("lista_negra_restaurada", tarjetas=len(self.lista_negra))

    def _guardar_uso(self, tarjeta, estacion, ts):
        if self.db:
            self.db.execute("INSERT OR REPLACE INTO ultimo_uso VALUES (?, ?, ?)", (tarjeta, estacion, ts))

    def _guardar_revocacion(self, tarjeta, version):
        if self.db:
            self.db.execute("INSERT OR REPLACE INTO lista_negra VALUES (?, ?)", (tarjeta, version))

    def distancia_km(self, a, b):
        ea, eb = self.estaciones[a], self.estaciones[b]
        return math.hypot(ea["x"] - eb["x"], ea["y"] - eb["y"])

    def evaluar(self, tarjeta, estacion, ts, tx_id=None, validador=None):
        """Devuelve (permitido: bool, motivo: str|None)."""
        with self._lock:
            if tarjeta in self.lista_negra:
                self.bitacora.escribir("uso_bloqueado", tarjeta=tarjeta, estacion=estacion,
                                       ts_evento=ts, tx_id=tx_id, validador=validador)
                return False, "tarjeta_en_lista_negra"

            previo = self._ultimo_uso.get(tarjeta)
            self._ultimo_uso[tarjeta] = (estacion, ts)
            self._guardar_uso(tarjeta, estacion, ts)
            if previo is None:
                return True, None

            est_prev, ts_prev = previo
            dist = self.distancia_km(est_prev, estacion)
            dt = abs(ts - ts_prev)
            if dist == 0:
                return True, None
            velocidad = math.inf if dt == 0 else dist / (dt / 3600.0)
            if velocidad <= VELOCIDAD_MAXIMA_KMH:
                return True, None

            # Uso imposible: revocar la tarjeta en toda la red
            self.version += 1
            self.lista_negra[tarjeta] = self.version
            self._guardar_revocacion(tarjeta, self.version)
            self.bitacora.escribir(
                "clon_detectado", tarjeta=tarjeta, tx_id=tx_id, validador=validador,
                estacion_previa=est_prev, estacion_actual=estacion,
                ts_evento_previo=ts_prev, ts_evento=ts, distancia_km=round(dist, 2),
                segundos_entre_usos=round(dt, 1),
                velocidad_kmh=None if velocidad == math.inf else round(velocidad, 1),
                accion="tarjeta_revocada", version_lista_negra=self.version,
                aviso_titular="enviado")
            return False, "uso_imposible_posible_clon"

    def exportar_lista_negra(self):
        with self._lock:
            return {"version": self.version, "tarjetas": list(self.lista_negra)}
