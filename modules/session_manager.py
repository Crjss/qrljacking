#!/usr/bin/env python3
"""
Gestion de sesion Selenium activa de WhatsApp Web.
v1.0: get_open_chat_header_name() reescrito con selectores quirurgicos
      y filtrado de status/tooltips. Solo devuelve nombres reales.
"""
import time
import logging
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException,
    NoSuchElementException, ElementClickInterceptedException
)

logger = logging.getLogger(__name__)

CHAT_LIST_SELECTORS = [
    'div[data-testid="chat-list"]',
    'div[aria-label="Chat list"]',
    '#pane-side',
    'div[data-testid="conversation-list"]',
]

CHAT_ITEM_SELECTORS = [
    'div[data-testid="chat-list"] div[role="listitem"]',
    'div[aria-label="Chat list"] div[role="listitem"]',
    '#pane-side div[role="listitem"]',
    'div[data-testid="conversation-list"] div[role="row"]',
    'div[data-testid="cell-frame-container"]',
    '#pane-side div[data-testid*="cell-frame"]',
]

MSG_CONTAINER_SELECTORS = [
    'div[data-id]',
    'div[data-testid="msg-container"]',
    'div.message-in, div.message-out',
    'div[data-testid="message-container"]',
]

MSG_PANEL_SELECTORS = [
    'div[data-testid="conversation-panel-messages"]',
    '#main .copyable-area',
    '#app > div > div > div:nth-child(4) > div',
    '#main',
]

NEW_CHAT_BUTTON_SELECTORS = [
    'button[data-tab="2"]',
    'button[aria-label="Nuevo chat"]',
    'button[aria-label="New chat"]',
]
CONTACT_LIST_SELECTORS = [
    'div[aria-label="Contactos"] div[role="listitem"]',
    '[data-testid="contact-list-key"] div[role="listitem"]',
    'div[role="listitem"]',
]

# Patrones que indican que un texto del header NO es un nombre de chat
_STATUS_PATTERNS = [
    r'^profile\s+details?$',
    r'^last\s+seen',
    r'^online$',
    r'^typing',
    r'^click\s+here',
    r'^last\s+active',
    r'^available',
    r'^busy',
    r'^at\s+work',
    r'^in\s+a\s+meeting',
    r'^\d+\s+participants',
    r'^you$',
]


def _is_likely_status(text):
    """True si el texto parece ser un status/last-seen/tooltip, no un nombre."""
    if not text:
        return True
    t = text.strip().lower()
    if len(t) > 80:
        return True  # Listas de participantes de grupos son muy largas
    for pat in _STATUS_PATTERNS:
        if re.search(pat, t):
            return True
    return False


