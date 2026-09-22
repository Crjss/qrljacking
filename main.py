#!/usr/bin/env python3
"""
WhatsApp Forensic Extractor v1.0 - Main Entry Point
Menú interactivo con soporte para múltiples sesiones concurrentes.
"""

import sys
import threading
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from server.server import app
from modules.session_orchestrator import orchestrator


def setup_logging():
    """Configurar trazabilidad detallada sin contaminar la consola interactiva."""
    project_dir = Path(__file__).parent.resolve()
    logs_dir = project_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"extraccion_{timestamp}.log"
    root_logger = logging.getLogger()

    # La aplicación puede inicializarse más de una vez en pruebas o intérpretes
    # interactivos. Reemplazar handlers evita duplicar cada evento en el archivo.
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    root_logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | "
        "%(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(file_handler)

    # Sin handler de consola: stdout queda reservado para el menú y sus prompts.
    # Las solicitudes HTTP se registran explícitamente en server/server.py.
    for logger_name in ("werkzeug", "selenium", "urllib3", "click"):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    # Flask usa esta función de Click para el banner del servidor de desarrollo.
    # Se neutraliza para que el arranque no altere la interfaz de consola.
    import flask.cli
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    logging.getLogger(__name__).info(
        "Logging inicializado; archivo de trazabilidad: %s", log_file
    )
    return log_file


logger = logging.getLogger(__name__)


def start_flask_server():
    """Iniciar servidor Flask en modo multihilo (daemon)."""
    try:
        logger.info("[FLASK] Iniciando servidor en http://0.0.0.0:8080")
        app.run(
            host="0.0.0.0",
            port=8080,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except Exception as e:
        logger.error(f"[FLASK] Error al iniciar servidor: {e}")


def print_header():
    """Imprimir encabezado de bienvenida."""
    print("""
  +==============================================================+
  |     WhatsApp Forensic Extractor v1.0                         |
  |     Auditoría de seguridad en entornos controlados           |
  |     Arquitectura: Multisesión + Orquestación centralizada    |
  +==============================================================+
    """)


def print_menu():
    """Imprimir menú interactivo."""
    print("\n" + "=" * 60)
    print("  MENÚ PRINCIPAL - Gestor de Sesiones de Auditoría")
    print("=" * 60)
    print("1. Crear nueva sesión de auditoría")
    print("2. Ver estado de sesiones activas")
    print("3. Salir (detener todas las sesiones)")
    print("=" * 60)


def create_session_menu():
    """Opción 1: Crear nueva sesión."""
    print("\n[SESIÓN] Creando nueva sesión de auditoría...")
    while True:
        requested_limit = input(
            "¿Cuántos chats deseas extraer? "
            "(Ej. 10, 20 o presiona Enter para extraer TODOS): "
        ).strip()

        if requested_limit in ("", "0"):
            max_chats = None
            break

        try:
            max_chats = int(requested_limit)
            if max_chats > 0:
                break
        except ValueError:
            pass

        print("❌ Ingresa un número entero positivo, 0 o Enter para todos.")

    session_id = orchestrator.create_session(max_chats=max_chats)

    if session_id is None:
        print("❌ No se pudo crear sesión: límite de sesiones simultáneas alcanzado.")
        return

    # Mostrar URL y información
    access_url = f"http://localhost:8080/demo/{session_id}"
    demo_url = f"http://127.0.0.1:8080/demo/{session_id}"

    print(f"\n✅ Sesión creada exitosamente")
    print(f"   Session ID: {session_id}")
    print(
        "   Límite de chats: "
        f"{max_chats if max_chats is not None else 'todos'}"
    )
    print(f"   URL de acceso: {access_url}")
    print(f"   URL local:    {demo_url}")
    print(f"\n   Instrucciones:")
    print(f"   1. Abre la URL en tu navegador")
    print(f"   2. Escanea el código QR con WhatsApp Web")
    print(f"   3. Confirma la sesión en tu dispositivo")

    capacity = orchestrator.get_capacity_info()
    print(f"\n   Capacidad: {capacity['active_sessions']}/{capacity['max_concurrent']} sesiones activas")


def view_status_menu():
    """Opción 2: Ver estado de sesiones activas."""
    print("\n[STATUS] Consultando estado de sesiones activas...")

    all_status = orchestrator.get_all_sessions_status()

    if not all_status:
        print("❌ No hay sesiones activas en este momento.")
        return

    print(f"\n✅ Sesiones activas: {len(all_status)}")
    print("=" * 60)

    for session_id, status in all_status.items():
        state_emoji = {
            'waiting_scan': '⏳',
            'extracting': '📊',
            'completed': '✅',
            'failed': '❌'
        }.get(status['state'], '❓')

        print(f"\n{state_emoji} Session: {session_id}")
        print(f"   Estado: {status['state']}")
        print(f"   En ejecución: {status['is_running']}")
        print(f"   Thread vivo: {status['is_alive']}")
        print(f"   URL de acceso: http://localhost:8080/demo/{session_id}")

    capacity = orchestrator.get_capacity_info()
    print(f"\n{'=' * 60}")
    print(f"Capacidad: {capacity['active_sessions']}/{capacity['max_concurrent']} sesiones")
    print(f"Slots disponibles: {capacity['available_slots']}")


def exit_menu():
    """Opción 3: Salir (detener todas las sesiones)."""
    print("\n[SALIDA] Deteniendo todas las sesiones...")

    stopped = orchestrator.stop_all_sessions()

    print(f"✅ Se detuvieron {stopped} sesiones")
    print("Finalizando aplicación...")
    logger.info("Suite finalizada.")
    sys.exit(0)


def main():
    """Ciclo principal del programa."""
    print_header()

    # Verificar que Flask se está ejecutando
    print("[INICIO] Iniciando servidor Flask en hilo demonio...")
    flask_thread = threading.Thread(
        target=start_flask_server,
        daemon=True
    )
    flask_thread.start()

    # Dar tiempo a Flask para inicializar
    import time
    time.sleep(2)

    logger.info("Servidor Flask iniciado en hilo demonio")
    print("✅ Servidor Flask activo en http://0.0.0.0:8080\n")

    # Menú interactivo
    while True:
        try:
            print_menu()
            option = input("Selecciona una opción (1-3): ").strip()

            if option == "1":
                create_session_menu()
            elif option == "2":
                view_status_menu()
            elif option == "3":
                exit_menu()
            else:
                print("❌ Opción no válida. Por favor, selecciona 1, 2 o 3.")

        except KeyboardInterrupt:
            print("\n\n[INTERRUPCIÓN] Recibida interrupción del usuario (Ctrl+C)")
            exit_menu()
        except Exception as e:
            logger.error(f"Error en menú: {e}")
            print(f"❌ Error inesperado: {e}")


if __name__ == "__main__":
    setup_logging()
    main()
