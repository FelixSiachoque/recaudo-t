"""Enlace de comunicaciones entre los validadores y el servidor central.

Es un proxy HTTP real: reenvía cada petición al central. Sirve para inyectar
fallas de red (escenario D2): mientras la falla está activa, corta la conexión
sin responder, igual que un enlace caído.

Control:
  POST /_control/falla   {"activa": true|false}
  GET  /_control/stats   peticiones reenviadas y cortadas
"""
import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .comun import Bitacora, Servidor

PUERTO = int(os.environ.get("PUERTO", "8001"))
DESTINO = urlparse(os.environ.get("CENTRAL_URL", "http://127.0.0.1:8000"))

estado = {"falla": False, "reenviadas": 0, "cortadas": 0, "reenviadas_validar": 0}
lock = threading.Lock()
bitacora = Bitacora("enlace.jsonl")


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, status, obj):
        d = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _proxy(self, metodo):
        n = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(n) if n else None

        if self.path.startswith("/_control/"):
            if self.path == "/_control/falla" and metodo == "POST":
                activa = bool(json.loads(cuerpo or b"{}").get("activa"))
                with lock:
                    estado["falla"] = activa
                bitacora.escribir("falla_on" if activa else "falla_off")
                return self._json(200, {"falla": activa})
            if self.path == "/_control/stats":
                with lock:
                    return self._json(200, dict(estado))
            return self._json(404, {})

        if estado["falla"]:
            with lock:
                estado["cortadas"] += 1
            self.close_connection = True  # se cae la conexión sin respuesta
            return

        con = http.client.HTTPConnection(DESTINO.hostname, DESTINO.port, timeout=3)
        try:
            con.request(metodo, self.path, body=cuerpo,
                        headers={"Content-Type": "application/json"} if cuerpo else {})
            r = con.getresponse()
            datos = r.read()
        except OSError:
            return self._json(502, {"error": "central no responde"})
        finally:
            con.close()
        with lock:
            estado["reenviadas"] += 1
            if self.path.startswith("/validar"):
                estado["reenviadas_validar"] += 1
        self.send_response(r.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")


def main():
    print(f"[enlace] puerto {PUERTO} -> {DESTINO.geturl()}", flush=True)
    Servidor(("0.0.0.0", PUERTO), Manejador).serve_forever()


if __name__ == "__main__":
    main()
