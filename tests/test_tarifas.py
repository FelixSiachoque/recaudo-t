"""Pruebas de regresión de tarifas y de la recarga en caliente (táctica M1)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DIR_LOGS", tempfile.mkdtemp())

from recaudo import tarifas_config  # noqa: E402
from recaudo.comun import RAIZ  # noqa: E402
from recaudo.tarifas_codigo import TarifasCodigo  # noqa: E402
from recaudo.tarifas_config import TarifasConfig  # noqa: E402

COMBOS = [(t, f, tr) for t in ("general", "estudiante", "adulto_mayor")
          for f in ("pico", "valle") for tr in (0, 1, 2, 3)]


class PruebasTarifas(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ruta = os.path.join(self.dir, "tarifas.json")
        shutil.copy(os.path.join(RAIZ, "config", "tarifas.json"), self.ruta)
        tarifas_config.INTERVALO_REVISION = 0  # revisar en cada llamada durante la prueba

    def tearDown(self):
        shutil.rmtree(self.dir)

    def escribir(self, datos):
        time.sleep(0.01)
        with open(self.ruta, "w") as f:
            json.dump(datos, f)
        os.utime(self.ruta, (time.time() + 1, time.time() + 1))  # asegura mtime distinto

    def test_configuracion_y_codigo_dan_las_mismas_tarifas(self):
        cfg, cod = TarifasConfig(self.ruta), TarifasCodigo()
        for t, f, tr in COMBOS:
            self.assertEqual(cfg.calcular(t, f, tr), cod.calcular(t, f, tr), (t, f, tr))

    def test_transbordos(self):
        cfg = TarifasConfig(self.ruta)
        self.assertEqual(cfg.calcular("general", "pico", 1), 300)
        self.assertEqual(cfg.calcular("general", "pico", 2), 0)

    def test_recarga_en_caliente_sin_reiniciar(self):
        cfg = TarifasConfig(self.ruta)
        datos = json.load(open(self.ruta))
        datos["tarifas"]["estudiante"]["valle"] = 1950
        datos["tarifas"]["discapacidad"] = {"pico": 1600, "valle": 1500}
        self.escribir(datos)
        self.assertEqual(cfg.calcular("estudiante", "valle"), 1950)
        self.assertEqual(cfg.calcular("discapacidad", "pico"), 1600)
        self.assertEqual(cfg.calcular("general", "pico"), 3200)  # lo demás no cambia

    def test_configuracion_invalida_se_rechaza_y_se_conserva_la_anterior(self):
        cfg = TarifasConfig(self.ruta)
        datos = json.load(open(self.ruta))
        datos["tarifas"]["general"]["pico"] = -5
        self.escribir(datos)
        self.assertEqual(cfg.calcular("general", "pico"), 3200)

    def test_tipo_desconocido(self):
        with self.assertRaises(ValueError):
            TarifasConfig(self.ruta).calcular("turista", "pico")


class PruebasAntifraude(unittest.TestCase):
    def setUp(self):
        from recaudo import antifraude
        self.tmp = tempfile.mkdtemp()
        antifraude.DIR_LOGS = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_viaje_posible_no_se_bloquea_y_viaje_imposible_si(self):
        from recaudo.antifraude import MotorAntifraude
        m = MotorAntifraude()
        self.assertTrue(m.evaluar("X1", "E02", 1000)[0])
        self.assertTrue(m.evaluar("X1", "E03", 1000 + 600)[0])      # 1,4 km en 10 min
        self.assertFalse(m.evaluar("X1", "E06", 1000 + 660)[0])     # 8,6 km en 1 min
        self.assertFalse(m.evaluar("X1", "E06", 9999)[0])           # ya está en lista negra
        self.assertIn("X1", m.exportar_lista_negra()["tarjetas"])

    def test_lista_negra_sobrevive_reinicio(self):
        from recaudo import antifraude
        m = antifraude.MotorAntifraude()
        m.evaluar("Y1", "E01", 0)
        m.evaluar("Y1", "E06", 60)              # revocada
        m2 = antifraude.MotorAntifraude()       # "reinicio": instancia nueva, misma base
        self.assertIn("Y1", m2.lista_negra)
        self.assertFalse(m2.evaluar("Y1", "E01", 99999)[0])


if __name__ == "__main__":
    unittest.main()
