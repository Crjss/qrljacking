# Demostrador de Evaluación de Seguridad Forense en WhatsApp Web

> **Uso exclusivo en entornos controlados y autorizados.** Este proyecto tiene fines académicos, de concientización y de análisis forense. No debe utilizarse con cuentas, conversaciones, contactos o dispositivos de terceros sin autorización expresa.

## Descripción

Demostrador técnico para estudiar riesgos de vinculación mediante QR en aplicaciones web, automatización de navegador y preservación de evidencias digitales. Incluye una interfaz de concientización, orquestación de sesiones aisladas y generación de artefactos de evidencia basados en texto.

## Características

- Sesiones concurrentes aisladas por identificador, hilo, perfil de Firefox y directorio de salida.
- Interfaz Flask de laboratorio para visualización de la imagen QR por sesión.
- Extracción limitada a mensajes de texto y metadatos asociados.
- Manejo de DOM dinámico y listas virtualizadas mediante Selenium y estructuras React Fiber.
- Evidencias JSON, registro de sesión, hashes SHA-256, manifiesto y archivo ZIP.

## Arquitectura

```text
main.py
  ├── server/server.py                # Servidor Flask e interfaz de laboratorio
  └── modules/session_orchestrator.py # Gestión de sesiones
        └── session_worker.py          # Navegador y flujo por sesión
              ├── session_manager.py  # Operaciones Selenium
              ├── chat_extractor.py   # Adquisición de texto
              └── output_manager.py   # Evidencias e integridad
```

## Requisitos

- Python 3.10 o superior.
- Firefox instalado.
- Geckodriver compatible disponible en `PATH` (o Selenium Manager en un entorno compatible).
- Cuenta, datos y red de laboratorio autorizados.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Dependencias Python: `Flask>=3.0.0` y `selenium>=4.15.0`.

## Uso

Ejecute desde la raíz del proyecto:

```bash
python3 main.py
```

El menú permite crear una sesión, consultar su estado o detener todas las sesiones. Al crearla, introduzca un número positivo para limitar las conversaciones procesadas; use `0` o Enter para no aplicar límite. El servidor Flask se inicia en el puerto 8080.

No exponga las rutas de sesión fuera del laboratorio ni comparta códigos QR de vinculación.

## Evidencias generadas

Cada sesión se guarda en `evidencias/<session_id>/` e incluye, según corresponda:

- `chats.json` y `all_chats.json`: resultados consolidados.
- `chat_<índice>_<nombre>.json`: resultado individual por conversación.
- `contacts.json`: contactos obtenidos en el escenario autorizado.
- `session.log`: bitácora de la sesión.
- `hashes.json`: hashes SHA-256 de los artefactos existentes al momento de su generación.
- `MANIFEST.json`: inventario de archivos, tamaños y marcas temporales.
- `evidencias_<session_id>.zip`: paquete comprimido final.

Los hashes apoyan la verificación de integridad, pero el ZIP no dispone actualmente de firma digital ni sello de tiempo. Un procedimiento pericial debe complementar estos artefactos con control de acceso, registro de transferencias y preservación inmutable.

## Estructura del proyecto

```text
.
├── main.py
├── requirements.txt
├── config.py
├── server/
│   ├── server.py
│   └── templates/phishing_page.html
├── modules/
│   ├── session_orchestrator.py
│   ├── session_worker.py
│   ├── session_manager.py
│   ├── chat_extractor.py
│   └── output_manager.py
├── evidencias/
└── logs/
```

## Seguridad y privacidad

Los directorios `evidencias/`, `logs/` y los perfiles de navegador pueden contener información sensible. No los publique en repositorios ni los transfiera sin controles de acceso, autorización y una política de retención definida.
