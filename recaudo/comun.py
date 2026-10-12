"""Utilidades compartidas: servidor HTTP JSON, cliente HTTP y bitácoras.

Solo usa la librería estándar de Python. Ninguna táctica se importa de una
librería externa: todas están implementadas en los módulos de este paquete.
"""
import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_LOGS = os.environ.get("DIR_LOGS", os.path.join(RAIZ, "logs"))
os.makedirs(DIR_LOGS, exist_ok=True)


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 2048


def crear_servidor(puerto, rutas):
    """rutas: {("GET"|"POST", "/ruta"): funcion(body, query) -> (status, dict)}"""

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _responder(self, status, obj):
            datos = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _atender(self, metodo):
            url = urlparse(self.path)
            funcion = rutas.get((metodo, url.path))
            if funcion is None:
                return self._responder(404, {"error": "ruta no existe"})
            body = {}
            if metodo == "POST":
                n = int(self.headers.get("Content-Length", 0))
                if n:
                    body = json.loads(self.rfile.read(n))
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                status, obj = funcion(body, query)
            except Exception as e:  # el servicio no se cae por una petición mala
                status, obj = 500, {"error": str(e)}
            self._responder(status, obj)

        def do_GET(self):
            self._atender("GET")

        def do_POST(self):
            self._atender("POST")

    return Servidor(("0.0.0.0", puerto), Manejador)


def pedir(metodo, url, body=None, timeout=2.0):
    """Petición HTTP con JSON. Lanza excepción si no hay conexión."""
    u = urlparse(url)
    con = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    try:
        datos = json.dumps(body).encode() if body is not None else None
        cab = {"Content-Type": "application/json"} if datos else {}
        ruta = u.path + ("?" + u.query if u.query else "")
        con.request(metodo, ruta, body=datos, headers=cab)
        r = con.getresponse()
        crudo = r.read()
        return r.status, (json.loads(crudo) if crudo else {})
    finally:
        con.close()


class Bitacora:
    """Archivo JSON Lines con marca de tiempo real (epoch, segundos)."""

    def __init__(self, nombre):
        self.ruta = os.path.join(DIR_LOGS, nombre)
        self._lock = threading.Lock()
        self._f = open(self.ruta, "a", encoding="utf-8")

    def escribir(self, evento, **campos):
        registro = {"ts": time.time(), "evento": evento, **campos}
        linea = json.dumps(registro, ensure_ascii=False)
        with self._lock:
            self._f.write(linea + "\n")
            self._f.flush()
        return registro


def leer_jsonl(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def env_bool(nombre, defecto="1"):
    return os.environ.get(nombre, defecto).strip().lower() in ("1", "true", "si", "on")