class SessionManager:
    def __init__(self, driver, timeout=45):
        self.driver = driver
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    def wait_for_chat_list(self):
        for sel in CHAT_LIST_SELECTORS:
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                logger.info(f"Lista de chats detectada con selector: {sel}")
                return True
            except TimeoutException:
                continue
        logger.error("No se detecto la lista de chats con ningun selector.")
        return False

    def open_new_chat_panel(self):
        """Abre ``Nuevo chat`` usando selectores CSS y XPath compatibles."""
        short_wait = WebDriverWait(self.driver, 4)

        def contact_list_is_visible():
            for contact_selector in CONTACT_LIST_SELECTORS:
                try:
                    short_wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, contact_selector)
                        )
                    )
                    logger.info(
                        "Panel Nuevo chat abierto (lista detectada con: %s).",
                        contact_selector,
                    )
                    return True
                except TimeoutException:
                    continue
            return False

        for selector in NEW_CHAT_BUTTON_SELECTORS:
            element = None
            try:
                element = short_wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                element.click()
                if contact_list_is_visible():
                    return True
                logger.debug("El selector no mostro la lista: %s", selector)
            except (TimeoutException, NoSuchElementException,
                    StaleElementReferenceException,
                    ElementClickInterceptedException) as error:
                # Si el clic nativo fallo o React reemplazo el nodo, reobtenerlo
                # y usar JavaScript antes de probar el selector siguiente.
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    self.driver.execute_script("arguments[0].click();", element)
                    if contact_list_is_visible():
                        return True
                except (TimeoutException, NoSuchElementException,
                        StaleElementReferenceException,
                        ElementClickInterceptedException) as fallback_error:
                    logger.debug(
                        "Selector Nuevo chat omitido (%s): %s; fallback: %s",
                        selector, error, fallback_error,
                    )
            except Exception as error:
                logger.debug("Error inesperado probando %s: %s", selector, error)

        logger.error("No se localizó el botón Nuevo chat con ningún selector.")
        return False

    def get_chat_elements(self):
        for sel in CHAT_ITEM_SELECTORS:
            try:
                chats = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if chats:
                    logger.debug(f"Chats encontrados con selector '{sel}': {len(chats)}")
                    return chats
            except Exception:
                continue
        logger.warning("No se encontraron chats con ningun selector.")
        try:
            pane = self.driver.find_element(By.CSS_SELECTOR, '#pane-side')
            html = pane.get_attribute('innerHTML')[:500]
            logger.debug(f"HTML del panel lateral (primeros 500 chars): {html}")
        except Exception:
            pass
        return []

    def get_chat_info(self, chat_element):
        name = "Sin nombre"
        try:
            title_el = chat_element.find_element(By.CSS_SELECTOR, "span[title]")
            name = title_el.get_attribute("title") or name
        except NoSuchElementException:
            try:
                title_el = chat_element.find_element(By.CSS_SELECTOR, "div[title]")
                name = title_el.get_attribute("title") or name
            except NoSuchElementException:
                try:
                    name = chat_element.text.split("\n")[0][:50]
                except Exception:
                    pass

        preview = ""
        try:
            preview_el = chat_element.find_element(By.CSS_SELECTOR, "span[data-testid='last-msg-status']")
            preview = preview_el.text
        except NoSuchElementException:
            pass

        return {"name": name, "preview": preview}

    def get_open_chat_header_name(self):
        """
        v1.0: Lee el nombre REAL del contacto o grupo desde el header del chat abierto.
        Usa selectores quirurgicos para evitar capturar status, tooltips o listas de participantes.
        Devuelve None si no puede obtener un nombre valido.
        """
        # Selectores especificos para el nombre del chat en el header de WA Web
        # Ordenados de mas especifico a mas general
        selectors = [
            # Nombre en span[dir="auto"] - el elemento principal del nombre
            '#main header span[dir="auto"]',
            '[data-testid="conversation-header"] span[dir="auto"]',
            # span[title] directamente bajo el header (no en botones)
            '#main header > div span[title]:not([data-testid])',
            '[data-testid="conversation-header"] > div span[title]:not([data-testid])',
            # Elementos con clase tipica de nombre en WA Web
            '#main header ._amig',
            '#main header ._amih',
            '#main header [role="button"] span',
        ]

        for sel in selectors:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                # Primero intentar atributo title (mas confiable)
                name = el.get_attribute("title")
                if name and name.strip() and not _is_likely_status(name):
                    return name.strip()
                # Luego texto visible
                name = el.text
                if name and name.strip() and not _is_likely_status(name):
                    return name.strip()
            except NoSuchElementException:
                continue

        # Fallback: buscar cualquier span dentro del header que tenga title con nombre real
        try:
            header = self.driver.find_element(By.CSS_SELECTOR, '#main header')
            spans = header.find_elements(By.CSS_SELECTOR, 'span[title]')
            for sp in spans:
                title = sp.get_attribute("title")
                if title and title.strip() and not _is_likely_status(title):
                    # Verificar que no sea un numero de telefono puro (el sidebar ya lo tiene)
                    # pero si es un nombre real, usarlo
                    return title.strip()
        except NoSuchElementException:
            pass

        try:
            header = self.driver.find_element(By.CSS_SELECTOR, '[data-testid="conversation-header"]')
            spans = header.find_elements(By.CSS_SELECTOR, 'span[title]')
            for sp in spans:
                title = sp.get_attribute("title")
                if title and title.strip() and not _is_likely_status(title):
                    return title.strip()
        except NoSuchElementException:
            pass

        return None

    def _is_chat_opened(self):
        try:
            msgs = self.driver.find_elements(By.CSS_SELECTOR, 'div[data-id]')
            if msgs and len(msgs) > 0:
                for m in msgs[:3]:
                    try:
                        text = m.text or ""
                        if len(text) > 0:
                            return True
                        if m.find_elements(By.CSS_SELECTOR, "img, video, audio"):
                            return True
                    except Exception:
                        continue
                return True
        except Exception:
            pass

        try:
            header = self.driver.find_element(By.CSS_SELECTOR, '#main header, [data-testid="conversation-header"]')
            if header and header.text:
                return True
        except NoSuchElementException:
            pass

        return False

    def _click_strategy(self, chat_element, strategy):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chat_element)
            time.sleep(0.5)

            if strategy == "actionchains_click":
                ActionChains(self.driver).move_to_element(chat_element).click().perform()
            elif strategy == "direct_click":
                chat_element.click()
            elif strategy == "title_click":
                for sel in ["span[title]", "div[title]"]:
                    try:
                        title = chat_element.find_element(By.CSS_SELECTOR, sel)
                        title.click()
                        break
                    except NoSuchElementException:
                        continue
                else:
                    return False
            elif strategy == "js_click":
                self.driver.execute_script("arguments[0].click();", chat_element)
            elif strategy == "js_click_parent":
                self.driver.execute_script("arguments[0].parentElement.click();", chat_element)
            elif strategy == "enter_key":
                chat_element.send_keys("\n")
            elif strategy == "double_click":
                ActionChains(self.driver).double_click(chat_element).perform()
            elif strategy == "js_click_first_child":
                self.driver.execute_script("""
                    var el = arguments[0];
                    var clickable = el.querySelector('div[tabindex], div[role="button"], div[data-testid*="cell-frame"]');
                    if (clickable) clickable.click();
                    else el.click();
                """, chat_element)
            else:
                return False

            time.sleep(2.5)
            return self._is_chat_opened()
        except Exception as e:
            logger.debug(f"  Estrategia {strategy} fallo: {e}")
            return False

    def open_chat_by_index(self, index):
        chats = self.get_chat_elements()
        if index >= len(chats):
            logger.warning(f"Indice {index} fuera de rango ({len(chats)} chats).")
            return False

        chat = chats[index]
        chat_info = self.get_chat_info(chat)
        chat_name = chat_info["name"]
        logger.info(f"  Abriendo chat '{chat_name}' (indice {index})...")

        strategies = [
            "actionchains_click",
            "direct_click",
            "title_click",
            "js_click",
            "js_click_first_child",
            "double_click",
            "enter_key",
        ]

        for attempt, strategy in enumerate(strategies):
            logger.info(f"  Intento {attempt+1}/{len(strategies)}: {strategy}")
            if self._click_strategy(chat, strategy):
                logger.info(f"  Chat '{chat_name}' abierto correctamente con {strategy}")
                time.sleep(1.5)
                return True
            time.sleep(0.5)

        logger.error(f"  No se pudo abrir el chat '{chat_name}' con ninguna estrategia.")
        return False

    def scroll_chat_up(self, pause=1.0):
        for sel in MSG_PANEL_SELECTORS:
            try:
                container = self.driver.find_element(By.CSS_SELECTOR, sel)
                self.driver.execute_script("arguments[0].scrollTop = 0;", container)
                time.sleep(pause)
                return True
            except NoSuchElementException:
                continue
        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(pause)
        return True

    def scroll_to_top_repeatedly(self, max_scrolls=200, pause=1.5):
        logger.info(f"Cargando historial ({max_scrolls} scrolls max)...")
        last_height = None
        for i in range(max_scrolls):
            try:
                container = None
                for sel in MSG_PANEL_SELECTORS:
                    try:
                        container = self.driver.find_element(By.CSS_SELECTOR, sel)
                        break
                    except NoSuchElementException:
                        continue
                if not container:
                    logger.warning("No se encontro contenedor de mensajes para scroll.")
                    break

                current_height = self.driver.execute_script(
                    "return arguments[0].scrollHeight;", container
                )
                if last_height == current_height and i > 0:
                    logger.info(f"Fin del historial alcanzado tras {i+1} scrolls.")
                    break
                last_height = current_height
                self.driver.execute_script("arguments[0].scrollTop = 0;", container)
                time.sleep(pause)
            except Exception as e:
                logger.debug(f"Scroll {i} error: {e}")
                break
        else:
            logger.info(f"Limite de scrolls alcanzado ({max_scrolls}).")

    def get_message_containers(self):
        for sel in MSG_CONTAINER_SELECTORS:
            try:
                msgs = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if msgs:
                    logger.debug(f"Mensajes encontrados con selector '{sel}': {len(msgs)}")
                    return msgs
            except Exception:
                continue
        logger.warning("No se encontraron mensajes con ningun selector.")
        return []

    def inject_js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def is_session_alive(self):
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'canvas[aria-label*="Scan this QR"]')
            return False
        except NoSuchElementException:
            return True
        except Exception:
            return False
