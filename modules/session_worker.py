#!/usr/bin/env python3
"""
SessionWorker: Encapsula el ciclo de vida de cada sesión de navegador en un hilo independiente.
Cada sesión corre en su propio Firefox Headless con perfil y almacenamiento aislado.
"""

import threading
import logging
import base64
import json
import time
import signal
from pathlib import Path
from enum import Enum
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)

from modules.chat_extractor import ChatExtractor
from modules.output_manager import OutputManager
from modules.session_manager import SessionManager

logger = logging.getLogger(__name__)


class _SessionThreadFilter(logging.Filter):
    """Permitir únicamente registros emitidos desde el hilo de una sesión."""

    def __init__(self, thread_id):
        super().__init__()
        self.thread_id = thread_id

    def filter(self, record):
        return record.thread == self.thread_id


class SessionState(Enum):
    """Estados internos del ciclo de vida de la sesión."""
    WAITING_SCAN = "waiting_scan"      # Esperando escaneo del QR
    EXTRACTING = "extracting"          # Extrayendo chats y contactos
    COMPLETED = "completed"            # Completado exitosamente
    FAILED = "failed"                  # Error durante la ejecución


class SessionWorker(threading.Thread):
    """
    Hilo independiente que gestiona una sesión de auditoría completa.
    Abre un navegador Firefox en modo headless, captura QR, espera autenticación,
    y ejecuta extractores de chats y contactos.
    """

    def __init__(
        self,
        session_id,
        output_dir="./evidencias",
        max_chats: Optional[int] = None,
    ):
        """
        Inicializar el worker de sesión.

        Args:
            session_id (str): UUID único de la sesión
            output_dir (str): Directorio base para evidencias
            max_chats (Optional[int]): Máximo de chats a extraer o ``None``.
        """
        super().__init__(daemon=False)
        self.session_id = str(session_id)
        self.output_dir = Path(output_dir)
        self.session_dir = self.output_dir / self.session_id
        self.profile_dir = self.session_dir / "firefox_profile"
        self.max_chats = (
            max_chats
            if isinstance(max_chats, int) and not isinstance(max_chats, bool)
            and max_chats > 0
            else None
        )

        # Estado interno
        self.state = SessionState.WAITING_SCAN
        self.driver = None
        self.session_manager = None
        self.chat_extractor = None
        self.output_manager = None
        self._stop_event = threading.Event()
        self._session_log_handler = None

        # Crear directorios aislados
        self._setup_directories()

        logger.info(
            f"[WORKER] SessionWorker creado para {self.session_id} "
            f"en {self.session_dir}"
        )

    def _setup_directories(self):
        """Crear estructura de directorios para la sesión."""
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[WORKER] Directorios creados: {self.session_dir}")
        except Exception as e:
            logger.error(f"[WORKER] Error al crear directorios: {e}")
            self.state = SessionState.FAILED
            raise

    def _configure_session_logging(self):
        """Añadir el archivo de trazabilidad aislado para este hilo de trabajo."""
        if self._session_log_handler is not None:
            return

        session_log = self.session_dir / "session.log"
        handler = logging.FileHandler(session_log, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "%(threadName)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(_SessionThreadFilter(threading.get_ident()))
        logging.getLogger().addHandler(handler)
        self._session_log_handler = handler

        logger.info(
            "[WORKER] Log de sesión configurado: %s", session_log
        )

    def _remove_session_logging(self):
        """Cerrar y desacoplar el handler de sesión al terminar el hilo."""
        handler = self._session_log_handler
        if handler is None:
            return

        logging.getLogger().removeHandler(handler)
        handler.close()
        self._session_log_handler = None

    def _build_driver(self):
        """
        Instanciar Firefox en modo headless con perfil único aislado.

        Returns:
            webdriver.Firefox: Driver configurado para la sesión
        """
        try:
            logger.info(f"[WORKER] Construyendo driver Firefox para {self.session_id}...")

            # Opciones de Firefox para modo gráfico visible
            options = FirefoxOptions()

            # Configurar descargas en el directorio de la sesión
            options.set_preference("browser.download.folderList", 2)
            options.set_preference(
                "browser.download.dir", str(self.session_dir)
            )
            options.set_preference(
                "browser.helperApps.neverAsk.saveToDisk",
                "application/json,text/plain,application/octet-stream"
            )

            # Aceptar almacenamiento persistente automáticamente
            options.set_preference(
                "dom.storageManager.prompt.testing", False
            )
            options.set_preference(
                "dom.storageManager.prompt.testing.allow", True
            )
            options.set_preference("permissions.default.persistent-storage", 1)
            options.set_preference("dom.indexedDB.enabled", True)
            options.set_preference("dom.storage.enabled", True)

            # Deshabilitar notificaciones emergentes
            options.set_preference("dom.webnotifications.enabled", False)

            # Crear instancia de WebDriver
            self.driver = webdriver.Firefox(options=options)
            logger.info(f"[WORKER] Driver Firefox creado exitosamente")
            return self.driver

        except Exception as e:
            logger.error(f"[WORKER] Error al construir driver: {e}")
            self.state = SessionState.FAILED
            raise

    def _capture_qr_periodically(self, interval=5):
        """
        Capturar periódicamente la imagen del código QR desde el canvas.

        Args:
            interval (int): Segundos entre capturas
        """
        qr_attempts = 0
        max_attempts = 60  # 5 minutos con intervalo de 5 segundos

        while qr_attempts < max_attempts and not self._stop_event.is_set():
            try:
                # Buscar el canvas del QR
                canvas = self.driver.find_element(
                    By.CSS_SELECTOR,
                    'canvas[aria-label*="Scan this QR"]'
                )

                # Extraer imagen en base64 desde toDataURL
                b64_qr = self.driver.execute_script(
                    """
                    return (function(c) {
                        return c.toDataURL('image/png').substring(22);
                    })(arguments[0]);
                    """,
                    canvas
                )

                # Decodificar y guardar en qr.png
                qr_bytes = base64.b64decode(b64_qr)
                qr_path = self.session_dir / "qr.png"
                qr_path.write_bytes(qr_bytes)

                logger.debug(
                    f"[WORKER] QR capturado para {self.session_id} "
                    f"({len(qr_bytes)} bytes)"
                )

            except NoSuchElementException:
                logger.debug(
                    f"[WORKER] Canvas QR no encontrado (intento {qr_attempts + 1})"
                )
            except Exception as e:
                logger.debug(f"[WORKER] Error capturando QR: {e}")

            qr_attempts += 1
            time.sleep(interval)

    def _wait_for_authentication(self, timeout=60):
        """
        Esperar a que el usuario se autentique detectando la lista de chats.

        Args:
            timeout (int): Segundos a esperar

        Returns:
            bool: True si se detectó autenticación, False si timeout
        """
        try:
            logger.info(
                f"[WORKER] Esperando autenticación por hasta {timeout}s..."
            )

            # Esperar a que aparezca la lista de chats
            try:
                WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'div[data-testid="chat-list"]')
                    )
                )
                logger.info(f"[WORKER] ¡Autenticación detectada para {self.session_id}!")
                return True
                
            except Exception as e:
                # Si la sesión fue detenida intencionalmente, no registrar como error
                if self._stop_event.is_set():
                    logger.debug(f"[WORKER] Sesión detenida durante espera de autenticación")
                    return False
                # Si fue timeout u otra excepción durante ejecución normal
                if isinstance(e, TimeoutException):
                    logger.warning(f"[WORKER] Timeout esperando autenticación")
                else:
                    logger.warning(f"[WORKER] Error esperando autenticación: {e}")
                return False
                
        except Exception as e:
            logger.error(f"[WORKER] Excepción inesperada en _wait_for_authentication: {e}")
            return False

    def _extract_data(self):
        """Ejecutar extractores de chats y contactos."""
        try:
            # Cambiar estado a extrayendo
            self.state = SessionState.EXTRACTING

            logger.info(f"[WORKER] Iniciando extracción de datos...")

            # Crear ChatExtractor con pausas de scroll configuradas
            self.chat_extractor = ChatExtractor(
                self.session_manager,
                output_dir=str(self.session_dir)
            )

            # Extraer chats (con pausas de 2.0 segundos) y consolidarlos
            # explícitamente en evidencias/<session_id>/chats.json.
            logger.info(f"[WORKER] Extrayendo chats...")
            self.chat_extractor.extract_all(
                max_chats=self.max_chats,
                msg_steps=200,
            )
            chats = self.chat_extractor.chats_data
            chats_path = self.session_dir / "chats.json"
            with chats_path.open("w", encoding="utf-8") as file:
                json.dump(chats, file, ensure_ascii=False, indent=2)
            logger.info(f"[WORKER] Extracted {len(chats)} chats")

            # Abrir Nuevo chat antes de extraer la libreta mediante React Fiber.
            logger.info(f"[WORKER] Extrayendo contactos...")
            if not self.session_manager.open_new_chat_panel():
                raise RuntimeError("No se pudo abrir el panel Nuevo chat")
            contacts = self.chat_extractor.extract_full_contacts()
            contacts_path = self.session_dir / "contacts.json"
            with contacts_path.open("w", encoding="utf-8") as file:
                json.dump(contacts, file, ensure_ascii=False, indent=2)
            logger.info(f"[WORKER] Extracted {len(contacts)} contacts")

        except Exception as e:
            logger.error(f"[WORKER] Error durante extracción: {e}")
            self.state = SessionState.FAILED
            raise

    def _finalize_evidence(self):
        """Guardar hashes de integridad y comprimir evidencias."""
        try:
            logger.info(f"[WORKER] Finalizando evidencias...")

            # Crear OutputManager para la sesión
            self.output_manager = OutputManager(
                output_dir=str(self.session_dir)
            )

            # Guardar hashes SHA-256
            logger.info(f"[WORKER] Generando hashes SHA-256...")
            self.output_manager.save_hashes()

            # Generar manifiesto
            logger.info(f"[WORKER] Generando manifiesto...")
            self.output_manager.generate_manifest()

            # Comprimir evidencias
            archive_name = f"evidencias_{self.session_id}.zip"
            logger.info(f"[WORKER] Comprimiendo evidencias...")
            archive_path = self.output_manager.create_archive(
                archive_name=archive_name
            )

            logger.info(f"[WORKER] Evidencias finalizadas: {archive_path}")

        except Exception as e:
            logger.error(f"[WORKER] Error durante finalización: {e}")
            self.state = SessionState.FAILED
            raise

    def run(self):
        """
        Bucle de ejecución principal: abre navegador, captura QR,
        espera autenticación, extrae datos y finaliza.
        """
        try:
            self._configure_session_logging()
            logger.info(f"[WORKER] Iniciando ejecución para {self.session_id}...")

            # 1. Construir driver Firefox
            self._build_driver()
            self.session_manager = SessionManager(self.driver)

            # 2. Abrir WhatsApp Web
            logger.info(f"[WORKER] Abriendo https://web.whatsapp.com...")
            self.driver.get("https://web.whatsapp.com")

            # 3. Capturar QR periódicamente en background (no bloqueante)
            # En esta versión, se captura en el loop principal
            time.sleep(3)  # Dar tiempo a cargar la página

            # 4. Capturar QR periódicamente
            logger.info(f"[WORKER] Iniciando captura periódica de QR...")
            qr_start = time.time()
            qr_timeout = 300  # 5 minutos para capturar QR

            while (time.time() - qr_start) < qr_timeout and not self._stop_event.is_set():
                try:
                    # Tras el escaneo el canvas desaparece. Salir de este bucle
                    # en cuanto WhatsApp muestre la lista para continuar con la
                    # confirmación y la extracción, sin esperar el timeout QR.
                    if self.driver.find_elements(
                        By.CSS_SELECTOR, 'div[data-testid="chat-list"]'
                    ):
                        logger.info("[WORKER] Lista de chats detectada durante captura QR")
                        break

                    canvas = self.driver.find_element(
                        By.CSS_SELECTOR,
                        'canvas[aria-label*="Scan this QR"]'
                    )
                    b64_qr = self.driver.execute_script(
                        """
                        return (function(c) {
                            return c.toDataURL('image/png').substring(22);
                        })(arguments[0]);
                        """,
                        canvas
                    )
                    qr_bytes = base64.b64decode(b64_qr)
                    qr_path = self.session_dir / "qr.png"
                    qr_path.write_bytes(qr_bytes)
                    logger.debug(
                        f"[WORKER] QR capturado ({len(qr_bytes)} bytes)"
                    )
                except (NoSuchElementException, StaleElementReferenceException):
                    pass  # Silenciar errores de elemento no encontrado
                except Exception as e:
                    logger.debug(f"[WORKER] Error capturando QR: {e}")

                time.sleep(2)  # Capturar cada 2 segundos

            # 5. Esperar autenticación (detect chat-list)
            authenticated = self._wait_for_authentication(timeout=60)

            if not authenticated:
                logger.warning(
                    f"[WORKER] No se detectó autenticación para {self.session_id}"
                )
                self.state = SessionState.FAILED
                return

            # 6. Dar tiempo para que WhatsApp se estabilice
            time.sleep(3)

            # 7. Extraer datos de chats y contactos
            self._extract_data()

            # 8. Finalizar y comprimir evidencias
            self._finalize_evidence()

            # Cambiar estado a completado
            self.state = SessionState.COMPLETED
            logger.info(
                f"[WORKER] ✅ Sesión {self.session_id} completada exitosamente"
            )

        except Exception as e:
            logger.error(
                f"[WORKER] ❌ Error no manejado en sesión {self.session_id}: {e}",
                exc_info=True
            )
            self.state = SessionState.FAILED

        finally:
            if self.state is SessionState.COMPLETED:
                # Se conserva el navegador para inspección posterior a la
                # extracción. ``stop()`` sigue siendo el cierre explícito.
                logger.info(
                    "[WORKER] Extracción completada; Firefox permanece abierto "
                    "para la sesión %s", self.session_id
                )
            else:
                # En cancelaciones o fallos se liberan recursos como antes.
                self.stop()

            self._remove_session_logging()

    def stop(self):
        """Detener la sesión y liberar recursos (driver, threading)."""
        logger.info(f"[WORKER] Deteniendo sesión {self.session_id}...")

        self._stop_event.set()

        # Cerrar driver Firefox
        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"[WORKER] Driver Firefox cerrado")
            except Exception:
                # Ignorar silenciosamente excepciones de socket/conexión si driver ya se cerró
                pass

        logger.info(f"[WORKER] Sesión {self.session_id} detenida")

    def get_state(self):
        """Obtener el estado actual de la sesión."""
        return self.state

    def is_running(self):
        """Verificar si el worker está en ejecución."""
        return self.is_alive() and not self._stop_event.is_set()
