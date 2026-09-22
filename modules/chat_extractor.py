# modules/chat_extractor.py
# WhatsApp Forensic Extractor v1.0

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

logger = logging.getLogger(__name__)

JS_EXTRACT_ALL_MESSAGES = r'''return JSON.stringify((function(){
    let results = [];
    let mensajes = document.querySelectorAll('[data-testid*="conv-msg"]');
    mensajes.forEach(msgNode => {
        let fiberKey = Object.keys(msgNode).find(k =>
            k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
        );
        if (fiberKey) {
            let current = msgNode[fiberKey];
            let nivel = 0;
            while (current && nivel < 15) {
                let props = current.memoizedProps;
                if (props && props.msg) {
                    let msg = props.msg;
                    let body = msg.body || "";
                    let msgId = null;
                    if (msg.id) {
                        if (typeof msg.id === "string") {
                            msgId = msg.id;
                        } else if (msg.id._serialized) {
                            msgId = String(msg.id._serialized);
                        } else if (msg.id.id) {
                            msgId = String(msg.id.id);
                        } else {
                            msgId = JSON.stringify(msg.id);
                        }
                    }
                    // data-id contiene el hash interno del mensaje. En objetos
                    // Fiber se expone directamente mediante msg.id.id.
                    let coreId = "";
                    if (msg.id && typeof msg.id === "object" && msg.id.id) {
                        coreId = String(msg.id.id);
                    } else if (msg.id) {
                        const rawCoreId = typeof msg.id === "object" ?
                            msg.id._serialized : msg.id;
                        const coreMatch = String(rawCoreId || "").match(
                            /(?:_|^)([A-F0-9]{16,32})(?:_|$)/i
                        );
                        coreId = coreMatch ? coreMatch[1] : "";
                    }
                    const invalidSender = value => {
                        const normalized = String(value || "").trim();
                        return !normalized ||
                            normalized.toLowerCase() === "desconocido" ||
                            /@(lid|c\.us|g\.us)\b/i.test(normalized) ||
                            /^\d{14,}$/.test(normalized);
                    };
                    let sender = "Desconocido";
                    if (msg.id && msg.id.fromMe) {
                        sender = "Yo";
                    } else {
                        // Intento 1: datos disponibles desde React Fiber.
                        let rawAuthor = "";
                        if (msg.author) {
                            if (typeof msg.author === "string") {
                                rawAuthor = msg.author;
                            } else if (msg.author._serialized) {
                                rawAuthor = String(msg.author._serialized);
                            } else if (msg.author.user) {
                                rawAuthor = String(msg.author.user);
                            } else {
                                rawAuthor = String(msg.author);
                            }
                        }
                        sender = (msg.senderObj && msg.senderObj.formattedTitle) ||
                            (msg.senderObj && msg.senderObj.name) ||
                            msg.pushName ||
                            (rawAuthor ?
                                rawAuthor.replace("@c.us", "").replace("@g.us", "") : null);

                        // Intento 2: priorizar el nombre visible del DOM cuando
                        // Fiber solo devuelve identificadores internos (@lid, etc.).
                        if (invalidSender(sender)) {
                            let preEl = null;
                            // Buscar solo alrededor de la fila de este mensaje,
                            // evitando ascender hasta otras filas del panel.
                            let curr = msgNode;
                            let depth = 0;
                            while (curr && depth < 5 && curr !== document.body) {
                                if (curr.getAttribute &&
                                    curr.getAttribute("data-pre-plain-text")) {
                                    preEl = curr;
                                    break;
                                }
                                let inner = curr.querySelector(
                                    "[data-pre-plain-text]"
                                );
                                if (inner) {
                                    preEl = inner;
                                    break;
                                }
                                if (curr.getAttribute &&
                                    (curr.getAttribute("role") === "row" ||
                                    (curr.getAttribute("data-testid") &&
                                    curr.getAttribute("data-testid").includes(
                                        "msg-"
                                    )))) {
                                    let rowMatch = curr.querySelector(
                                        "[data-pre-plain-text]"
                                    );
                                    if (rowMatch) {
                                        preEl = rowMatch;
                                    }
                                    break;
                                }
                                curr = curr.parentElement;
                                depth++;
                            }
                            // Respaldo por coreId si el recorrido local no lo halló.
                            if (!preEl && coreId) {
                                let domNode = document.querySelector(
                                    '[data-id*="' + coreId + '"]'
                                );
                                if (domNode) {
                                    preEl = domNode.getAttribute("data-pre-plain-text") ?
                                        domNode : domNode.querySelector(
                                            "[data-pre-plain-text]"
                                        );
                                }
                            }
                            if (preEl) {
                                const attr = preEl.getAttribute("data-pre-plain-text");
                                const match = attr ? attr.match(/\]\s+(.*?):\s*$/) : null;
                                if (match && match[1] && match[1].trim()) {
                                    sender = match[1].trim();
                                }
                            }
                            // Último respaldo Fiber: un user telefónico real.
                            if (invalidSender(sender)) {
                                const senderSources = [
                                    msg.senderObj, msg.contact, msg.author
                                ];
                                for (let index = 0; index < senderSources.length; index++) {
                                    const source = senderSources[index];
                                    const phoneCandidates = [
                                        source && source.id && source.id._serialized,
                                        source && source.id && source.id.user,
                                        source && source.phoneNumber,
                                        source && source.user
                                    ];
                                    for (let phoneIndex = 0;
                                        phoneIndex < phoneCandidates.length;
                                        phoneIndex++) {
                                        const user = String(
                                            phoneCandidates[phoneIndex] || ""
                                        ).replace(/@(lid|c\.us|g\.us)$/i, "");
                                        if (/^\d{8,13}$/.test(user)) {
                                            sender = "+" + user;
                                            break;
                                        }
                                    }
                                    if (!invalidSender(sender)) {
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    if (invalidSender(sender)) {
                        sender = "Desconocido";
                    }
                    // Ignorar multimedia: cuerpos vacios y cadenas base64 (ej. /9j/).
                    if (body.trim() !== "" && !body.startsWith("/9j/")) {
                        results.push({
                            id: msgId,
                            text: body,
                            timestamp: msg.t,
                            from_me: msg.id ? msg.id.fromMe : false,
                            sender: sender
                        });
                    }
                    break;
                }
                current = current.return;
                nivel++;
            }
        }
    });
    return results;
})());'''

