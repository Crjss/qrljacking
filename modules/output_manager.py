#!/usr/bin/env python3
"""
Gestión de salida: organiza evidencias, comprime y genera hashes de integridad.
"""
import json
import hashlib
import zipfile
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class OutputManager:
    """Organiza y sella las evidencias extraídas."""

    def __init__(self, output_dir="./evidencias"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compute_hashes(self, directory=None):
        """Genera SHA-256 de todos los archivos en el directorio."""
        directory = directory or self.output_dir
        hashes = {}
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file() and fpath.name != "hashes.json":
                h = hashlib.sha256(fpath.read_bytes()).hexdigest()
                rel = fpath.relative_to(directory)
                hashes[str(rel)] = h
        return hashes

    def save_hashes(self):
        hashes = self.compute_hashes()
        hfile = self.output_dir / "hashes.json"
        with open(hfile, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2)
        logger.info(f"🔐 Hashes SHA-256 guardados: {hfile} ({len(hashes)} archivos)")
        return hfile

    def create_archive(self, archive_name=None):
        """Comprime todas las evidencias en un ZIP."""
        if archive_name is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"whatsapp_evidencias_{ts}.zip"
        archive_path = self.output_dir.parent / archive_name

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in self.output_dir.rglob("*"):
                if fpath.is_file():
                    zf.write(fpath, fpath.relative_to(self.output_dir))
        logger.info(f"📦 Archivo comprimido creado: {archive_path}")
        return archive_path

    def generate_manifest(self):
        """Genera un manifiesto JSON con metadatos de la extracción."""
        manifest = {
            "tool": "WhatsApp Forensic Extractor",
            "version": "v1.0",
            "purpose": "Análisis de seguridad en entornos controlados",
            "extracted_at": datetime.now().isoformat(),
            "output_dir": str(self.output_dir.resolve()),
            "files": {}
        }
        for fpath in sorted(self.output_dir.rglob("*")):
            if fpath.is_file():
                rel = str(fpath.relative_to(self.output_dir))
                manifest["files"][rel] = {
                    "size": fpath.stat().st_size,
                    "modified": datetime.fromtimestamp(fpath.stat().st_mtime).isoformat()
                }
        mfile = self.output_dir / "MANIFEST.json"
        with open(mfile, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"📋 Manifiesto generado: {mfile}")
        return mfile
