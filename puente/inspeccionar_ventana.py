#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Herramienta de reconocimiento — NO escribe nada, NO hace clic en nada,
NO toca el teclado. Solo LEE cómo está armada la ventana de "999" por
dentro (qué controles tiene, cómo se llama cada uno, en qué posición
están) y lo guarda en un archivo de texto. Sirve para poder automatizar
después los clics de "elegir ambiente" y "elegir mesa" (ahora mismo el
puente solo sabe escribir con el teclado, no hace clics).

CÓMO USARLO
-----------
1. Necesita Python 3.9+ y las mismas librerías del puente instaladas:
      pip install pywinauto pywin32 psutil

2. Abre "999" y déjalo en la pantalla que quieres mapear — por ejemplo,
   la pantalla donde se elige el AMBIENTE (1er Piso, 2do Piso, etc.).

3. Corre, en esa misma computadora:
      python inspeccionar_ventana.py ambientes

   Cuando termine, va a avisar que escribió un archivo
   "inspeccion_ambientes.txt" al lado de este script.

4. Ahora, SIN cerrar "999", entra a un ambiente cualquiera (para que se
   vean las mesas de ese ambiente en pantalla) y corre:
      python inspeccionar_ventana.py mesas

5. Por último, entra a una mesa cualquiera (para llegar a la pantalla
   donde se escribe el pedido — el campo "CARTA") y corre:
      python inspeccionar_ventana.py pedido

6. Al final vas a tener 3 archivos de texto
   (inspeccion_ambientes.txt / inspeccion_mesas.txt /
   inspeccion_pedido.txt). Mándamelos (o pega el contenido) — con eso
   armo la automatización de los clics.

Si en vez de 3 pasos preferís uno solo que lo guarde todo junto en el
momento que esté la pantalla que sea, corre:
      python inspeccionar_ventana.py cualquiera
"""
import sys
import json
import os

# IMPORTANTE: cuando este script corre compilado como .exe de un solo
# archivo (PyInstaller --onefile), __file__ apunta a una carpeta TEMPORAL
# donde Windows lo descomprime al vuelo (algo como
# C:\Users\...\AppData\Local\Temp\_MEIxxxxx), no a la carpeta real donde
# está el .exe — y esa carpeta temporal se borra sola apenas el programa
# termina. Por eso hay que usar sys.argv[0] (la ruta del .exe en sí) en
# vez de __file__ cuando está "congelado" (sys.frozen), igual que hace
# bridge_server.py, para que config.json y los inspeccion_*.txt queden
# siempre al lado del .exe, donde el usuario los puede encontrar.
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def cargar_ventana_cfg():
    proceso = "Restaurante"
    backend = "win32"
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        proceso = cfg.get("ventana", {}).get("proceso", proceso)
        backend = cfg.get("backend_automatizacion", backend)
    except Exception:
        pass
    return proceso, backend


def encontrar_ventana(proceso, backend):
    import psutil
    from pywinauto import Application
    from pywinauto.findwindows import find_elements

    pids = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nombre = p.info.get("name") or ""
        except Exception:
            continue
        if proceso.lower() in nombre.lower():
            pids.append(p.info["pid"])
    if not pids:
        print('No se encontró ningún proceso llamado "%s" corriendo. '
              '¿"999" está abierto?' % proceso)
        sys.exit(1)

    candidatos = []
    for pid in pids:
        candidatos.extend(find_elements(backend=backend, process=pid))
    if not candidatos:
        print('El proceso "%s" está corriendo pero no se le encontró '
              'ninguna ventana.' % proceso)
        sys.exit(1)

    app = Application(backend=backend).connect(process=candidatos[0].process_id)
    return app.top_window()


def main():
    etiqueta = sys.argv[1] if len(sys.argv) > 1 else "cualquiera"
    proceso, backend = cargar_ventana_cfg()
    print('Buscando la ventana del proceso "%s" (backend=%s)...' % (proceso, backend))
    ventana = encontrar_ventana(proceso, backend)
    ventana.set_focus()

    nombre_archivo = "inspeccion_%s.txt" % etiqueta
    ruta = os.path.join(BASE_DIR, nombre_archivo)

    with open(ruta, "w", encoding="utf-8") as f:
        f.write("Título de la ventana: %r\n" % ventana.window_text())
        f.write("Clase: %r\n" % ventana.friendly_class_name())
        f.write("=" * 70 + "\n\n")
        import contextlib
        with contextlib.redirect_stdout(f):
            ventana.print_control_identifiers(depth=None)

    print("Listo. Se guardó: %s" % ruta)
    print("Mándame ese archivo (o copia y pega su contenido).")


if __name__ == "__main__":
    main()