JS_SCROLL_UP = r'''
var historyControls = document.querySelectorAll(
    'button, [role="button"], [data-testid*="older"], [data-testid*="history"]'
);
for (var i = 0; i < historyControls.length; i++) {
    var controlText = (historyControls[i].textContent || '').trim().toLowerCase();
    if (controlText.includes('older messages') ||
        controlText.includes('load older') ||
        controlText.includes('mensajes más antiguos') ||
        controlText.includes('mensajes mas antiguos')) {
        try {
            historyControls[i].click();
        } catch (error) {}
        break;
    }
}
var panel = document.querySelector('div[data-testid="conversation-panel-messages"]') || document.querySelector('#main .copyable-area') || document.querySelector('#main');
if(!panel) return '0|0';
var before = panel.scrollTop;
panel.scrollTop = Math.max(0, panel.scrollTop - 400);
var after = panel.scrollTop;
var moved = before - after;
if(moved <= 0 && panel.parentElement){
    panel.parentElement.scrollTop = Math.max(0, panel.parentElement.scrollTop - 400);
    moved = before - panel.scrollTop;
}
return String(moved) + '|' + String(after);
'''

JS_EXTRACT_FULL_CONTACTS = r'''
const done = arguments[arguments.length - 1];
(async () => {
    const contactos = new Map();
    const celdasEjemplo = document.querySelector('div[data-testid="cell-frame-container"]');
    if (!celdasEjemplo) {
        done([]);
        return;
    }

    let scrollContainer = celdasEjemplo.parentElement;
    while (scrollContainer && scrollContainer.scrollHeight <= scrollContainer.clientHeight) {
        scrollContainer = scrollContainer.parentElement;
    }
    if (!scrollContainer) scrollContainer = document.querySelector('div[data-testid="drawer-left"]') || document.body;

    const extraerVisibles = () => {
        const celdas = document.querySelectorAll('div[data-testid="cell-frame-container"]');
        celdas.forEach(celda => {
            const fiberKey = Object.keys(celda).find(k => k.startsWith('__reactFiber'));
            if (!fiberKey) return;

            let curr = celda[fiberKey];
            let phone = null;
            let name = null;

            while (curr) {
                const props = curr.memoizedProps || curr.pendingProps;
                if (props) {
                    const c = props.contact || props.item?.contact || props.data?.contact || props.item;
                    if (c && typeof c === 'object') {
                        name = c.name || c.formattedName || c.pushname || c.displayName || name;
                        if (c.phoneNumber) {
                            phone = typeof c.phoneNumber === 'string' ? c.phoneNumber : c.phoneNumber.user;
                        } else if (c.pn) {
                            phone = typeof c.pn === 'object' ? c.pn.user : String(c.pn).split('@')[0];
                        } else if (c.id) {
                            phone = c.id.user || (typeof c.id === 'string' ? c.id.split('@')[0] : null);
                        }
                        if (phone && name) break;
                    }
                }
                curr = curr.return;
            }

            if (!name) {
                const titleEl = celda.querySelector('span[title]') || celda.querySelector('div[title]');
                if (titleEl) name = titleEl.getAttribute('title');
            }

            if (name && phone) {
                const numLimpio = phone.startsWith('+') ? phone : `+${phone}`;
                contactos.set(name, { nombreVisible: name, numero: numLimpio });
            }
        });
    };

    let lastScroll = -1;
    for (let i = 0; i < 100; i++) {
        extraerVisibles();
        scrollContainer.scrollTop += 450;
        await new Promise(r => setTimeout(r, 350));
        if (scrollContainer.scrollTop === lastScroll) break;
        lastScroll = scrollContainer.scrollTop;
    }

    done(Array.from(contactos.values()));
})().catch(error => {
    console.error('Error extrayendo contactos:', error);
    done([]);
});
'''


