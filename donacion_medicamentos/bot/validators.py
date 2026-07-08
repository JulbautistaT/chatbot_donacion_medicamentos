import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class FormulaValidator:
    """Validador de fórmulas médicas con validación flexible de nombres"""

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n', 'ü': 'u'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def extract_document_number(text: str) -> List[str]:
        text_collapsed = re.sub(r'(?<=\d) (?=\d)', '', text)
        texts_to_search = [text, text_collapsed]
        patterns = [
            r'\b(\d{6,12})\b',
            r'(?:c\.?c\.?|cedula|documento|identificacion|identif)[^0-9]{0,10}(\d[\d ]{4,11}\d)',
        ]
        found_documents = []
        for search_text in texts_to_search:
            for pattern in patterns:
                matches = re.finditer(pattern, search_text, re.IGNORECASE)
                for match in matches:
                    doc = match.group(1) if match.lastindex else match.group(0)
                    doc = re.sub(r'\D', '', doc)
                    if 6 <= len(doc) <= 12:
                        found_documents.append(doc)
        unique_docs = list(set(found_documents))
        logger.info(f"🆔 Documentos encontrados: {unique_docs}")
        return unique_docs

    @staticmethod
    def validate_name_flexible(text_normalized: str, expected_name_normalized: str) -> Dict[str, Any]:
        result = {'matched': False, 'matched_words': [], 'strategy': None, 'confidence': 0.0}
        expected_words = [w for w in expected_name_normalized.split() if len(w) >= 3]
        if not expected_words:
            logger.warning("⚠️ No hay palabras válidas en el nombre esperado")
            return result

        logger.info(f"🔍 Buscando palabras: {expected_words}")

        matched_full = []
        for word in expected_words:
            if re.search(r'\b' + re.escape(word) + r'\b', text_normalized):
                matched_full.append(word)
        if len(matched_full) >= len(expected_words) * 0.5:
            result.update({'matched': True, 'matched_words': matched_full,
                           'strategy': 'palabras_completas',
                           'confidence': len(matched_full) / len(expected_words)})
            logger.info(f"✅ Nombre validado (palabras completas): {matched_full}")
            return result

        matched_partial = []
        for word in expected_words:
            if len(word) >= 4 and (word[:4] in text_normalized or word[-4:] in text_normalized):
                matched_partial.append(word)
        if len(matched_partial) >= len(expected_words) * 0.5:
            result.update({'matched': True, 'matched_words': matched_partial,
                           'strategy': 'palabras_parciales',
                           'confidence': len(matched_partial) / len(expected_words)})
            logger.info(f"✅ Nombre validado (parcial): {matched_partial}")
            return result

        all_letters_name = ''.join(expected_words)
        all_letters_text = text_normalized.replace(' ', '')
        matched_chars, text_idx = 0, 0
        for char in all_letters_name:
            found_idx = all_letters_text.find(char, text_idx)
            if found_idx != -1:
                matched_chars += 1
                text_idx = found_idx + 1
        char_match_ratio = matched_chars / len(all_letters_name) if all_letters_name else 0
        if char_match_ratio >= 0.7:
            result.update({'matched': True, 'matched_words': expected_words,
                           'strategy': 'secuencia_letras', 'confidence': char_match_ratio})
            logger.info(f"✅ Nombre validado (secuencia letras): {char_match_ratio:.1%}")
            return result

        apellidos = [w for w in expected_words if len(w) >= 4][-2:]
        if apellidos:
            matched_apellidos = [w for w in apellidos if w in text_normalized]
            if matched_apellidos:
                result.update({'matched': True, 'matched_words': matched_apellidos,
                               'strategy': 'apellidos',
                               'confidence': len(matched_apellidos) / len(apellidos)})
                logger.info(f"✅ Nombre validado (apellidos): {matched_apellidos}")
                return result

        logger.warning(f"❌ Nombre NO validado.")
        return result

    @staticmethod
    def validate_formula(text: str, expected_document: str, expected_name: str) -> Dict[str, Any]:
        result = {'is_valid': False, 'document_match': False, 'name_match': False,
                  'errors': [], 'debug_info': {}}

        if not text or len(text) < 50:
            result['errors'].append("Texto insuficiente o no se pudo leer el documento")
            logger.warning(f"⚠️ Validación fallida: texto muy corto ({len(text)} caracteres)")
            return result

        text_normalized = FormulaValidator.normalize_text(text)
        expected_name_normalized = FormulaValidator.normalize_text(expected_name)
        result['debug_info']['text_length'] = len(text)
        result['debug_info']['text_preview'] = text[:300]

        found_documents = FormulaValidator.extract_document_number(text)
        document_matched = expected_document in found_documents
        if not document_matched:
            for found in found_documents:
                if expected_document in found or found in expected_document:
                    document_matched = True
                    break

        if document_matched:
            result['document_match'] = True
        else:
            result['errors'].append("documento")
        result['debug_info']['found_documents'] = found_documents

        name_validation = FormulaValidator.validate_name_flexible(text_normalized, expected_name_normalized)
        result['name_match'] = name_validation['matched']
        result['debug_info']['name_validation'] = name_validation
        if not result['name_match']:
            result['errors'].append("nombre")

        result['is_valid'] = result['document_match'] and result['name_match']
        logger.info(f"📊 Resultado: doc={result['document_match']}, "
                    f"nombre={result['name_match']}, válido={result['is_valid']}")
        return result
