#!/usr/bin/env python3
"""
SessionOrchestrator: Gestor centralizado de sesiones de auditoría.
Administra múltiples SessionWorker de forma concurrente con límites de recursos.
"""

import logging
import threading
import uuid
from typing import Dict, Optional, List
from datetime import datetime

from modules.session_worker import SessionWorker, SessionState

logger = logging.getLogger(__name__)


class SessionOrchestrator:
    """
    Orquestador centralizado para gestionar múltiples sesiones de auditoría.
    Limita el número de sesiones simultáneas y proporciona métodos para monitoreo.
    """

    # Límite máximo de sesiones simultáneas
    MAX_CONCURRENT_SESSIONS = 4

    def __init__(self, output_dir="./evidencias"):
        """
        Inicializar el orquestador de sesiones.

        Args:
            output_dir (str): Directorio base para evidencias de todas las sesiones
        """
        self.output_dir = output_dir

        # Diccionario de sesiones activas: {session_id -> SessionWorker}
        self.sessions: Dict[str, SessionWorker] = {}

        # Lock para acceso thread-safe al diccionario de sesiones
        self.lock = threading.RLock()

        logger.info(
            f"[ORCHESTRATOR] Inicializado con máximo de "
            f"{self.MAX_CONCURRENT_SESSIONS} sesiones simultáneas"
        )

    def _generate_short_session_id(self) -> str:
        """
        Generar un UUID4 corto de 8 caracteres.

        Returns:
            str: ID de sesión de 8 caracteres hex (primeros 8 de un UUID4)
        """
        full_uuid = str(uuid.uuid4()).replace("-", "")
        return full_uuid[:8]

    def _get_active_sessions_count(self) -> int:
        """
        Contar sesiones activas (en ejecución o pendientes).

        Returns:
            int: Número de sesiones activas/vivas
        """
        with self.lock:
            # Contar sesiones que están vivas (thread en ejecución)
            active_count = sum(
                1 for worker in self.sessions.values()
                if worker.is_alive()
            )
            return active_count

    def create_session(self, max_chats: Optional[int] = None) -> Optional[str]:
        """
        Crear y arrancar una nueva sesión de auditoría.

        Valida que no se supere el límite de sesiones simultáneas,
        genera un session_id único, instancia SessionWorker y lo arranca.

        Args:
            max_chats: Máximo de chats a extraer; ``None`` extrae todos.

        Returns:
            str: El session_id generado, o None si se alcanzó el límite
        """
        with self.lock:
            # Verificar límite de sesiones
            active_count = self._get_active_sessions_count()

            if active_count >= self.MAX_CONCURRENT_SESSIONS:
                logger.warning(
                    f"[ORCHESTRATOR] Límite de sesiones simultáneas alcanzado "
                    f"({active_count}/{self.MAX_CONCURRENT_SESSIONS})"
                )
                return None

            # Generar session_id único
            session_id = self._generate_short_session_id()

            # Asegurar unicidad (muy improbable, pero por seguridad)
            while session_id in self.sessions:
                session_id = self._generate_short_session_id()

            try:
                # Instanciar SessionWorker
                worker = SessionWorker(
                    session_id=session_id,
                    output_dir=self.output_dir,
                    max_chats=max_chats,
                )

                # Almacenar en diccionario
                self.sessions[session_id] = worker

                # Arrancar el hilo
                worker.start()

                logger.info(
                    f"[ORCHESTRATOR] ✅ Sesión creada: {session_id} "
                    f"({active_count + 1}/{self.MAX_CONCURRENT_SESSIONS})"
                )

                return session_id

            except Exception as e:
                logger.error(
                    f"[ORCHESTRATOR] ❌ Error al crear sesión {session_id}: {e}",
                    exc_info=True
                )
                # Limpiar entrada en caso de error
                if session_id in self.sessions:
                    del self.sessions[session_id]
                return None

    def get_status(self, session_id: str) -> Optional[Dict]:
        """
        Obtener el estado de ejecución de una sesión.

        Args:
            session_id (str): ID de la sesión a consultar

        Returns:
            dict: Diccionario con estado de la sesión, o None si no existe
                  {
                    'session_id': str,
                    'state': str (enum value),
                    'is_running': bool,
                    'is_alive': bool,
                    'created_at': str (ISO timestamp),
                  }
        """
        with self.lock:
            if session_id not in self.sessions:
                logger.warning(
                    f"[ORCHESTRATOR] Sesión no encontrada: {session_id}"
                )
                return None

            worker = self.sessions[session_id]

            status = {
                'session_id': session_id,
                'state': worker.get_state().value,  # Enum value (string)
                'is_running': worker.is_running(),
                'is_alive': worker.is_alive(),
                'created_at': datetime.now().isoformat(),
            }

            return status

    def get_all_sessions_status(self) -> Dict[str, Dict]:
        """
        Obtener el estado de todas las sesiones activas.

        Returns:
            dict: Diccionario con estado de cada sesión activa
                  {session_id: status_dict, ...}
        """
        with self.lock:
            all_status = {}
            for session_id in self.sessions.keys():
                status = self.get_status(session_id)
                if status:
                    all_status[session_id] = status
            return all_status

    def stop_session(self, session_id: str) -> bool:
        """
        Detener una sesión de forma limpia.

        Libera recursos, cierra el driver Firefox y elimina del registro.

        Args:
            session_id (str): ID de la sesión a detener

        Returns:
            bool: True si se detuvo correctamente, False si no existe
        """
        with self.lock:
            if session_id not in self.sessions:
                logger.warning(
                    f"[ORCHESTRATOR] No se puede detener: sesión no encontrada: {session_id}"
                )
                return False

            try:
                worker = self.sessions[session_id]

                # Detener el worker
                logger.info(f"[ORCHESTRATOR] Deteniendo sesión {session_id}...")
                worker.stop()

                # Esperar a que el hilo termine (con timeout)
                worker.join(timeout=10)

                # Eliminar del registro
                del self.sessions[session_id]

                logger.info(
                    f"[ORCHESTRATOR] ✅ Sesión detenida: {session_id}"
                )
                return True

            except Exception as e:
                logger.error(
                    f"[ORCHESTRATOR] ❌ Error deteniendo sesión {session_id}: {e}",
                    exc_info=True
                )
                # Intentar limpiar de todas formas
                if session_id in self.sessions:
                    del self.sessions[session_id]
                return False

    def stop_all_sessions(self) -> int:
        """
        Detener todas las sesiones activas.

        Returns:
            int: Número de sesiones detenidas
        """
        with self.lock:
            session_ids = list(self.sessions.keys())
            stopped_count = 0

            for session_id in session_ids:
                if self.stop_session(session_id):
                    stopped_count += 1

            logger.info(
                f"[ORCHESTRATOR] Se detuvieron {stopped_count} sesiones"
            )
            return stopped_count

    def get_active_sessions_list(self) -> List[str]:
        """
        Obtener lista de IDs de sesiones activas.

        Returns:
            list: Lista de session_ids activos
        """
        with self.lock:
            return [
                session_id
                for session_id, worker in self.sessions.items()
                if worker.is_alive()
            ]

    def get_capacity_info(self) -> Dict:
        """
        Obtener información sobre la capacidad del orquestador.

        Returns:
            dict: {
                'max_concurrent': int,
                'active_sessions': int,
                'available_slots': int,
                'can_create_new': bool,
            }
        """
        with self.lock:
            active = self._get_active_sessions_count()
            available = self.MAX_CONCURRENT_SESSIONS - active

            return {
                'max_concurrent': self.MAX_CONCURRENT_SESSIONS,
                'active_sessions': active,
                'available_slots': max(0, available),
                'can_create_new': available > 0,
            }


# Instancia global única del orquestador
orchestrator = SessionOrchestrator()
