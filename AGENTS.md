# Contexto del Proyecto
Este proyecto es una herramienta de auditoría forense y concientización sobre seguridad en entornos controlados para WhatsApp Web. Evalúa el manejo de información en memoria de React Fiber mediante arquitecturas multisesión aisladas.

# Reglas de Desarrollo
1. ENFOQUE ESTRICTO: Procesar únicamente mensajes de texto. Ignorar imágenes, videos, audios, documentos, stickers y cadenas base64.
2. EXTRACCIÓN HÍBRIDA DE METADATOS Y TEXTO: La extracción se realiza prioritariamente desde el árbol de React Fiber accediendo a las propiedades internas (`memoizedProps.msg`). Si Fiber devuelve identificadores internos (como `@lid`), usar como respaldo el atributo DOM `data-pre-plain-text` buscando en el nodo, sus hijos o sus ancestros mediante `.closest()`.
3. ROBUSTEZ Y DOM DINÁMICO: 
   - Prevenir y manejar `StaleElementReferenceException` reobteniendo los elementos de la lista de chats en cada iteración.
   - Tratar los IDs de mensaje estrictamente como cadenas de texto (`str`).
   - Deduplicar mensajes mediante su `id` único.
4. FORMATO DE SALIDA: Los archivos JSON incluyen `id`, `text`, `timestamp`, `datetime` (YYYY-MM-DD HH:MM:SS), `from_me` y `sender`, ordenados cronológicamente.
5. EXTRACCIÓN DE LIBRETA: Abrir "Nuevo chat", hacer scroll e iterar sobre los listitem mediante React Fiber para localizar `props.contact`.
6. ARQUITECTURA MULTISESIÓN AISLADA:
   - Cada sesión de auditoría corre en un hilo independiente (`threading.Thread`) asignado a un `session_id` único (UUID4).
   - Cada hilo instancia su propia sesión de Firefox Headless usando un directorio de perfil único (`-profile evidencias/<session_id>/firefox_profile`) para evitar colisiones de almacenamiento local y cookies.
   - Cada hilo guarda de manera aislada en `./evidencias/<session_id>/`.
   - Cada hilo configura un logger dedicado/handler independiente que escribe únicamente los eventos generados por ese hilo en `./evidencias/<session_id>/session.log` (además del log consolidado general), y debe removerlo al finalizar para evitar duplicados y fugas de memoria.
   - CICLO DE VIDA DEL NAVEGADOR: No ejecutar `driver.quit()` ni `driver.close()` automáticamente al finalizar la extracción exitosa; la instancia de Firefox debe permanecer abierta e interactiva hasta un cierre explícito de la sesión.
7. SERVIDOR WEB DE CONCIENTIZACIÓN:
   - Utilizar Flask sirviendo en un hilo demonio en el puerto 8080.
   - Rutas dinámicas: `/demo/<session_id>` para la pantalla de inicio de sesión y `/qr/<session_id>/qr.png` para la imagen QR individual.
8. TOLERANCIA Y TIEMPOS DE ESPERA EXTENDIDOS:
   - Configurar `WebDriverWait` con un tiempo mínimo de 45 a 60 segundos.
   - Configurar pausas de scroll e inyección JS de entre 2.0 y 2.5 segundos para garantizar la renderización completa de React en ejecuciones concurrentes.
