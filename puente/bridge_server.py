#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puente Comanda Cevichería <-> sistema "999"
=============================================

Este programa corre en la computadora "comando" del restaurante (la B o la
C, nunca la principal — ver el documento del proyecto). Lee los pedidos
DIRECTO de Firestore (la base de datos en la nube del proyecto), con su
propia llave de administrador (firebase-service-account.json, al lado de
este programa) — ya no depende de que ninguna pestaña del navegador le
avise nada por HTTP. Eso se cambió porque claude.ai bloqueaba esa conexión
por seguridad (Content Security Policy) y no había forma de evitarlo desde
el lado del navegador.

Cuando detecta algo nuevo (platos recién registrados en cocina, o un
pedido recién cerrado), este programa:

  1. En MODO SIMULACIÓN (el que trae por defecto): NO toca el teclado de
     nada. Solo escribe en la consola y en puente_log.txt exactamente qué
     habría escrito y en qué orden, para poder revisar la secuencia con
     calma antes de arriesgar un pedido real.
  2. En MODO REAL: activa la ventana de "999" (proceso "Restaurante", título
     que contiene "REALIZAR PEDIDOS POR MESAS") y escribe la secuencia de
     teclas configurada en config.json para registrar el pedido o finalizarlo.

Los eventos pendientes de varios dispositivos/mesas se ordenan por la HORA
REAL DEL SERVIDOR (no la del celular de cada mozo) en que se presionó
"Registrar"/"Cerrar pedido", y se mandan a "999" de a UNO por vez, en ese
mismo orden — así, si 2 mozos mandan pedidos casi juntos (5-10 segundos de
diferencia), entran en el orden real en que los mandaron.

También escribe su propio estado (conectado, modo, pendientes, actividad
reciente) en el documento estadoPuente/actual de Firestore, para que
cualquier pantalla del navegador pueda ver cómo va sin necesitar hablarle
directo a este programa.

La secuencia exacta de teclas (qué campo se llena primero, si hace falta
Tab o Enter entre uno y otro, el atajo del botón "Registrar", etc.) TODAVÍA
NO está confirmada contra el sistema real. Por eso vive en config.json como
una lista de pasos editable, no metida a la fuerza en este código.

Requiere Python 3.9+. Dependencias: firebase-admin, pywinauto, pywin32 (ver
requirements.txt). Para armar el .exe de un solo archivo se usa PyInstaller
vía GitHub Actions (ver .github/workflows/build-puente.yml).

IMPORTANTE: firebase-service-account.json es una llave privada — nunca se
sube a GitHub (está en .gitignore) ni se compila dentro del .exe. Tiene que
quedar como archivo suelto al lado del .exe, en la computadora del
restaurante solamente.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_DEFAULT = {
    # "simulacion": no toca el teclado, solo registra en el log lo que haría.
    # "real": sí escribe de verdad en la ventana de "999".
    "modo": "simulacion",
    # backend de pywinauto para hablar con la ventana de "999":
    # "win32" funciona mejor con programas más antiguos (Delphi/VB6/VCL),
    # que es lo más común en sistemas de punto de venta de este tipo.
    # "uia" (UI Automation) funciona mejor con programas más modernos.
    "backend_automatizacion": "win32",
    # NUEVO (2026-10-03): si está en true, el puente hace los clics de
    # ambiente -> mesa por su cuenta antes de escribir el pedido, en vez
    # de necesitar que alguien deje "999" ya posicionado ahí a mano. Esto
    # es justo lo que permite que pedidos de mesas/ambientes distintos
    # (mandados casi al mismo tiempo por mozos distintos) entren cada uno
    # a su mesa real, sin cruzarse. Se resolvió con los archivos
    # inspeccion_ambientes.txt / inspeccion_mesas.txt / inspeccion_pedido.txt
    # que mandó el usuario (ver _navegar_a_mesa más abajo).
    #
    # IMPORTANTE para probarlo sin riesgo: este interruptor es
    # INDEPENDIENTE de "modo". Con navegar_con_clics:true y modo:
    # "simulacion", el puente SÍ hace los clics reales de ambiente/mesa en
    # "999" (para que puedas verificar que entra a la mesa correcta), pero
    # NO escribe ningún plato ni código de mozo (eso se queda en el log,
    # como siempre en modo simulación). Recién con modo:"real" además
    # escribe de verdad.
    "navegar_con_clics": False,
    # Después de registrar/finalizar, hace UN clic en la barra de título de
    # "999" para dejarla activa en primer plano (por si el foco quedó en otra
    # ventana o en un aviso). "clic_final_y" = cuántos píxeles abajo del borde
    # superior de la ventana cae el clic (la barra de título). Poner
    # "clic_final_en_999": false para desactivarlo.
    "clic_final_en_999": True,
    # Pasos para que "999" vuelva a la pantalla de ambientes/mesas después de
    # registrar o finalizar (ej. [{"accion":"tecla","tecla":"{ESC}"}]). Vacío = no hace nada.
    "secuencia_volver": [],
    "clic_final_y": 12,
    "ventana": {
        "proceso": "Restaurante",
        "titulo_contiene": "REALIZAR PEDIDOS POR MESAS"
    },
    # Nombre del ambiente tal como lo guarda la app (colección "ambientes"
    # de Firestore, campo "nombre") -> el texto EXACTO de su etiqueta
    # dentro de "999" (confirmado contra inspeccion_ambientes.txt,
    # 2026-10-03 — "999" usa mayúsculas/abreviaturas distintas a la app
    # a propósito, es el texto que programó el proveedor del sistema).
    "ambiente_app_a_999": {
        "1er Piso": "1º PISO",
        "2do Piso": "2º PISO",
        "Mezanine": "MEZANINE",
        "Privado": "PRIVADO",
        "Salón": "SALON"
    },
    "reintentos_activar_ventana": 3,
    "espera_entre_reintentos_ms": 500,
    # Placeholders disponibles en cada paso: {carta} {cantidad} {comentario}
    # {mozoCode} {mesaNumero}. "tecla" usa la sintaxis de pywinauto.keyboard
    # (ej. "{ENTER}", "{TAB}", "%r" para Alt+R, "^s" para Ctrl+S).
    #
    # ESTA SECUENCIA ES UN PUNTO DE PARTIDA, NO ESTÁ CONFIRMADA TODAVÍA
    # contra el sistema real. Ajustar viendo la pantalla real de "999" en
    # modo simulación primero (ver README.md de esta carpeta).
    # Confirmado por el usuario viendo "999" en vivo (2026-10-01/02): desde
    # el campo "carta", son 2 ENTER seguidos (no Tab) para seleccionar el
    # producto y pasar a cantidad; de cantidad a comentario es 1 ENTER (no
    # Tab); y para terminar de agregar el renglón a la tabla, DESPUÉS del
    # comentario van 2 ENTER más (no el "%m"/Alt+M que se había puesto
    # como suposición inicial sin confirmar). Tras esos 2 últimos ENTER el
    # cursor vuelve solo al campo "carta", listo para el siguiente plato.
    "secuencia_por_plato": [
        {"accion": "escribir", "texto": "{carta}"},
        {"accion": "esperar", "ms": 600},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 150},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 150},
        {"accion": "escribir", "texto": "{cantidad}"},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 150},
        {"accion": "escribir", "texto": "{comentario}"},
        {"accion": "esperar", "ms": 150},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 150},
        {"accion": "tecla", "tecla": "{ENTER}"}
    ],
    # Confirmado por el usuario (2026-10-03): después de escribir el código
    # de mozo hacen falta DOS Enter, no uno — el primero termina el campo
    # del código y pasa el foco al botón "Aceptar"; el segundo Enter es el
    # que de verdad lo acciona.
    "secuencia_registrar": [
        {"accion": "tecla", "tecla": "%r"},
        {"accion": "esperar", "ms": 400},
        {"accion": "escribir", "texto": "{mozoCode}"},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 200},
        {"accion": "tecla", "tecla": "{ENTER}"}
    ],
    "secuencia_finalizar": [
        {"accion": "tecla", "tecla": "%f"},
        {"accion": "esperar", "ms": 400},
        {"accion": "escribir", "texto": "{mozoCode}"},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 400},
        {"accion": "tecla", "tecla": "{ENTER}"},
        {"accion": "esperar", "ms": 300},
        {"accion": "tecla", "tecla": "{ENTER}"}
    ]
}

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "puente_log.txt")
CREDENCIALES_PATH = os.path.join(BASE_DIR, "firebase-service-account.json")
PROCESADOS_PATH = os.path.join(BASE_DIR, "puente_procesados.json")


