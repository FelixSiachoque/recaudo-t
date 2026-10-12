"""LÍNEA BASE de M1 (sin la táctica): reglas tarifarias escritas en el código.

Cada cambio de la alcaldía obliga a editar este archivo y reiniciar el
servicio central para que Python vuelva a cargar el módulo.
"""


class TarifasCodigo:
    modo = "codigo"
    version = "codigo"

    def calcular(self, tipo, franja, transbordos=0):
        transbordos = int(transbordos)
        if transbordos == 1:
            return 300
        if transbordos >= 2:
            return 0

        if tipo == "general":
            if franja == "pico":
                return 3200
            return 2950
        elif tipo == "estudiante":
            if franja == "pico":
                return 2250
            return 2100
        elif tipo == "adulto_mayor":
            if franja == "pico":
                return 2000
            return 1800
        raise ValueError(f"tipo de usuario desconocido: {tipo}")
