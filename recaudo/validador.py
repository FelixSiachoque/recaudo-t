"""Validador embarcado (bus / torniquete).

Recibe los toques de tarjeta de los usuarios (POST /tap) y los envía al
servidor central a través del enlace de comunicaciones.

TÁCTICA D2 – Reintentar (disponibilidad), activa con REINTENTO=1:
  * Si el central no responde, el validador NO rechaza al pasajero: acepta el
    pasaje en modo local, lo guarda en una cola persistente (archivo JSONL) y
    sigue operando.
  * Un hilo de reintento reenvía la cola en orden, con espera exponencial
    (0,25 s, 0,5 s, 1 s, 2 s como máximo) mientras el enlace siga caído.
  * Cada transacción lleva un tx_id único; el central descarta reenvíos
    repetidos (idempotencia), así que reintentar nunca cobra dos veces.
Con REINTENTO=0 (línea base) el pasaje se rechaza si no hay conexión.

También descarga la lista negra del central cada INTERVALO_LISTA_NEGRA segundos
(parte de la reacción de S1) para rechazar tarjetas revocadas sin consultar.
"""
import collections
import itertools
import json
import os
import threading
import time
import uuid

from .comun import DIR_LOGS, Bitacora, crear_servidor, env_bool, pedir

ID = os.environ.get("VALIDADOR_ID", "VA")
PUERTO = int(os.environ.get("PUERTO", "8101"))
CENTRAL = os.environ.get("CENTRAL_URL", "http://127.0.0.1:8001")
REINTENTO = env_bool("REINTENTO", "1")
TIMEOUT_ENVIO = float(os.environ.get("TIMEOUT_ENVIO", "1.0"))
INTERVALO_LISTA_NEGRA = float(os.environ.get("INTERVALO_LISTA_NEGRA", "2.0"))
ESPERA_BASE, ESPERA_MAX = 0.25, 2.0


class FallaRed(Exception):
    pass