def _looks_like_phone_number(name):
    return bool(name and re.match(r'^[\+\d\s\(\)\-]{7,}$', str(name).strip()))


class ChatExtractor:
    def __init__(self, session_manager, output_dir="evidencias"):
        self.sm = session_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.chats_data = []

    def _safe_filename(self, name):
        safe = re.sub(r'[\\/*?:"<>|]', "_", str(name))
        return safe.strip() or "chat"

    def _inject_js(self, script):
        try:
            return self.sm.driver.execute_script(script)
        except StaleElementReferenceException:
            logger.debug("  DOM stale durante la inyeccion JS.")
            return None
        except Exception as error:
            logger.debug("  Error de inyeccion JS: %s", error)
            return None

    def _scroll_up(self, amount=400):
        result = self._inject_js(JS_SCROLL_UP.replace('400', str(amount)))
        if not isinstance(result, str) or '|' not in result:
            return 0, 0
        try:
            moved, position = result.split('|', 1)
            return int(moved), int(position)
        except ValueError:
            return 0, 0

    def _scroll_and_extract(self, max_steps=300, pause=2.0):
        """Extrae desde React Fiber, deduplicando por ID durante el scroll."""
        logger.info("  Extrayendo mensajes desde React Fiber (%s pasos)...", max_steps)
        seen_messages = {}
        no_new_count = 0
        last_scroll_pos = None
        stuck_count = 0

        for step in range(max_steps):
            try:
                raw = self.sm.driver.execute_script(JS_EXTRACT_ALL_MESSAGES)
            except StaleElementReferenceException:
                logger.debug("  DOM stale en paso %s; reintentando.", step + 1)
                continue
            except Exception as error:
                logger.warning("  Error al extraer con React Fiber: %s", error)
                raw = None

            try:
                batch = json.loads(raw) if raw else []
                if not isinstance(batch, list):
                    raise ValueError("La respuesta JS no es una lista")
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                logger.warning("  Error al parsear la respuesta de React Fiber: %s", error)
                batch = []

            new_count = 0
            for message in batch:
                if not isinstance(message, dict):
                    continue
                message_id = message.get("id")
                if isinstance(message_id, dict):
                    message_id = (
                        message_id.get("_serialized")
                        or message_id.get("id")
                        or json.dumps(message_id, sort_keys=True)
                    )
                elif message_id is not None:
                    message_id = str(message_id)
                if message_id is not None and message_id not in seen_messages:
                    seen_messages[message_id] = message
                    new_count += 1

            _, pos = self._scroll_up(amount=400)
            stuck_count = stuck_count + 1 if pos == last_scroll_pos else 0
            last_scroll_pos = pos

            if new_count:
                logger.info("    +%s mensajes nuevos (total: %s)", new_count, len(seen_messages))
                no_new_count = 0
            else:
                no_new_count += 1
                if no_new_count >= 5 or stuck_count >= 3:
                    logger.info("  Fin del historial tras %s pasos.", step + 1)
                    break
            time.sleep(pause)
        else:
            logger.info("  Limite de pasos alcanzado (%s).", max_steps)

        return seen_messages

    def extract_chat_messages(self, max_steps=300, scroll_pause=2.0, chat_name=""):
        """Devuelve solo mensajes de texto, ordenados por timestamp Unix."""
        logger.info("  Extrayendo mensajes de texto desde React Fiber...")
        seen_messages = {}
        for attempt in range(3):
            seen_messages = self._scroll_and_extract(max_steps=max_steps, pause=scroll_pause)
            if seen_messages:
                break
            logger.warning("  Intento %s retorno vacio; reintentando...", attempt + 1)
            time.sleep(2.0)

        if not seen_messages:
            logger.error("  No se extrajo ningun mensaje tras 3 intentos.")
            return []

        messages = list(seen_messages.values())
        messages.sort(key=lambda message: int(message.get("timestamp") or 0))
        formatted = []
        for message in messages:
            ts = message.get("timestamp")
            if ts:
                try:
                    message["datetime"] = datetime.fromtimestamp(ts).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception:
                    message["datetime"] = None
            else:
                message["datetime"] = None
            formatted.append({
                "id": message.get("id"),
                "text": message.get("text"),
                "timestamp": ts,
                "from_me": bool(message.get("from_me", False)),
                "sender": message.get("sender") or "Desconocido",
                "datetime": message["datetime"],
            })
        logger.info("  %s mensajes unicos extraidos y ordenados.", len(formatted))
        return formatted

    def extract_all(self, max_chats=None, msg_steps=300):
        logger.info("Iniciando extraccion de chats (React Fiber)...")
        chats = self.sm.get_chat_elements()
        if not chats:
            logger.error("No se encontraron chats.")
            return False

        if (
            isinstance(max_chats, int)
            and not isinstance(max_chats, bool)
            and max_chats > 0
        ):
            chats = chats[:max_chats]
            logger.info(
                "Limite aplicado: procesando los primeros %s chats de la lista.",
                len(chats),
            )

        total_chats = len(chats)
        logger.info("%s chats detectados.", total_chats)

        for idx in range(total_chats):
            try:
                # Los WebElement no se conservan entre iteraciones: WhatsApp
                # vuelve a renderizar la barra lateral al abrir cada chat.
                current_chats = self.sm.get_chat_elements()
                if idx >= len(current_chats):
                    logger.warning("Indice %s ya no existe en la barra lateral.", idx)
                    continue
                chat_el = current_chats[idx]
                chat_info = self.sm.get_chat_info(chat_el)
                chat_name = chat_info["name"]
                safe_name = self._safe_filename(chat_name)
                logger.info("[%s/%s] Chat sidebar: '%s'", idx + 1, total_chats, chat_name)
                if not self.sm.open_chat_by_index(idx):
                    logger.error("  No se pudo abrir el chat '%s'.", chat_name)
                    continue
                if not self.sm._is_chat_opened():
                    time.sleep(2.0)
                    if not self.sm._is_chat_opened():
                        logger.error("  Chat '%s' no se abrio.", chat_name)
                        continue
                if _looks_like_phone_number(chat_name):
                    header_name = self.sm.get_open_chat_header_name()
                    if header_name and header_name != chat_name:
                        chat_name = header_name
                        safe_name = self._safe_filename(chat_name)
                time.sleep(5.0)
                messages = self.extract_chat_messages(max_steps=msg_steps, scroll_pause=2.0, chat_name=chat_name)
                chat_data = {"index": idx, "name": chat_name, "message_count": len(messages),
                             "extracted_at": datetime.now().isoformat(), "messages": messages}
                self.chats_data.append(chat_data)
                out_file = self.output_dir / f"chat_{idx:03d}_{safe_name}.json"
                with open(out_file, "w", encoding="utf-8") as file:
                    json.dump(chat_data, file, ensure_ascii=False, indent=2)
                logger.info("  Guardado: %s", out_file.name)
            except Exception as error:
                logger.error("  Error: %s", error)
            time.sleep(1.0)

        consolidated = self.output_dir / "all_chats.json"
        with open(consolidated, "w", encoding="utf-8") as file:
            json.dump(self.chats_data, file, ensure_ascii=False, indent=2)
        total_msgs = sum(chat["message_count"] for chat in self.chats_data)
        logger.info("Total chats: %s, mensajes: %s", len(self.chats_data), total_msgs)
        return True

    def extract_contacts(self):
        logger.info("Extrayendo contactos...")
        contacts = []
        for chat in self.sm.get_chat_elements():
            info = self.sm.get_chat_info(chat)
            if info["name"] and info["name"] != "Sin nombre":
                contacts.append({"name": info["name"], "preview": info["preview"]})
        contacts_file = self.output_dir / "contacts.json"
        with open(contacts_file, "w", encoding="utf-8") as file:
            json.dump(contacts, file, ensure_ascii=False, indent=2)
        logger.info("%s contactos guardados en %s", len(contacts), contacts_file)
        report = self.output_dir / "REPORTE.txt"
        with open(report, "w", encoding="utf-8") as file:
            file.write("WhatsApp Forensic Extractor v1.0\n")
            file.write(f"Fecha: {datetime.now().isoformat()}\n")
            file.write(f"Chats: {len(self.chats_data)}\n")
            file.write(f"Mensajes totales: {sum(c['message_count'] for c in self.chats_data)}\n\n")
            for chat in self.chats_data:
                file.write(f"- {chat['name']}: {chat['message_count']} msgs\n")
        logger.info("Reporte: %s", report)

    def extract_full_contacts(self):
        """Extrae la libreta completa visible desde el panel Nuevo chat.

        El recorrido, scroll y lectura de React Fiber se ejecutan de forma
        asíncrona dentro del navegador; Selenium recibe el resultado final por
        el callback de ``execute_async_script``.
        """
        logger.info("Extrayendo libreta completa desde el panel Nuevo chat...")
        try:
            self.sm.driver.set_script_timeout(60)
            result = self.sm.driver.execute_async_script(JS_EXTRACT_FULL_CONTACTS)
        except TimeoutException:
            logger.warning("Timeout durante la extracción asíncrona de contactos.")
            return []
        except StaleElementReferenceException:
            logger.warning("El panel de contactos cambió durante la extracción.")
            return []
        except Exception as error:
            logger.warning("Error al extraer la libreta completa: %s", error)
            return []

        if not isinstance(result, list):
            logger.warning("Respuesta inesperada del script de contactos: %r", type(result))
            return []

        contacts_by_key = {}
        for contact in result:
            if not isinstance(contact, dict):
                continue
            name = str(contact.get("nombreVisible") or "Desconocido").strip()
            number = str(contact.get("numero") or "No disponible").strip()
            if not name or number == "No disponible":
                continue
            contacts_by_key.setdefault(
                number, {"nombreVisible": name, "numero": number}
            )

        contacts = list(contacts_by_key.values())
        logger.info("%s contactos unicos extraidos de la libreta.", len(contacts))
        return contacts
