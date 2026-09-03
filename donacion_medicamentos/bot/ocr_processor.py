import logging
import os
import re
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Procesador de OCR con pipeline adaptativo (ligero vs rescate)."""

    EARLY_EXIT_MIN_CONF = 85.0
    EARLY_EXIT_MIN_CHARS = 30

    @staticmethod
    def _open_image(image_path: str) -> Image.Image:
        image = Image.open(image_path)
        try:
            image = ImageOps.exif_transpose(image)
        except Exception:
            pass
        return image

    @staticmethod
    def _resize_if_needed(image: Image.Image, min_width: int = 1500) -> Image.Image:
        w, h = image.size
        if w < min_width:
            image = image.resize((min_width, int(h * min_width / w)), Image.Resampling.LANCZOS)
        return image

    @staticmethod
    def _compute_metrics(gray: np.ndarray) -> dict:
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / edges.size
        return {
            "brightness": brightness,
            "contrast": contrast,
            "sharpness": sharpness,
            "edge_density": edge_density,
        }

    @staticmethod
    def _classify_image(metrics: dict) -> tuple[bool, list[str]]:
        reasons = []
        if metrics["brightness"] < 80 or metrics["brightness"] > 200:
            reasons.append("brightness")
        if metrics["contrast"] <= 40:
            reasons.append("contrast")
        if metrics["sharpness"] <= 100:
            reasons.append("sharpness")
        if metrics["edge_density"] < 0.02 or metrics["edge_density"] > 0.15:
            reasons.append("edge_density")

        is_difficult = len(reasons) >= 2
        return is_difficult, reasons

    @staticmethod
    def _light_preprocess(image_path: str) -> dict | None:
        try:
            img = cv2.imread(image_path)
            if img is None:
                logger.error(f"? No se pudo leer imagen: {image_path}")
                return None

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
            h, w = gray.shape
            if w < 1500:
                scale = 1500 / w
                gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            metrics = OCRProcessor._compute_metrics(gray)
            variants = {"gray": gray}

            # Contraste bajo: aplicar CLAHE suave
            if metrics["contrast"] <= 40:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                variants["light_clahe"] = clahe.apply(gray)

            return {"metrics": metrics, "variants": variants}

        except Exception as e:
            logger.error(f"? Error en pre-procesamiento ligero: {e}")
            return None

    @staticmethod
    def _rescue_preprocess(image_path: str) -> dict | None:
        """
        Pipeline de rescate: gris ? upscale ? gamma ? rotaci?n ? deskew
        ? denoise ? sharpen ? CLAHE ? binarizaci?n (+ invertida)
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                logger.error(f"? No se pudo leer imagen: {image_path}")
                return None

            logger.info(f"?? Imagen original: {img.shape[1]}x{img.shape[0]}")

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()

            h, w = gray.shape
            if w < 1500:
                scale = 1500 / w
                gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            mean_brightness = np.mean(gray)
            if mean_brightness < 80:
                gamma = 2.0
                lut = np.array([min(255, int(((i / 255.0) ** (1.0 / gamma)) * 255))
                                for i in range(256)], dtype=np.uint8)
                gray = cv2.LUT(gray, lut)
                logger.info(f"?? Gamma aplicado (brillo: {mean_brightness:.0f})")
            elif mean_brightness > 210:
                gray = cv2.equalizeHist(gray)
                logger.info(f"?? Ecualizaci?n aplicada (brillo: {mean_brightness:.0f})")

            try:
                pil_for_osd = Image.fromarray(gray)
                osd = pytesseract.image_to_osd(
                    pil_for_osd,
                    config='--psm 0 -c min_characters_to_try=5',
                    output_type=pytesseract.Output.DICT
                )
                rotation = osd.get('rotate', 0)
                rotation_map = {
                    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
                    180: cv2.ROTATE_180,
                    270: cv2.ROTATE_90_CLOCKWISE,
                }
                if rotation in rotation_map:
                    gray = cv2.rotate(gray, rotation_map[rotation])
                    logger.info(f"?? Imagen rotada {rotation}?")
            except Exception as e:
                logger.warning(f"?? OSD no disponible, sin rotaci?n: {e}")

            try:
                _, tmp_bin = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                coords = np.column_stack(np.where(tmp_bin > 0))
                if len(coords) >= 100:
                    angle = cv2.minAreaRect(coords)[-1]
                    if angle < -45:
                        angle = 90 + angle
                    if 0.5 < abs(angle) < 45:
                        h_d, w_d = gray.shape
                        center = (w_d // 2, h_d // 2)
                        M = cv2.getRotationMatrix2D(center, angle, 1.0)
                        gray = cv2.warpAffine(
                            gray, M, (w_d, h_d),
                            flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REPLICATE
                        )
                        logger.info(f"?? Deskew aplicado: {angle:.2f}?")
            except Exception as e:
                logger.warning(f"?? Deskew fall?: {e}")

            denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

            kernel_sharp = np.array([[0, -1, 0],
                                     [-1, 5, -1],
                                     [0, -1, 0]])
            sharpened = cv2.filter2D(denoised, -1, kernel_sharp)

            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(sharpened)

            _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            white_ratio = np.sum(otsu == 255) / otsu.size
            if 0.15 < white_ratio < 0.85:
                binary = otsu
                logger.info(f"? Binarizaci?n Otsu (ratio blanco: {white_ratio:.1%})")
            else:
                binary = cv2.adaptiveThreshold(
                    enhanced, 255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY, 11, 2
                )
                logger.info(f"? Binarizaci?n adaptativa (ratio Otsu: {white_ratio:.1%})")

            binary_inv = cv2.bitwise_not(binary)

            return {
                "metrics": OCRProcessor._compute_metrics(gray),
                "variants": {
                    "gray": gray,
                    "enhanced": enhanced,
                    "binary": binary,
                    "binary_inv": binary_inv,
                },
            }

        except Exception as e:
            logger.error(f"? Error en pre-procesamiento de rescate: {e}")
            return None

    @staticmethod
    def _ocr_with_score(pil_image: Image.Image, config: str, lang: str) -> tuple[str, float, int, float]:
        text = pytesseract.image_to_string(pil_image, lang=lang, config=config)
        data = pytesseract.image_to_data(pil_image, lang=lang, config=config, output_type=pytesseract.Output.DICT)
        confs = []
        for c in data.get("conf", []):
            if isinstance(c, (int, float)) and c >= 0:
                confs.append(float(c))
            elif isinstance(c, str) and c != "-1":
                try:
                    confs.append(float(c))
                except Exception:
                    pass
        conf_avg = float(sum(confs) / len(confs)) if confs else 0.0
        char_count = len(re.sub(r"\s", "", text))
        score = (conf_avg * 2.0) + (char_count * 0.1)
        return text, score, char_count, conf_avg

    @staticmethod
    def extract_text_from_image(image_path: str) -> str:
        """Extrae texto de una imagen con pipeline adaptativo."""
        try:
            light = OCRProcessor._light_preprocess(image_path)
            use_rescue = True
            reasons = []

            if light and "metrics" in light:
                use_rescue, reasons = OCRProcessor._classify_image(light["metrics"])
                logger.info(
                    f"?? Diagn?stico: {'rescate' if use_rescue else 'ligero'} | razones: {', '.join(reasons) if reasons else 'ok'}"
                )

            processed = OCRProcessor._rescue_preprocess(image_path) if use_rescue else light

            if processed is None:
                logger.warning("?? Pre-procesamiento fall?, usando fallback PIL")
                image = OCRProcessor._open_image(image_path)
                image = image.convert('L')
                image = OCRProcessor._resize_if_needed(image)
                variants = [("pil_fallback", image)]
            else:
                variants = []
                for name, mat in processed["variants"].items():
                    try:
                        variants.append((name, Image.fromarray(mat)))
                    except Exception:
                        pass
                original_gray = OCRProcessor._open_image(image_path).convert('L')
                original_gray = OCRProcessor._resize_if_needed(original_gray)
                variants.append(("original_gray", original_gray))

            configs = [
                ('--oem 3 --psm 6', 'bloque_uniforme'),
                ('--oem 3 --psm 4', 'columna'),
                ('--oem 3 --psm 3', 'automatico'),
                ('--oem 3 --psm 11', 'texto_disperso'),
                ('--oem 3 --psm 7', 'una_linea'),
            ]

            best_text = ""
            best_score = -1.0
            best_char_count = 0

            early_exit = False
            for variant_name, pil_image in variants:
                if early_exit:
                    break
                for config, config_name in configs:
                    try:
                        text, score, char_count, conf_avg = OCRProcessor._ocr_with_score(
                            pil_image,
                            f"{config} --dpi 300",
                            lang='spa+eng'
                        )
                        logger.info(
                            f"?? {variant_name} | {config_name}: score={score:.1f} conf={conf_avg:.1f} chars={char_count}"
                        )
                        if score > best_score:
                            best_text = text
                            best_score = score
                            best_char_count = char_count

                        if (
                            conf_avg >= OCRProcessor.EARLY_EXIT_MIN_CONF
                            and char_count >= OCRProcessor.EARLY_EXIT_MIN_CHARS
                        ):
                            logger.info(
                                f"?? Early exit: {variant_name}/{config_name} ya es suficientemente bueno "
                                f"(conf={conf_avg:.1f}, chars={char_count})"
                            )
                            early_exit = True
                            break
                    except Exception as e:
                        logger.warning(f"?? Fall? {variant_name} / {config_name}: {e}")

            if best_char_count < 20:
                logger.warning("?? Texto insuficiente, probando solo ingles")
                try:
                    text_eng, score, char_count, conf_avg = OCRProcessor._ocr_with_score(
                        variants[0][1],
                        "--oem 3 --psm 6 --dpi 300",
                        lang='eng'
                    )
                    if score > best_score:
                        best_text = text_eng
                        best_score = score
                except Exception as e:
                    logger.warning(f"?? Ingl?s tambi?n fall?: {e}")

            if best_text:
                preview = best_text[:150].replace(chr(10), ' ')
                logger.info(f"?? Mejor resultado: score={best_score:.1f} ? preview: {preview}")
            else:
                logger.warning("?? No se extrajo texto de la imagen")

            return best_text.strip()

        except Exception as e:
            logger.error(f"? Error en OCR de imagen: {e}")
            logger.exception("Traceback completo:")
            return None

    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> str:
        """Extrae texto de un PDF usando PyPDF2 y OCR si es necesario"""
        try:
            text = ""
            try:
                reader = PdfReader(pdf_path)
                logger.info(f"?? PDF tiene {len(reader.pages)} pagina(s)")
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                        logger.info(f"?? Pagina {i+1}: {len(page_text)} caracteres extraidos directamente")
            except Exception as e:
                logger.warning(f"?? No se pudo extraer texto directamente: {e}")

            if len(text.strip()) < 50:
                logger.info("?? Texto insuficiente, usando OCR...")
                images = convert_from_path(pdf_path, dpi=300)
                logger.info(f"?? PDF convertido a {len(images)} imagen(es)")
                for i, image in enumerate(images):
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        temp_path = tmp.name
                    try:
                        image.save(temp_path, 'PNG')
                        page_text = OCRProcessor.extract_text_from_image(temp_path)
                        if page_text:
                            text += page_text + "\n"
                            logger.info(f"?? P?gina {i+1}: {len(page_text)} caracteres (OCR)")
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

            logger.info(f"?? Total extraido del PDF: {len(text)} caracteres")
            return text.strip()

        except Exception as e:
            logger.error(f"? Error en extraccion de PDF: {e}")
            logger.exception("Traceback completo:")
            return None

    @staticmethod
    def extract_text_from_file(file_path: str) -> str:
        """Extrae texto de un archivo (imagen o PDF)"""
        file_ext = Path(file_path).suffix.lower()
        logger.info(f"?? Procesando archivo: {file_path} (tipo: {file_ext})")
        if file_ext == '.pdf':
            return OCRProcessor.extract_text_from_pdf(file_path)
        if file_ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.webp']:
            return OCRProcessor.extract_text_from_image(file_path)
        logger.warning(f"?? Formato no soportado: {file_ext}")
        return None

    @staticmethod
    def test_ocr_setup():
        """Verifica configuraci?n de OCR"""
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"? Tesseract version: {version}")
            logger.info(f"? OpenCV version: {cv2.__version__}")
            try:
                import subprocess
                result = subprocess.run(['tesseract', '--list-langs'],
                                        capture_output=True, text=True, timeout=5)
                langs = result.stdout
                if 'spa' not in langs:
                    logger.warning("?? Idioma español (spa) no instalado!")
                    logger.warning("   Instalar: sudo apt-get install tesseract-ocr-spa")
                else:
                    logger.info("? Idioma español disponible")
            except Exception as e:
                logger.warning(f"?? No se pudo verificar idiomas: {e}")
            return True
        except Exception as e:
            logger.error(f"? Error en configuracion OCR: {e}")
            return False