def cargar_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CONFIG_DEFAULT, f, ensure_ascii=False, indent=2)
        return json.loads(json.dumps(CONFIG_DEFAULT))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    def completar(base, extra):
        for k, v in extra.items():
            if k not in base:
                base[k] = v
            elif isinstance(v, dict) and isinstance(base.get(k), dict):
                completar(base[k], v)
    completar(cfg, CONFIG_DEFAULT)
    return cfg


CONFIG = cargar_config()

# ---------------------------------------------------------------------------
# Logging (consola + archivo)
# ---------------------------------------------------------------------------

logger = logging.getLogger("puente")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file = logging.FileHandler(LOG_PATH, encoding="utf-8")
_file.setFormatter(_fmt)
logger.addHandler(_file)

# ---------------------------------------------------------------------------
# Diagnóstico de cierres inesperados: todo lo que mate al programa (error de
# Python en cualquier hilo, o una caída "dura" de una librería como pywinauto/
# grpc) queda escrito en puente_log.txt. Si el log termina SIN ninguna de estas
# líneas, a la ventana la cerraron desde fuera (Windows, alguien, suspensión).
# ---------------------------------------------------------------------------

def _excepthook(tipo, valor, tb):
    logger.critical("ERROR NO CONTROLADO (hilo principal)", exc_info=(tipo, valor, tb))

