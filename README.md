# RECAUDO-T – Atributos de calidad, Parte 2 (práctica)

Variante **V5 – Ola de fraudes** (Seguridad prioritaria, Disponibilidad secundaria).

Simulación de un sistema de recaudo de transporte (RECAUDO-T) formado por procesos
reales que se comunican por HTTP. El repositorio implementa tres tácticas de
arquitectura y los experimentos que las miden contra una línea base sin la táctica.

## Contenido

- [Qué implementa](#qué-implementa)
- [Inicio rápido](#inicio-rápido)
- [Comandos disponibles](#comandos-disponibles)
- [Ejecución paso a paso](#ejecución-paso-a-paso)
- [Ejecución con Docker](#ejecución-con-docker)
- [Arquitectura y procesos](#arquitectura-y-procesos)
- [Configuración](#configuración)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Evidencias generadas](#evidencias-generadas)
- [Solución de problemas](#solución-de-problemas)
- [Simplificaciones](#simplificaciones)

## Qué implementa

| Escenario | Atributo | Táctica implementada | Dónde está |
|---|---|---|---|
| S1 – Clonación de tarjetas | Seguridad (prioritario) | Detectar ataques (uso imposible por velocidad) + revocar acceso (lista negra) | `recaudo/antifraude.py` |
| D2 – Validador sin red | Disponibilidad (secundario) | Reintentar (cola local persistente, reenvío con espera exponencial, idempotencia por `tx_id`) | `recaudo/validador.py` |
| M1 – Cambios de tarifa | Modificabilidad | Diferir el enlace (reglas en `config/tarifas.json`, recarga en caliente) | `recaudo/tarifas_config.py` |

**Compromiso medido:** Seguridad vs. Desempeño (latencia que agrega la detección de S1).

> En la Parte 1 se había seleccionado P1 con la táctica *Introducir concurrencia*.
> La regla 2 de la Parte 2 no la acepta (ya se implementó en los talleres), por eso
> el tercer escenario es M1. El compromiso Seguridad–Desempeño se mide igual.

Ninguna táctica se importa de una librería: todo usa solo la **librería estándar de
Python** (`http.server`, `http.client`, `sqlite3`, `json`, `threading`).

## Inicio rápido

Requisitos: **Python 3.10 o superior** (verifique con `python --version`; en algunos
sistemas el comando es `python3`). No hay que instalar nada para correr el sistema.

```bash
git clone <url-del-repositorio> recaudo-t
cd recaudo-t

python run.py              # 1. levanta el sistema completo
```

En otra terminal, con el sistema arriba:

```bash
python -m simuladores.usuarios --tarjetas 50         # 2. tráfico legítimo
python -m simuladores.atacante_clones --clonadas 20  # 3. ataque con tarjetas clonadas
```

Detenga el sistema con `Ctrl+C`. Las bitácoras quedan en `logs/`.

> Opcional: `pip install -r requirements.txt` (solo instala `matplotlib`, necesario
> únicamente para dibujar las gráficas de los experimentos). Se recomienda usar un
> entorno virtual: `python -m venv .venv && source .venv/bin/activate`.

## Comandos disponibles

Todo se lanza desde la raíz del repositorio con `run.py`:

| Comando | Qué hace | Duración aprox. |
|---|---|---|
| `python run.py` | Levanta central, enlace y validadores; queda en espera hasta `Ctrl+C` | continuo |
| `python run.py pruebas` | Pruebas de regresión (tarifas y antifraude, con `unittest`) | segundos |
| `python run.py experimentos` | Corre **todos** los experimentos y genera `evidencias/` | ~15 min |
| `python run.py experimentos s1` | Solo un experimento (`m1`, `s1`, `d2`, `compromiso`) | variable |
| `python run.py experimentos s1 d2` | Varios experimentos a elección | variable |

### Parámetros de los simuladores

| Simulador | Parámetro | Por defecto | Significado |
|---|---|---|---|
| `simuladores.usuarios` | `--tarjetas` | 100 | Cantidad de usuarios legítimos |
| `simuladores.usuarios` | `--tasa` | 20 | Solicitudes por segundo |
| `simuladores.atacante_clones` | `--clonadas` | 50 | Cantidad de tarjetas clonadas |
| `simuladores.atacante_clones` | `--tasa` | 50 | Solicitudes por segundo |

## Ejecución paso a paso

### 1. Levantar el sistema

```bash
python run.py
```

Al terminar de arrancar imprime las URL de cada proceso (central `:8000`,
enlace `:8001`, validadores `:8101` y `:8102`).

### 2. Verificar que responde

```bash
curl http://127.0.0.1:8000/salud     # estado de salud de la central
curl http://127.0.0.1:8000/estado    # estado general (antifraude, lista negra, etc.)
```

### 3. Generar tráfico y observar el antifraude

1. Lance `simuladores.usuarios`: los viajes legítimos se validan sin bloqueos.
2. Lance `simuladores.atacante_clones`: las tarjetas clonadas se usan en estaciones
   distantes en tiempos imposibles; el antifraude las detecta y las agrega a la
   lista negra.
3. Consulte `curl http://127.0.0.1:8000/lista_negra` y revise `logs/`.

### 4. Probar el cambio de tarifas en caliente (M1)

Con el sistema corriendo, edite [`config/tarifas.json`](config/tarifas.json) (por
ejemplo, cambie `general.pico`) y guarde. La central recarga el archivo sin
reiniciarse; si el JSON es inválido lo rechaza y conserva la tarifa anterior.
Consulte una tarifa con `GET /tarifa` en la central (`:8000`).

### 5. Probar la caída del enlace (D2)

El proceso `recaudo.enlace` hace de proxy entre los validadores y la central y
permite inyectar la caída de la red. Mientras el enlace está caído, los validadores
guardan los toques en su cola local y los reenvían con espera exponencial al
recuperarse.

```bash
curl -X POST http://127.0.0.1:8001/_control/falla -d '{"activa": true}'   # cortar la red
curl -X POST http://127.0.0.1:8001/_control/falla -d '{"activa": false}'  # restablecerla
curl http://127.0.0.1:8001/_control/stats                                 # reenviadas / cortadas
```

El experimento `python run.py experimentos d2` automatiza este escenario y lo mide.

### 6. Correr las pruebas y los experimentos

```bash
python run.py pruebas
python run.py experimentos
```

Los experimentos levantan y detienen su propio sistema: **no** hace falta (ni
conviene) tener `python run.py` corriendo al mismo tiempo, porque ocuparían los
mismos puertos.

## Ejecución con Docker

Alternativa que levanta los cuatro procesos en contenedores:

```bash
docker compose up --build     # levantar
docker compose down           # detener
```

Los puertos 8000, 8001, 8101 y 8102 se publican en el host, y `logs/` y `config/`
se montan como volúmenes. Los simuladores se siguen ejecutando desde el host.

## Arquitectura y procesos

| Proceso | Puerto | Real o simulado | Qué hace |
|---|---|---|---|
| `recaudo.central` | 8000 | real | Valida, calcula tarifa, descuenta saldo, motor antifraude, lista negra |
| `recaudo.enlace` | 8001 | real | Proxy de red entre validadores y central; permite inyectar la caída del enlace |
| `recaudo.validador` (VA, VB) | 8101, 8102 | real | Validadores embarcados; cola local y reintento; lista negra local |
| `simuladores/usuarios.py` | – | simulado | Usuarios legítimos con tiempos de viaje realistas |
| `simuladores/atacante_clones.py` | – | simulado | Atacante que usa tarjetas clonadas |
| `simuladores/carga.py` | – | simulado | Generador de carga de lazo abierto que registra cada solicitud |

![Arquitectura](docs/diagramas/arquitectura.png)

Endpoints de la central: `GET /salud`, `POST /validar`, `GET /lista_negra`,
`GET /saldo`, `GET /tarifa`, `GET /estado`.

## Configuración

Los archivos de `config/` definen estaciones (`estaciones.json`) y tarifas
(`tarifas.json`). Además, el comportamiento se ajusta con variables de entorno
(todas son opcionales):

| Variable | Proceso | Por defecto | Efecto |
|---|---|---|---|
| `PUERTO` | todos | 8000 / 8001 / 8101 | Puerto en que escucha el proceso |
| `SALDO_INICIAL` | central | `500000` | Saldo inicial de cada tarjeta (pesos) |
| `TARIFAS_MODO` | central | `config` | `config` lee `tarifas.json`; `codigo` usa tarifas fijas en el código (línea base de M1) |
| `TARIFAS_PATH` | central | `config/tarifas.json` | Ruta alternativa del archivo de tarifas |
| `VELOCIDAD_MAXIMA_KMH` | antifraude | `80` | Velocidad a partir de la cual un viaje se considera imposible |
| `ANTIFRAUDE` | central | `1` | `1` activa el motor antifraude, `0` lo desactiva (línea base de S1) |
| `REINTENTO` | validador | `1` | `1` activa la cola local con reintento, `0` la desactiva (línea base de D2) |
| `ANTIFRAUDE_PERSISTENCIA` | antifraude | `sqlite` | Modo de persistencia del antifraude (por defecto SQLite; la lista negra sobrevive a reinicios) |
| `CENTRAL_URL` | enlace, validador | `http://127.0.0.1:8000` (enlace) / `:8001` (validador) | Destino al que reenvía |
| `VALIDADOR_ID` | validador | `VA` | Identificador del validador |
| `TIMEOUT_ENVIO` | validador | `1.0` | Tiempo máximo de espera al enviar (s) |
| `INTERVALO_LISTA_NEGRA` | validador | `2.0` | Cada cuánto sincroniza la lista negra (s) |
| `DIR_LOGS` | todos | `logs/` | Carpeta de bitácoras |

Ejemplo:

```bash
VELOCIDAD_MAXIMA_KMH=60 python run.py
```

## Estructura del repositorio

```
run.py          comando único (sistema, pruebas y experimentos)
recaudo/        código del sistema (central, validador, enlace, tácticas)
simuladores/    usuarios, atacante y generador de carga
experimentos/   un script por experimento + gráficas
config/         estaciones y tarifas (la tabla de tarifas es la de M1)
tests/          pruebas de regresión
evidencias/     CSV, bitácoras, diffs, resultados y gráficas de cada experimento
docs/           diagramas e informes (Parte 1 y Parte 2, en .docx y .pdf)
logs/           bitácoras de la última ejecución (se genera, no se versiona)
Dockerfile, docker-compose.yml, requirements.txt
```

## Evidencias generadas

Cada experimento deja, para la línea base y para la táctica:

- `evidencias/s1/*/solicitudes.csv`, `seguridad.jsonl` (bitácora), `resultado.json`
- `evidencias/d2/*/toques.csv`, `muestras_cola.csv`, `validador_VA.jsonl`, `enlace.jsonl`, `central_tx.jsonl`
- `evidencias/m1/*/cambio.diff` (el cambio exacto en el código o en la configuración), `consultas.csv`
- `evidencias/compromiso/*_repN/latencias.csv`, `corridas.csv`
- `evidencias/resumen.json` (todos los números del documento) y `evidencias/graficas/`

Sin `matplotlib` se generan igual los CSV y el JSON, pero se omiten las gráficas.

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Address already in use` / el sistema no arranca | Los puertos 8000, 8001, 8101 u 8102 están ocupados (otra instancia de `run.py`, Docker o un experimento) | Detenga la otra instancia, o en Linux/macOS `lsof -i :8000` para ver quién usa el puerto |
| `python: command not found` | En su sistema el intérprete se llama `python3` | Use `python3 run.py ...` |
| Error de sintaxis al arrancar | Versión de Python menor a 3.10 | Instale Python 3.10+ |
| `matplotlib no está instalado: se omiten las gráficas` | Dependencia opcional ausente | `pip install -r requirements.txt` |
| `ModuleNotFoundError: recaudo` o `simuladores` | Se ejecutó desde otra carpeta | Ejecute siempre desde la raíz del repositorio |
| Los simuladores no conectan | El sistema no está arriba | Lance primero `python run.py` y espere a ver las URL |

## Simplificaciones

- Los saldos viven en memoria del central; cada tarjeta simulada arranca con 500 000 pesos.
- El reloj de los eventos (`ts`) es simulado, para poder representar una hora de viajes
  en unos segundos. Las latencias y tiempos de detección se miden con el reloj real.
- Dos validadores representan la red; cada uno atiende seis estaciones.
