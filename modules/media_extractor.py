#!/usr/bin/env python3
"""
Extraccion de media v1.0.
Cambios:
  - Scroll paso a paso para cargar imagenes visibles
  - JS_CAPTURE_VISIBLE_IMAGES usa canvas.toDataURL() para cada <img> en mensajes visibles
  - Nombres: sidebar como base. Solo corrige con header cuando sidebar es numero de telefono.
"""
import os
import time
import json
import base64
import logging
import re
from pathlib import Path
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

logger = logging.getLogger(__name__)

JS_SCROLL_STEP = r"""var c=document.querySelector('div[data-testid="conversation-panel-messages"]')||document.querySelector('#main .copyable-area')||document.querySelector('#main');if(c){c.scrollTop=Math.max(0,c.scrollTop-800);return c.scrollTop;}return -1;"""

JS_CAPTURE_VISIBLE_IMAGES = r"""(function(){var panel=document.querySelector('div[data-testid="conversation-panel-messages"]')||document.querySelector('#main .copyable-area')||document.querySelector('#main');if(!panel)return JSON.stringify([]);var results=[];var msgs=panel.querySelectorAll('div[data-id]');for(var i=0;i<msgs.length;i++){var msg=msgs[i];var imgs=msg.querySelectorAll('img');for(var j=0;j<imgs.length;j++){var img=imgs[j];var src=img.src||'';if(src.length<5)continue;var dataId=msg.getAttribute('data-id')||('img_'+i+'_'+j);var w=img.naturalWidth||img.width||0;var h=img.naturalHeight||img.height||0;if(w<20||h<20)continue;try{var canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);var b64=canvas.toDataURL('image/png').split(',')[1];results.push({data_id:dataId,width:w,height:h,base64:b64});}catch(e){results.push({data_id:dataId,width:w,height:h,error:e.message});}}}return JSON.stringify(results);})();"""


def _looks_like_phone_number(name):
    if not name:
        return False
    cleaned = name.strip()
    if re.search(r'[a-zA-Z\u00c0-\u024f\u1e00-\u1eff]', cleaned):
        return False
    digits_only = re.sub(r'\D', '', cleaned)
    if len(digits_only) >= 7:
        return True
    return False


class MediaExtractor:
    def __init__(self, session_manager, output_dir="./evidencias/media"):
        self.sm = session_manager
        self.base_output_dir = Path(output_dir)
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"images": 0, "videos": 0, "audios": 0, "documents": 0, "errors": 0}

    def _safe_dirname(self, name):
        safe = re.sub(r'[^\w\s._-]', '_', name)
        safe = safe.strip()[:60]
        return safe or "chat"

    def _chat_media_dir(self, chat_name):
        safe = self._safe_dirname(chat_name)
        chat_dir = self.base_output_dir / safe
        for sub in ("images", "videos", "audios", "documents"):
            (chat_dir / sub).mkdir(parents=True, exist_ok=True)
        return chat_dir

    def _save_base64_image(self, b64_data, dest_path):
        try:
            data = base64.b64decode(b64_data)
            Path(dest_path).write_bytes(data)
            return True
        except Exception as e:
            logger.debug(f"Error guardando imagen: {e}")
            return False

    def _scroll_and_capture_images(self, chat_dir, max_steps=60, pause=3.0):
        captured_ids = set()
        total_captured = 0
        last_top = -1
        same_count = 0

        for step in range(max_steps):
            try:
                raw = self.sm.inject_js(JS_CAPTURE_VISIBLE_IMAGES)
                images = []
                if isinstance(raw, str):
                    try:
                        images = json.loads(raw)
                    except Exception:
                        pass
                elif isinstance(raw, list):
                    images = raw

                new_in_step = 0
                for img_info in images:
                    data_id = img_info.get("data_id", "")
                    if not data_id or data_id in captured_ids:
                        continue
                    if img_info.get("error"):
                        logger.debug(f"  Canvas error en {data_id}: {img_info['error']}")
                        continue
                    b64_data = img_info.get("base64")
                    if not b64_data:
                        continue

                    dest = str(chat_dir / "images" / f"img_{total_captured:03d}_{data_id[:16]}.png")
                    if self._save_base64_image(b64_data, dest):
                        captured_ids.add(data_id)
                        total_captured += 1
                        new_in_step += 1

                if new_in_step > 0:
                    logger.info(f"  [Step {step+1}] +{new_in_step} imagenes capturadas (total: {total_captured})")

                current_top = self.sm.inject_js(JS_SCROLL_STEP)
                if isinstance(current_top, str):
                    try:
                        current_top = int(current_top)
                    except ValueError:
                        current_top = -1

                if current_top == last_top and step > 0:
                    same_count += 1
                    if same_count >= 3:
                        logger.info(f"  Fin del historial en media tras {step+1} pasos")
                        break
                else:
                    same_count = 0
                    last_top = current_top

                time.sleep(pause)
            except Exception as e:
                logger.debug(f"  Media scroll step {step} error: {e}")
                break
        else:
            logger.info(f"  Limite de pasos alcanzado en media ({max_steps}).")

        return total_captured

    def extract_all_media(self, chat_indices=None, max_per_type=50):
        logger.info("Iniciando extraccion de media (v1.0)...")
        chats = self.sm.get_chat_elements()
        total = len(chats)
        indices = chat_indices if chat_indices is not None else range(total)

        for idx in indices:
            if idx >= total:
                break
            try:
                chat_el = chats[idx]
                chat_info = self.sm.get_chat_info(chat_el)
                chat_name = chat_info["name"]
                logger.info(f"[{idx+1}/{total}] Media de: {chat_name}")

                if not self.sm.open_chat_by_index(idx):
                    continue
                time.sleep(3.0)

                if _looks_like_phone_number(chat_name):
                    header_name = self.sm.get_open_chat_header_name()
                    if header_name and header_name != chat_name:
                        logger.info(f"  Nombre corregido para media: '{header_name}' (sidebar era numero: '{chat_name}')")
                        chat_name = header_name
                    else:
                        logger.info(f"  Sidebar es numero pero header no valido. Manteniendo: '{chat_name}'")

                chat_dir = self._chat_media_dir(chat_name)

                img_count = self._scroll_and_capture_images(chat_dir, max_steps=60, pause=3.0)
                self.stats["images"] += img_count

                logger.info(f"  Chat '{chat_name}' finalizado: {img_count} imagenes.")

                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error chat {idx}: {e}")
                self.stats["errors"] += 1

        stats_file = self.base_output_dir / "media_stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2)
        logger.info(f"Resumen media v1.0: {self.stats}")
        return self.stats