def _thread_excepthook(args):
    logger.critical("ERROR NO CONTROLADO en hilo %s", getattr(args.thread, "name", "?"),
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

sys.excepthook = _excepthook
try:
    threading.excepthook = _thread_excepthook
except Exception:
    pass
try:
    import faulthandler
    # Va a su PROPIO archivo: Windows reporta a veces errores COM recuperables
    # (ej. código 0x8001010d, "999" ocupada) con un volcado largo aunque el
    # programa siga bien; así no ensucian puente_log.txt.
    _fault_file = open(os.path.join(BASE_DIR, "puente_caidas.txt"), "a", encoding="utf-8")
    faulthandler.enable(file=_fault_file, all_threads=True)
except Exception:
    pass

import atexit
atexit.register(lambda: logger.info("El puente se está cerrando (salida normal del programa)."))

# ---------------------------------------------------------------------------
# Procesados (persistido en disco — qué ya se le avisó a "999", para no
# repetirlo si este programa se reinicia)
# ---------------------------------------------------------------------------

_procesados_lock = threading.Lock()


def cargar_procesados():
    try:
        with open(PROCESADOS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def guardar_procesados(procesados):
    try:
        with open(PROCESADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(procesados), f)
    except Exception as e:
        logger.warning("No se pudo guardar puente_procesados.json: %s", e)


# ---------------------------------------------------------------------------
# Automatización de la ventana de "999" (solo se usa en modo "real")
# ---------------------------------------------------------------------------

# ANTES esto abría una ventanita (Tkinter) siempre encima avisando "no tocar
# el teclado". Se quitó (2026-10-04): Tkinter necesita que TODO pase por el
# hilo principal del programa, pero este aviso se mostraba/ocultaba desde un
# hilo de fondo (procesar_cola corre en su propio hilo, uno nuevo por cada
# pedido que llega) — crear una ventana de Tk desde ahí funciona la primera
# vez "de suerte" y casi siempre revienta el programa entero la segunda o
# tercera vez. Esto era justo la causa de que el puente se cerrara solo
# después de uno o dos pedidos. Como reemplazo, el aviso ahora es solo texto
# en la consola/log (ver _ejecutar_pasos y procesar_cola), que sí es seguro
# desde cualquier hilo.
def _mostrar_overlay():
    logger.info("PEDIDO EN PROCESO — no tocar el teclado ni el mouse de esta PC.")


def _ocultar_overlay():
    pass


def _escapar_para_send_keys(texto):
    especiales = "+^%~(){}[]"
    out = []
    for ch in str(texto):
        if ch in especiales:
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


def _activar_ventana_999(cfg):
    import psutil
    from pywinauto import Application
    from pywinauto.findwindows import find_elements

    proceso = cfg["ventana"]["proceso"]
    titulo_contiene = cfg["ventana"]["titulo_contiene"]
    backend = cfg.get("backend_automatizacion", "win32")

    # Los objetos que devuelve find_elements() (HwndElementInfo/UIAElementInfo)
    # no tienen el nombre del proceso directamente (eso dio el error
    # "object has no attribute 'process_name'") — solo el PID. Así que
    # primero se busca el PID por nombre de proceso con psutil, y recién
    # ahí se buscan las ventanas de ESE proceso puntual.
    pids = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nombre = p.info.get("name") or ""
        except Exception:
            continue
        if proceso.lower() in nombre.lower():
            pids.append(p.info["pid"])
    if not pids:
        raise RuntimeError(
            'No se encontró ningún proceso llamado "%s" corriendo en esta '
            'computadora. ¿"999" está abierto?' % proceso
        )

    candidatos = []
    for pid in pids:
        candidatos.extend(find_elements(backend=backend, process=pid))
    if not candidatos:
        raise RuntimeError(
            'El proceso "%s" está corriendo, pero no se le encontró ninguna '
            'ventana. ¿"999" está abierto y no minimizado?' % proceso
        )

    app = Application(backend=backend).connect(process=candidatos[0].process_id)
    ventana = None
    try:
        top = app.top_window()
        if titulo_contiene.lower() in (top.window_text() or "").lower():
            ventana = top
    except Exception:
        pass
    if ventana is None:
        for e in candidatos:
            if titulo_contiene.lower() in (e.name or "").lower():
                ventana = app.window(handle=e.handle)
                break
    if ventana is None:
        raise RuntimeError(
            'Se encontró el proceso "%s" pero ninguna de sus ventanas tiene '
            '"%s" en el título.' % (proceso, titulo_contiene)
        )

    ventana.set_focus()
    return ventana


# ---------------------------------------------------------------------------
# Navegación por clics (ambiente -> mesa) — NUEVO 2026-10-03
# ---------------------------------------------------------------------------
#
# Se arma a partir de los 3 archivos inspeccion_*.txt que mandó el usuario
# (sacados con inspeccionar_ventana.py en la PC real). Hallazgos clave:
#
#   - Cada ambiente ("MEZANINE", "1º PISO", etc.) y cada mesa ("M07", etc.)
#     es una etiqueta (System.Windows.Forms.Label) que se encuentra por su
#     TEXTO EXACTO, no por su posición en pantalla — así que no importa que
#     cada ambiente tenga las mesas acomodadas distinto, el clic cae solo
#     donde esté.
#   - Esos identificadores (auto_id, control_type) solo se pueden usar
#     conectando con el backend "uia" de pywinauto — por eso estas
#     funciones abren su PROPIA conexión en vez de reusar la de
#     _activar_ventana_999 (que puede estar en "win32" para el tipeo).
#   - La misma etiqueta de texto aparece REPETIDA muchas veces en el árbol
#     completo de la ventana (quedan copias de pantallas anteriores que no
#     se cerraron del todo, es normal en apps tipo MDI como "999") — por
#     eso _encontrar_visible() exige que haya EXACTAMENTE UNA copia
#     visible en pantalla antes de hacerle clic; si hay 0 o más de 1,
#     prefiere fallar con un error claro antes que arriesgarse a tocar la
#     mesa equivocada.

def _conectar_uia(cfg):
    import psutil
    from pywinauto import Application
    from pywinauto.findwindows import find_elements

    proceso = cfg["ventana"]["proceso"]
    pids = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nombre = p.info.get("name") or ""
        except Exception:
            continue
        if proceso.lower() in nombre.lower():
            pids.append(p.info["pid"])
    if not pids:
        raise RuntimeError(
            'No se encontró ningún proceso llamado "%s" corriendo en esta '
            'computadora. ¿"999" está abierto?' % proceso
        )
    # Reintenta unos segundos: justo después de "Registrar", "999" puede estar
    # ocupado un momento y no contestarle a UIA (la lista de ventanas sale vacía).
    candidatos = []
    for intento in range(6):
        candidatos = []
        for pid in pids:
            try:
                candidatos.extend(find_elements(backend="uia", process=pid))
            except Exception as e:
                logger.warning("find_elements(uia) falló para pid %s: %s", pid, e)
        if candidatos:
            break
        time.sleep(1.0)

    if not candidatos:
        # Plan B: buscar las ventanas por Win32 (no depende de que UIA responda) y
        # dejar en el log QUÉ ventanas tiene "999" ahora mismo, para diagnosticar.
        titulo_contiene = cfg["ventana"].get("titulo_contiene", "")
        hwnd_principal = None
        descripcion = []
        for pid in pids:
            try:
                for e in find_elements(backend="win32", process=pid, visible_only=False):
                    descripcion.append("%r clase=%s visible=%s" % (
                        e.name, getattr(e, "class_name", "?"), getattr(e, "visible", "?")))
                    if titulo_contiene and titulo_contiene.lower() in (e.name or "").lower():
                        hwnd_principal = e.handle
            except Exception as ex:
                descripcion.append("(win32 falló: %s)" % ex)
        logger.warning('UIA no ve ventanas de "%s". Ventanas Win32 del proceso: %s',
                       proceso, "; ".join(descripcion) if descripcion else "ninguna")
        if hwnd_principal:
            try:
                app = Application(backend="uia").connect(handle=hwnd_principal)
                ventana = app.window(handle=hwnd_principal)
                ventana.set_focus()
                logger.info("Conectado a la ventana principal de 999 por Win32 (plan B).")
                return ventana
            except Exception as ex:
                logger.warning("Plan B (conectar por handle) falló: %s", ex)
        raise RuntimeError(
            'El proceso "%s" está corriendo, pero no se le encontró ninguna '
            'ventana por UIA (necesaria para los clics). ¿"999" está '
            'abierto y no minimizado? (¿quedó alguna ventana/aviso abierto?)' % proceso
        )
    app = Application(backend="uia").connect(process=candidatos[0].process_id)
    ventana = app.top_window()
    ventana.set_focus()
    return ventana


def _describir_control(c):
    try:
        ei = c.element_info
        r = c.rectangle()
        return "%s/%s en (%d,%d,%d,%d)" % (getattr(ei, "control_type", "?"),
                                          getattr(ei, "class_name", "?"),
                                          r.left, r.top, r.right, r.bottom)
    except Exception:
        return "?"


def _visibles_con_texto(ventana, titulo, reintentos=4, espera_ms=400):
    """Todos los controles visibles cuyo texto es exactamente 'titulo' (puede ser
    más de uno). Reintenta un poco si todavía no aparece ninguno."""
    import time as _time
    visibles = []
    for _ in range(reintentos):
        try:
            candidatos = ventana.descendants(title=titulo)
        except Exception:
            candidatos = []
        visibles = []
        for c in candidatos:
            try:
                if c.is_visible():
                    visibles.append(c)
            except Exception:
                continue
        if visibles:
            return visibles
        _time.sleep(espera_ms / 1000.0)
    return visibles


def _encontrar_visible(ventana, titulo, reintentos=6, espera_ms=400):
    """Busca, dentro de 'ventana', TODOS los controles cuyo texto sea
    exactamente 'titulo' y exige que haya exactamente UNO visible en
    pantalla en ese momento (ver nota arriba sobre las copias viejas).
    Reintenta por si la pantalla todavía está cargando."""
    import time as _time
    ultimo_motivo = "sin intentos"
    for _ in range(reintentos):
        try:
            candidatos = ventana.descendants(title=titulo)
        except Exception as e:
            candidatos = []
            ultimo_motivo = str(e)
        visibles = []
        for c in candidatos:
            try:
                if c.is_visible():
                    visibles.append(c)
            except Exception:
                continue
        if len(visibles) == 1:
            return visibles[0]
        ultimo_motivo = "%d candidato(s), %d visible(s)" % (len(candidatos), len(visibles))
        _time.sleep(espera_ms / 1000.0)
    raise RuntimeError(
        'No se encontró de forma segura el control "%s" en "999" (%s). '
        "No se hizo clic, para no arriesgar tocar otra mesa por error."
        % (titulo, ultimo_motivo)
    )


def _navegar_a_mesa(cfg, ambiente_999, mesa_numero):
    """Hace los clics reales de ambiente -> mesa en "999". Devuelve la
    ventana (conexión UIA) ya posicionada en la pantalla de esa mesa.

    Si el texto del ambiente aparece en VARIOS controles visibles a la vez (por
    ejemplo el botón del ambiente y además rótulos con el mismo nombre cuando
    "999" se quedó dentro de la pantalla de una mesa), ya no se rinde: prueba
    cada uno (botones primero) y SOLO da por bueno el clic si después de hacerlo
    aparece, exactamente una vez, la mesa buscada. Así nunca hace clic en una
    mesa equivocada."""
    ventana = _conectar_uia(cfg)
    candidatos = _visibles_con_texto(ventana, ambiente_999)
    if not candidatos:
        raise RuntimeError('No se encontró el ambiente "%s" en "999" (¿está en la pantalla de mesas?).' % ambiente_999)

    def orden(c):
        try:
            tipo = getattr(c.element_info, "control_type", "")
            r = c.rectangle()
            return (0 if tipo in ("Button", "TabItem", "ListItem") else 1, r.top, r.left)
        except Exception:
            return (2, 0, 0)
    candidatos.sort(key=orden)
    if len(candidatos) > 1:
        logger.warning('"%s" aparece %d veces en pantalla: %s. Se prueba uno por uno, verificando que aparezca la mesa %s.',
                       ambiente_999, len(candidatos), " | ".join(_describir_control(c) for c in candidatos), mesa_numero)

    ultimo_error = None
    for c in candidatos:
        try:
            c.click_input()
            time.sleep(0.6)
            mesa_ctrl = _encontrar_visible(ventana, mesa_numero, reintentos=3, espera_ms=300)
            mesa_ctrl.click_input()
            time.sleep(0.6)
            return ventana
        except Exception as e:
            ultimo_error = e
            continue
    raise RuntimeError(
        'No se pudo llegar a la mesa %s desde "%s" (%d candidato(s) probados). Último motivo: %s'
        % (mesa_numero, ambiente_999, len(candidatos), ultimo_error)
    )


def _ejecutar_pasos(pasos, variables):
    from pywinauto.keyboard import send_keys
    for paso in pasos:
        accion = paso.get("accion")
        if accion == "escribir":
            texto = paso.get("texto", "").format(**variables)
            send_keys(_escapar_para_send_keys(texto), pause=0.02, with_spaces=True)
        elif accion == "tecla":
            send_keys(paso.get("tecla", ""), pause=0.02)
        elif accion == "esperar":
            time.sleep(paso.get("ms", 0) / 1000.0)
        else:
            logger.warning('Paso desconocido en config.json ignorado: %r', paso)


def _comentario_combinado(grupo):
    """Arma el comentario de una línea que junta varias unidades del mismo plato.

    - Si todas las unidades tienen el MISMO comentario (o ninguno), se deja ese.
    - Si difieren, se detalla cuántas unidades lleva cada uno, ej. 2 ceviches
      (uno normal y otro "sin ají"): "1 normal, 1 ik h"."""
    cuentas = []  # [(comentario, cantidad)] en orden de aparición
    for it in grupo:
        com = (it.get("comentario") or "").strip()
        try:
            cant = int(it.get("cantidad") or 1)
        except (TypeError, ValueError):
            cant = 1
        for k, par in enumerate(cuentas):
            if par[0] == com:
                cuentas[k] = (com, par[1] + cant)
                break
        else:
            cuentas.append((com, cant))
    if len(cuentas) == 1:
        return cuentas[0][0]
    return ", ".join("%d %s" % (c, com if com else "normal") for com, c in cuentas)


def _separar_items_automatizables(items):
    """Divide los platos de un pedido en dos listas:

    - automatizables: UNA línea por cada código real distinto. Si el mismo
      plato viene varias veces en la tanda (ej. piden 2 Cev Mix, uno normal
      y otro "sin ají": en la app son 2 renglones con el mismo código), se
      JUNTAN en una sola línea con la cantidad total y un comentario
      combinado ("1 normal, 1 ik h"). Así "999" no abre la ventanita
      "Actualizar Cantidad de pedido detalle" que sale al repetir un código.
    - manuales: los que no tienen código real mapeado TODAVÍA.

    Los platos que se piden DESPUÉS, cuando el mismo código ya está cargado
    en "999" de una tanda anterior, todavía requieren la ventanita (doble
    clic en "cantidad"); eso queda pendiente de automatizar.
    """
    automatizables = []
    manuales = []
    grupos = {}
    orden = []
    for it in items:
        codigo = it.get("codigo")
        if not codigo:
            manuales.append((it, "sin código real todavía"))
            continue
        if codigo not in grupos:
            grupos[codigo] = []
            orden.append(codigo)
        grupos[codigo].append(it)
    for codigo in orden:
        grupo = grupos[codigo]
        if len(grupo) == 1:
            automatizables.append(grupo[0])
            continue
        junto = dict(grupo[0])
        total = 0
        for it in grupo:
            try:
                total += int(it.get("cantidad") or 1)
            except (TypeError, ValueError):
                total += 1
        junto["cantidad"] = total
        junto["comentario"] = _comentario_combinado(grupo)
        automatizables.append(junto)
    return automatizables, manuales


def _avisar_items_manuales(mesa_numero, manuales):
    if not manuales:
        return
    detalle = "; ".join(
        "%sx %s (%s)" % (it.get("cantidad"), it.get("nombreApp"), motivo)
        for it, motivo in manuales
    )
    logger.warning(
        'Mesa %s: %d plato(s) requieren carga manual en "999" (%s).',
        mesa_numero, len(manuales), detalle
    )


def _navegar_si_corresponde(cfg, datos):
    """Si navegar_con_clics está prendido en config.json, hace los clics
    reales de ambiente -> mesa ANTES de tocar el teclado. Esto corre sin
    importar si el modo es "simulacion" o "real" — a propósito, para
    poder probar que el clic cae en la mesa correcta sin arriesgar que
    además escriba algo (ver comentario de "navegar_con_clics" en
    CONFIG_DEFAULT)."""
    if not cfg.get("navegar_con_clics"):
        return
    ambiente999 = datos.get("ambiente999")
    mesa_numero = datos.get("mesaNumero")
    if not ambiente999:
        logger.warning(
            'Mesa %s: no se pudo navegar por clics (no se sabe a qué '
            'ambiente de "999" corresponde) — se intenta escribir donde '
            '"999" ya esté parado.', mesa_numero
        )
        return
    _navegar_a_mesa(cfg, ambiente999, mesa_numero)


def _volver_a_pantalla_mesas(cfg):
    pasos = cfg.get("secuencia_volver") or []
    if not pasos:
        return
    try:
        time.sleep(0.4)
        _ejecutar_pasos(pasos, {"carta": "", "cantidad": "", "comentario": "", "mozoCode": "", "mesaNumero": ""})
    except Exception as e:
        logger.warning('No se pudo volver a la pantalla de mesas: %s', e)


def _clic_para_enfocar_999(cfg):
    """Un clic en la barra de título de "999" al terminar un pedido, para que
    quede en primer plano y lista para el siguiente. Nunca hace fallar el pedido."""
    if not cfg.get("clic_final_en_999", True):
        return
    try:
        time.sleep(0.5)
        ventana = _conectar_uia(cfg)
        ancho = ventana.rectangle().width()
        ventana.click_input(coords=(int(ancho // 2), int(cfg.get("clic_final_y", 12))))
        time.sleep(0.3)
    except Exception as e:
        logger.warning('No se pudo hacer el clic final para enfocar "999": %s', e)


def registrar_en_999(cfg, datos, escribir=True):
    automatizables, manuales = _separar_items_automatizables(datos["items"])
    _avisar_items_manuales(datos["mesaNumero"], manuales)

    _navegar_si_corresponde(cfg, datos)
    if not escribir:
        return
    ventana = _activar_ventana_999(cfg)
    for it in automatizables:
        variables = {
            "carta": it["codigo"],
            "cantidad": it.get("cantidad", 1),
            "comentario": it.get("comentario", ""),
            "mozoCode": datos.get("mozoCode", ""),
            "mesaNumero": datos.get("mesaNumero", "")
        }
        _ejecutar_pasos(cfg["secuencia_por_plato"], variables)
    _ejecutar_pasos(cfg["secuencia_registrar"], {
        "mozoCode": datos.get("mozoCode", ""), "mesaNumero": datos.get("mesaNumero", ""),
        "carta": "", "cantidad": "", "comentario": ""
    })
    _volver_a_pantalla_mesas(cfg)
    ventana.set_focus()
    _clic_para_enfocar_999(cfg)


def finalizar_en_999(cfg, datos, escribir=True):
    _navegar_si_corresponde(cfg, datos)
    if not escribir:
        return
    ventana = _activar_ventana_999(cfg)
    _ejecutar_pasos(cfg["secuencia_finalizar"], {
        "mozoCode": datos.get("mozoCode", ""), "mesaNumero": datos.get("mesaNumero", ""),
        "carta": "", "cantidad": "", "comentario": ""
    })
    _volver_a_pantalla_mesas(cfg)
    ventana.set_focus()
    _clic_para_enfocar_999(cfg)


def simular(tipo, datos):
    logger.info("=" * 60)
    if tipo == "registrar":
        logger.info('[SIMULACIÓN] Registraría en "999" — Mesa %s (mozo %s):',
                     datos.get("mesaNumero"), datos.get("mozoCode"))
        automatizables, manuales = _separar_items_automatizables(datos.get("items", []))
        for it in automatizables:
            logger.info('   - %sx [%s] %s%s  (por teclado)',
                        it.get("cantidad"), it["codigo"], it.get("nombreApp"),
                        (" — " + it["comentario"]) if it.get("comentario") else "")
        for it, motivo in manuales:
            logger.info('   - %sx %s%s  -> CARGA MANUAL (%s)',
                        it.get("cantidad"), it.get("nombreApp"),
                        (" — " + it["comentario"]) if it.get("comentario") else "", motivo)
        logger.info('   -> Presionaría "Registrar" con código de mozo "%s"', datos.get("mozoCode"))
    else:
        logger.info('[SIMULACIÓN] Finalizaría (pasaría a cobrar) — Mesa %s (mozo %s). '
                     'Imprimiría 2 veces.', datos.get("mesaNumero"), datos.get("mozoCode"))
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Firestore: conexión, lectura de pedidos/códigos, cola ordenada, estado
# ---------------------------------------------------------------------------

def conectar_firestore():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not os.path.exists(CREDENCIALES_PATH):
        raise RuntimeError(
            'Falta el archivo "firebase-service-account.json" al lado de este '
            "programa. Es la llave privada del proyecto Firebase — pídesela a "
            "quien armó el proyecto (nunca se sube a GitHub)."
        )
    cred = credentials.Certificate(CREDENCIALES_PATH)
    firebase_admin.initialize_app(cred)
    return firestore.client()


class PuenteFirestore(object):
    def __init__(self, db, cfg):
        self.db = db
        self.cfg = cfg
        self.procesados = cargar_procesados()
        self.lock = threading.Lock()
        self.cola = []  # lista de eventos pendientes, ordenada por ts
        self.codigos_por_producto = {}
        self.mesas_por_id = {}
        self.ambientes_por_id = {}
        self.log = []  # [{texto, ok, hora}], más reciente primero
        self.enviando = False
        # UN SOLO hilo permanente para todo lo que toca "999" (UIA/COM). Antes se
        # creaba un hilo nuevo por cada pedido: al terminar, ese hilo cerraba su
        # COM y sus objetos quedaban "huérfanos"; el recolector de basura los
        # liberaba después desde OTRO hilo y eso tumbaba el programa con
        # "access violation" (comtypes/pywinauto). Con un hilo único y vivo todo
        # el tiempo, los objetos COM se crean y se liberan en el mismo hilo.
        # El recolector de basura automático puede correr en CUALQUIER hilo (ej. los
        # de red de Firestore) y liberar desde ahí objetos COM creados por el hilo de
        # 999 -> access violation. Se apaga el automático y se recoge a mano, solo
        # desde el hilo de 999, al terminar cada tanda de pedidos.
        import gc
        gc.disable()
        self._despertar = threading.Event()
        self._hilo_999 = threading.Thread(target=self._bucle_hilo_999, name="hilo-999", daemon=True)
        self._hilo_999.start()
        self._cargar_codigos_reales()
        self._cargar_mesas()
        self._cargar_ambientes()
        self._watch_codigos = self.db.collection("codigosReales").on_snapshot(self._on_codigos)
        self._watch_mesas = self.db.collection("mesas").on_snapshot(self._on_mesas)
        self._watch_ambientes = self.db.collection("ambientes").on_snapshot(self._on_ambientes)
        self._watch_pedidos = self.db.collection("pedidos").on_snapshot(self._on_pedidos)
        self._watch_comandos = self.db.collection("comandosPuente").on_snapshot(self._on_comandos)

    def _cargar_codigos_reales(self):
        try:
            docs = self.db.collection("codigosReales").stream()
            self.codigos_por_producto = {d.id: d.to_dict() for d in docs}
        except Exception as e:
            logger.warning("No se pudo leer codigosReales todavía: %s", e)

    def _on_codigos(self, docs, changes, read_time):
        mapa = {}
        for d in docs:
            mapa[d.id] = d.to_dict()
        self.codigos_por_producto = mapa

    def _cargar_mesas(self):
        # El documento del pedido solo guarda mesaId (el id de Firestore,
        # ej. "mesa-m20") — el número real de mesa ("M20", el que "999"
        # conoce) vive aparte, en el documento de la colección "mesas". Se
        # mantiene este mapa en memoria para no tener que leerlo cada vez.
        try:
            docs = self.db.collection("mesas").stream()
            self.mesas_por_id = {d.id: d.to_dict() for d in docs}
        except Exception as e:
            logger.warning("No se pudo leer mesas todavía: %s", e)

    def _on_mesas(self, docs, changes, read_time):
        mapa = {}
        for d in docs:
            mapa[d.id] = d.to_dict()
        self.mesas_por_id = mapa

    def _cargar_ambientes(self):
        # Para saber a qué ambiente real de "999" hay que entrar antes de
        # cargar una mesa (ver navegar_con_clics / _navegar_a_mesa).
        try:
            docs = self.db.collection("ambientes").stream()
            self.ambientes_por_id = {d.id: d.to_dict() for d in docs}
        except Exception as e:
            logger.warning("No se pudo leer ambientes todavía: %s", e)

    def _on_ambientes(self, docs, changes, read_time):
        mapa = {}
        for d in docs:
            mapa[d.id] = d.to_dict()
        self.ambientes_por_id = mapa

    def _ambiente_999_para_mesa(self, mesa_doc):
        """Dado el documento de una mesa (de self.mesas_por_id), devuelve
        el texto EXACTO que usa "999" para ese ambiente (ej. "MEZANINE"),
        o None si no se pudo resolver (ambiente no sembrado, nombre nuevo
        sin mapear en config.json, etc.)."""
        if not mesa_doc:
            return None
        ambiente_doc = self.ambientes_por_id.get(mesa_doc.get("ambienteId")) or {}
        nombre_app = ambiente_doc.get("nombre")
        if not nombre_app:
            return None
        return self.cfg.get("ambiente_app_a_999", {}).get(nombre_app)

    def _ts_valor(self, campo):
        """Convierte un campo de Firestore (Timestamp o None, puede no estar
        resuelto todavía justo después de escribirse) a algo ordenable."""
        if campo is None:
            return datetime.now(timezone.utc)
        if hasattr(campo, "timestamp"):
            return campo
        return datetime.now(timezone.utc)

    def _on_pedidos(self, docs, changes, read_time):
        nuevos_eventos = []
        with self.lock:
            for d in docs:
                pedido = d.to_dict() or {}
                pedido_id = d.id
                if pedido.get("estado") == "archivado":
                    continue
                mesa_doc = self.mesas_por_id.get(pedido.get("mesaId")) or {}
                mesa_numero = mesa_doc.get("numero") or pedido.get("mesaNumero") or pedido.get("mesaId") or "?"
                ambiente999 = self._ambiente_999_para_mesa(mesa_doc)
                items = pedido.get("items") or []
                nuevos_items = [
                    it for it in items
                    if it.get("enviadoCocina") and ("item_" + str(it.get("id"))) not in self.procesados
                ]
                if nuevos_items:
                    key = "registrar_" + pedido_id + "_" + ",".join(str(it.get("id")) for it in nuevos_items)
                    if not any(e["key"] == key for e in self.cola):
                        items_payload = []
                        for it in nuevos_items:
                            cr = self.codigos_por_producto.get(it.get("productoId"))
                            items_payload.append({
                                "itemId": it.get("id"),
                                "codigo": (cr or {}).get("codigo"),
                                "nombreReal": (cr or {}).get("nombreReal"),
                                "nombreApp": it.get("nombre"),
                                "cantidad": it.get("cantidad"),
                                # "comentarioPuente" = texto tal cual lo comandó el
                                # mozo (abreviaturas sin interpretar, ej. "ik h"),
                                # corto a propósito porque se imprime. Si el plato no
                                # lo trae (platos viejos, o editados a mano en la app)
                                # se usa "detalle", como antes.
                                "comentario": (it.get("comentarioPuente")
                                               if it.get("comentarioPuente") is not None
                                               else (it.get("detalle") or ""))
                            })
                        evento = {
                            "key": key,
                            "tipo": "registrar",
                            "pedidoId": pedido_id,
                            "ts": self._ts_valor(pedido.get("registradoPuenteEn")),
                            "payload": {
                                "mesaNumero": mesa_numero,
                                "ambiente999": ambiente999,
                                "mozoCode": pedido.get("mozoCode") or "",
                                "pedidoId": pedido_id,
                                "items": items_payload
                            },
                            "marcar_ids": ["item_" + str(it.get("id")) for it in nuevos_items]
                        }
                        self.cola.append(evento)
                        nuevos_eventos.append(evento)

                if pedido.get("estado") == "cerrado" and ("cerrado_" + pedido_id) not in self.procesados:
                    key = "finalizar_" + pedido_id
                    if not any(e["key"] == key for e in self.cola):
                        evento = {
                            "key": key,
                            "tipo": "finalizar",
                            "pedidoId": pedido_id,
                            "ts": self._ts_valor(pedido.get("cerradoPuenteEn")),
                            "payload": {
                                "mesaNumero": mesa_numero,
                                "ambiente999": ambiente999,
                                "mozoCode": pedido.get("mozoCode") or "",
                                "pedidoId": pedido_id
                            },
                            "marcar_ids": ["cerrado_" + pedido_id]
                        }
                        self.cola.append(evento)
                        nuevos_eventos.append(evento)

            # Orden real: por la hora de servidor en que se mandó cada evento,
            # así entran en el orden real aunque Firestore los avise en otro
            # orden por timing de red entre dispositivos distintos.
            self.cola.sort(key=lambda e: e["ts"])

        if nuevos_eventos:
            self.lanzar_procesar_cola()

    def _on_comandos(self, docs, changes, read_time):
        for d in docs:
            cmd = d.to_dict() or {}
            if cmd.get("atendido"):
                continue
            if cmd.get("accion") == "descartar":
                self._descartar(cmd.get("pedidoId"), cmd.get("tipo"), d.id)

    def _descartar(self, pedido_id, tipo, comando_id):
        with self.lock:
            idx = None
            for i, e in enumerate(self.cola):
                if e["pedidoId"] == pedido_id and e["tipo"] == tipo:
                    idx = i
                    break
            if idx is not None:
                evento = self.cola.pop(idx)
                for mid in evento["marcar_ids"]:
                    self.procesados.add(mid)
                guardar_procesados(self.procesados)
                self._log_push("Descartado manualmente — Mesa " + str(evento["payload"]["mesaNumero"]), False)
        try:
            self.db.collection("comandosPuente").document(comando_id).update({"atendido": True})
        except Exception as e:
            logger.warning("No se pudo marcar comando atendido: %s", e)

    def _log_push(self, texto, ok):
        hora = datetime.now().strftime("%H:%M:%S")
        self.log.insert(0, {"texto": texto, "ok": ok, "hora": hora})
        if len(self.log) > 25:
            self.log = self.log[:25]

    def lanzar_procesar_cola(self):
        """Avisa al hilo permanente que revise la cola (no crea hilos nuevos)."""
        self._despertar.set()

    def _bucle_hilo_999(self):
        while True:
            self._despertar.wait()
            self._despertar.clear()
            try:
                self.procesar_cola()
            except Exception:
                logger.exception("Error inesperado en el hilo de 999 (sigue funcionando)")
            try:
                import gc
                gc.collect()
            except Exception:
                pass

    def procesar_cola(self):
        """Manda los eventos pendientes de a UNO por vez, en orden, esperando
        que cada uno termine antes de pasar al siguiente — el teclado de
        "999" solo puede escribir una cosa a la vez."""
        with self.lock:
            if self.enviando:
                return
            self.enviando = True
        try:
            while True:
                with self.lock:
                    if not self.cola:
                        break
                    evento = self.cola[0]
                modo = self.cfg.get("modo", "simulacion")
                navegar = bool(self.cfg.get("navegar_con_clics"))
                escribir = (modo == "real")
                try:
                    if modo == "simulacion":
                        # Aunque no vaya a escribir nada, siempre se deja
                        # en el log qué haría — sirve para revisar antes
                        # de pasar a modo real.
                        simular(evento["tipo"], evento["payload"])
                    if escribir or navegar:
                        # Si navegar_con_clics está prendido, esto corre
                        # IGUAL en modo simulación (hace los clics reales
                        # de ambiente/mesa para poder verificar que caen
                        # bien), pero "escribir" decide si además tipea
                        # algo — ver _navegar_si_corresponde más arriba.
                        _mostrar_overlay()
                        try:
                            if evento["tipo"] == "registrar":
                                registrar_en_999(self.cfg, evento["payload"], escribir=escribir)
                            else:
                                finalizar_en_999(self.cfg, evento["payload"], escribir=escribir)
                            if escribir:
                                logger.info('Mesa %s: %s escrito en "999".',
                                            evento["payload"]["mesaNumero"], evento["tipo"])
                            elif navegar:
                                logger.info(
                                    'Mesa %s: clic de navegación hecho en "999" '
                                    "(modo simulación, no escribió nada).",
                                    evento["payload"]["mesaNumero"]
                                )
                        finally:
                            _ocultar_overlay()
                    modo_txt = " (modo simulación, no tocó \"999\")" if modo == "simulacion" else ""
                    self._log_push(
                        (("Platos registrados" if evento["tipo"] == "registrar" else "Pedido finalizado") +
                         " — Mesa " + str(evento["payload"]["mesaNumero"]) + modo_txt), True
                    )
                    with self.lock:
                        for mid in evento["marcar_ids"]:
                            self.procesados.add(mid)
                        guardar_procesados(self.procesados)
                        if self.cola and self.cola[0]["key"] == evento["key"]:
                            self.cola.pop(0)
                except Exception as e:
                    logger.exception("Error con mesa %s: %s", evento["payload"].get("mesaNumero"), e)
                    self._log_push(
                        "Error con Mesa " + str(evento["payload"].get("mesaNumero")) + ": " + str(e), False
                    )
                    # Se queda al frente de la cola y se reintenta en el
                    # siguiente ciclo (no se pierde ni se duplica nada).
                    break
        finally:
            with self.lock:
                self.enviando = False

    def escribir_estado(self):
        with self.lock:
            pendientes_detalle = []
            for e in self.cola[:8]:
                pendientes_detalle.append({
                    "pedidoId": e["pedidoId"],
                    "tipo": e["tipo"],
                    "mesaNumero": e["payload"]["mesaNumero"],
                    "platos": len(e["payload"].get("items", [])) if e["tipo"] == "registrar" else None
                })
            pendientes = len(self.cola)
            log_copia = list(self.log[:15])
        try:
            from firebase_admin import firestore
            self.db.collection("estadoPuente").document("actual").set({
                "modo": self.cfg.get("modo", "simulacion"),
                "pendientes": pendientes,
                "pendientesDetalle": pendientes_detalle,
                "log": log_copia,
                "actualizadoEn": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            logger.warning("No se pudo escribir estadoPuente/actual: %s", e)


def main():
    logger.info("=" * 60)
    logger.info("Puente Comanda Cevichería <-> \"999\"")
    logger.info('Modo actual: %s%s', CONFIG.get("modo"),
                "  (no va a tocar el teclado)" if CONFIG.get("modo") == "simulacion" else "  (SÍ va a escribir en \"999\")")
    logger.info("Config: %s", CONFIG_PATH)
    logger.info("Log: %s", LOG_PATH)

    try:
        db = conectar_firestore()
    except Exception as e:
        logger.error("No se pudo conectar con Firestore: %s", e)
        logger.error("Revisa que firebase-service-account.json esté al lado de este programa y que haya internet.")
        input("\nPresiona Enter para cerrar...")
        return

    logger.info("Conectado a Firestore. Vigilando pedidos en vivo...")
    logger.info("Dejar esta ventana abierta. Para cerrar el puente, cerrar esta ventana.")
    logger.info("=" * 60)

    puente = PuenteFirestore(db, CONFIG)
    try:
        while True:
            time.sleep(5)
            # Un error aquí NO debe tumbar al puente: se anota y sigue.
            try:
                puente.escribir_estado()
                # Por si algún evento quedó pendiente de un intento fallido.
                if puente.cola and not puente.enviando:
                    puente.lanzar_procesar_cola()
            except Exception:
                logger.exception("Error en el ciclo principal (el puente sigue funcionando)")
    except KeyboardInterrupt:
        logger.info("Puente detenido con Ctrl+C.")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        logger.critical("El puente terminó por un error fatal:", exc_info=True)
        try:
            input("\nEl puente se detuvo por un error (ver puente_log.txt). Presiona Enter para cerrar...")
        except Exception:
            pass