class Validador:
    def __init__(self):
        self.bit = Bitacora(f"validador_{ID}.jsonl")
        self.ruta_cola = os.path.join(DIR_LOGS, f"cola_{ID}.jsonl")
        self.cola = collections.deque()
        self.lock = threading.Lock()
        self.contador = itertools.count(1)
        self.enlace_caido = False
        self.lista_negra, self.version_ln = set(), 0
        self.stats = collections.Counter()
        self._cargar_cola()

    # ---- cola persistente ----
    def _cargar_cola(self):
        if os.path.exists(self.ruta_cola):
            with open(self.ruta_cola, encoding="utf-8") as f:
                self.cola.extend(json.loads(l) for l in f if l.strip())
            if self.cola:
                self.bit.escribir("cola_recuperada_tras_reinicio", pendientes=len(self.cola))

    def _encolar(self, tx):
        self.cola.append(tx)
        with open(self.ruta_cola, "a", encoding="utf-8") as f:
            f.write(json.dumps(tx) + "\n")

    def _persistir_cola(self):
        with open(self.ruta_cola, "w", encoding="utf-8") as f:
            for tx in self.cola:
                f.write(json.dumps(tx) + "\n")

    # ---- comunicación con el central ----
    def _enviar(self, tx, timeout=TIMEOUT_ENVIO):
        try:
            status, resp = pedir("POST", CENTRAL + "/validar", tx, timeout=timeout)
        except OSError as e:
            raise FallaRed(str(e))
        if status in (502, 503, 504):
            raise FallaRed(f"HTTP {status}")
        return status, resp

    def _marcar_caido(self, motivo):
        if not self.enlace_caido:
            self.enlace_caido = True
            self.bit.escribir("falla_detectada", motivo=motivo, en_cola=len(self.cola))

    # ---- ruta /tap ----
    def tap(self, b, q):
        tx = {"tx_id": f"{ID}-{next(self.contador)}-{uuid.uuid4().hex[:8]}",
              "tarjeta": b["tarjeta"], "estacion": b["estacion"], "ts": b["ts"],
              "tipo": b.get("tipo", "general"), "franja": b.get("franja", "valle"),
              "transbordos": b.get("transbordos", 0), "validador": ID}

        if b["tarjeta"] in self.lista_negra:
            self.stats["rechazo_local_lista_negra"] += 1
            self.bit.escribir("rechazo_local_lista_negra", tarjeta=b["tarjeta"], tx_id=tx["tx_id"])
            return 403, {"estado": "rechazado", "motivo": "lista_negra_local", "tx_id": tx["tx_id"]}

        with self.lock:
            hay_pendientes = bool(self.cola)
        if REINTENTO and hay_pendientes:
            return self._aceptar_offline(tx)  # respeta el orden de la cola

        try:
            status, resp = self._enviar(tx)
            self.stats["en_linea"] += 1
            return status, {**resp, "tx_id": tx["tx_id"]}
        except FallaRed as e:
            self._marcar_caido(str(e))
            if not REINTENTO:
                self.stats["rechazo_sin_red"] += 1
                return 503, {"estado": "rechazado", "motivo": "sin_conexion", "tx_id": tx["tx_id"]}
            return self._aceptar_offline(tx)

    def _aceptar_offline(self, tx):
        tx["offline"] = True
        with self.lock:
            self._encolar(tx)
        self.stats["aceptado_offline"] += 1
        return 200, {"estado": "aceptado_offline", "tx_id": tx["tx_id"]}

    # ---- hilo de reintento ----
    def bucle_reintento(self):
        espera = ESPERA_BASE
        while True:
            with self.lock:
                tx = self.cola[0] if self.cola else None
            if tx is None:
                time.sleep(0.05)
                continue
            try:
                self._enviar(tx)
            except FallaRed as e:
                self.stats["reintentos_fallidos"] += 1
                self._marcar_caido(str(e))
                time.sleep(espera)
                espera = min(espera * 2, ESPERA_MAX)
                continue
            espera = ESPERA_BASE
            with self.lock:
                self.cola.popleft()
                self.stats["sincronizadas"] += 1
                vacia = not self.cola
                if vacia:
                    self._persistir_cola()
            if self.enlace_caido:
                self.enlace_caido = False
                self.bit.escribir("reconexion", pendientes=len(self.cola))
            if vacia:
                self.bit.escribir("cola_vacia", sincronizadas_total=self.stats["sincronizadas"])
            elif self.stats["sincronizadas"] % 200 == 0:
                with self.lock:
                    self._persistir_cola()

    # ---- hilo de lista negra ----
    def bucle_lista_negra(self):
        while True:
            try:
                status, d = pedir("GET", CENTRAL + "/lista_negra", timeout=1.0)
                if status == 200 and d["version"] != self.version_ln:
                    self.lista_negra, self.version_ln = set(d["tarjetas"]), d["version"]
                    self.bit.escribir("lista_negra_sincronizada", version=d["version"],
                                      tarjetas=len(d["tarjetas"]))
            except OSError:
                pass
            time.sleep(INTERVALO_LISTA_NEGRA)

    def estado(self, b, q):
        with self.lock:
            return 200, {"id": ID, "reintento": REINTENTO, "en_cola": len(self.cola),
                         "enlace_caido": self.enlace_caido, "version_lista_negra": self.version_ln,
                         **self.stats}

    def salud(self, b, q):
        return 200, {"ok": True, "id": ID}


def main():
    v = Validador()
    if REINTENTO:
        threading.Thread(target=v.bucle_reintento, daemon=True).start()
    threading.Thread(target=v.bucle_lista_negra, daemon=True).start()
    rutas = {("POST", "/tap"): v.tap, ("GET", "/estado"): v.estado, ("GET", "/salud"): v.salud}
    print(f"[validador {ID}] puerto {PUERTO} reintento={REINTENTO} central={CENTRAL}", flush=True)
    crear_servidor(PUERTO, rutas).serve_forever()


if __name__ == "__main__":
    main()
