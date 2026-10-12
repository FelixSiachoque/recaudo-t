"""Servidor central de RECAUDO-T: valida pasajes, calcula la tarifa y descuenta el saldo.

Variables de entorno:
  PUERTO          puerto HTTP (8000)
  ANTIFRAUDE      1 = táctica S1 activa, 0 = línea base sin detección
  TARIFAS_MODO    config = táctica M1 (diferir el enlace), codigo = línea base
  SALDO_INICIAL   saldo con el que empieza cada tarjeta simulada (pesos)
"""
import os
import threading
import time

from .comun import Bitacora, crear_servidor, env_bool

PUERTO = int(os.environ.get("PUERTO", "8000"))
SALDO_INICIAL = int(os.environ.get("SALDO_INICIAL", "500000"))


class Central:
    def __init__(self):
        self.antifraude = None
        if env_bool("ANTIFRAUDE", "1"):
            from .antifraude import MotorAntifraude
            self.antifraude = MotorAntifraude()

        if os.environ.get("TARIFAS_MODO", "config") == "codigo":
            from .tarifas_codigo import TarifasCodigo
            self.tarifas = TarifasCodigo()
        else:
            from .tarifas_config import TarifasConfig
            self.tarifas = TarifasConfig()

        self.tx = Bitacora("central_tx.jsonl")
        self._lock = threading.Lock()
        self.saldos = {}
        self.procesadas = {}  # tx_id -> respuesta (idempotencia para reenvíos)
        self.duplicados = 0
        self.inicio = time.time()

    # ---- rutas ----
    def salud(self, body, q):
        return 200, {"ok": True, "antifraude": self.antifraude is not None,
                     "tarifas": self.tarifas.modo, "inicio": self.inicio}

    def validar(self, b, q):
        tx_id = b["tx_id"]
        with self._lock:
            if tx_id in self.procesadas:
                self.duplicados += 1
                return 200, {**self.procesadas[tx_id], "duplicado": True}

        if self.antifraude is not None:
            ok, motivo = self.antifraude.evaluar(b["tarjeta"], b["estacion"], b["ts"],
                                                 tx_id=tx_id, validador=b.get("validador"))
            # Un viaje registrado sin red ya ocurrió: se cobra igual, pero la
            # detección corre y la tarjeta queda revocada para lo que siga.
            if not ok and not b.get("offline"):
                resp = {"estado": "rechazado", "motivo": motivo, "tx_id": tx_id}
                with self._lock:
                    self.procesadas[tx_id] = resp
                self.tx.escribir("rechazo", tx_id=tx_id, tarjeta=b["tarjeta"], motivo=motivo)
                return 403, resp

        valor = self.tarifas.calcular(b.get("tipo", "general"), b.get("franja", "valle"),
                                      b.get("transbordos", 0))
        with self._lock:
            if tx_id in self.procesadas:  # carrera entre dos reenvíos
                self.duplicados += 1
                return 200, {**self.procesadas[tx_id], "duplicado": True}
            saldo = self.saldos.get(b["tarjeta"], SALDO_INICIAL)
            if saldo < valor and not b.get("offline"):
                resp = {"estado": "rechazado", "motivo": "saldo_insuficiente", "tx_id": tx_id}
                self.procesadas[tx_id] = resp
                return 402, resp
            self.saldos[b["tarjeta"]] = saldo - valor
            resp = {"estado": "aceptado", "valor": valor, "saldo": saldo - valor, "tx_id": tx_id}
            self.procesadas[tx_id] = resp
        self.tx.escribir("cobro", tx_id=tx_id, tarjeta=b["tarjeta"], valor=valor,
                         offline=bool(b.get("offline")), validador=b.get("validador"))
        return 200, resp

    def lista_negra(self, body, q):
        if self.antifraude is None:
            return 200, {"version": 0, "tarjetas": []}
        return 200, self.antifraude.exportar_lista_negra()

    def saldo(self, body, q):
        return 200, {"tarjeta": q["tarjeta"], "saldo": self.saldos.get(q["tarjeta"], SALDO_INICIAL)}

    def tarifa(self, body, q):
        valor = self.tarifas.calcular(q.get("tipo", "general"), q.get("franja", "valle"),
                                      q.get("transbordos", 0))
        return 200, {"valor": valor, "version": self.tarifas.version}

    def estado(self, body, q):
        with self._lock:
            return 200, {"procesadas": len(self.procesadas), "duplicados_descartados": self.duplicados,
                         "lista_negra": len(self.antifraude.lista_negra) if self.antifraude else 0}


def main():
    c = Central()
    rutas = {
        ("GET", "/salud"): c.salud,
        ("POST", "/validar"): c.validar,
        ("GET", "/lista_negra"): c.lista_negra,
        ("GET", "/saldo"): c.saldo,
        ("GET", "/tarifa"): c.tarifa,
        ("GET", "/estado"): c.estado,
    }
    print(f"[central] puerto {PUERTO} antifraude={c.antifraude is not None} tarifas={c.tarifas.modo}", flush=True)
    crear_servidor(PUERTO, rutas).serve_forever()


if __name__ == "__main__":
    main()
