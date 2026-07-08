"""Capa intermediaria de OCR.

NO reemplaza a OCRProcessor (ocr_processor.py): es el intermediario entre
conversation/photo.py (y relink.py) y OCRProcessor.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from telegram import Update

from .ocr_processor import OCRProcessor
from .validators import FormulaValidator

logger = logging.getLogger(__name__)


class OCRService:
    """Descarga de archivos, extracción/combinación de texto y validación de recetas."""

    async def download_file(self, update: Update) -> Optional[str]:
        """Antes: BotController.download_file_only"""
        try:
            photo_path_tmp = None
            if update.message.document:
                doc = update.message.document
                photo_file = await doc.get_file()
                ext = os.path.splitext(doc.file_name)[1] or ".jpg"
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{doc.file_unique_id}{ext}")
                await photo_file.download_to_drive(photo_path_tmp)
            elif update.message.photo:
                photo = update.message.photo[-1]
                photo_file = await photo.get_file()
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{photo.file_unique_id}.jpg")
                await photo_file.download_to_drive(photo_path_tmp)
            return photo_path_tmp
        except Exception as e:
            logger.exception(f"Error descargando archivo: {e}")
            return None

    def extract_text(self, file_path: str) -> Optional[str]:
        """Extrae el texto de un archivo delegando en OCRProcessor."""
        return OCRProcessor.extract_text_from_file(file_path)

    def combine_text(self, file_paths: List[str]) -> str:
        """Combina el texto extraído de varios archivos (antes inline en el flujo de fotos)."""
        combined_text = ""
        for fp in file_paths:
            extracted = OCRProcessor.extract_text_from_file(fp)
            if extracted:
                combined_text += extracted + "\n\n"
        return combined_text

    def process_recipe(self, file_paths: List[str]) -> str:
        """Procesa la receta: OCR sobre todos los archivos pendientes y devuelve el texto combinado."""
        return self.combine_text(file_paths)

    def validate_recipe(
        self, text: str, expected_document: str, expected_name: str
    ) -> Dict[str, Any]:
        """Valida el texto extraído contra documento y nombre esperados."""
        return FormulaValidator.validate_formula(text, expected_document, expected_name)
