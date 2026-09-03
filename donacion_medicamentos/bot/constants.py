"""SessionSteps y constantes globales del bot."""


class SessionSteps:
    """Constantes para los pasos de la sesión"""
    NEW_USER = "NEW_USER"
    REQ_DOCUMENT = "REQUEST_DOCUMENT"
    REQ_NAME = "REQUEST_NAME"
    REQ_PHONE = "REQUEST_PHONE"
    REQ_ADDRESS = "REQUEST_ADDRESS"
    REQ_CONFIRM_DATA = "REQUEST_CONFIRM_DATA"
    KNOWN_USER = "KNOWN_USER"
    REQ_MEDICATIONS = "REQUEST_MEDICATIONS"
    REQ_MED_COUNT = "REQUEST_MED_COUNT"
    REQ_MED_DESCRIPTION = "REQUEST_MED_DESCRIPTION"
    REQ_MED_SEARCH = "REQUEST_MED_SEARCH"
    REQ_MED_SELECT = "REQUEST_MED_SELECT"
    REQ_PHOTO = "REQUEST_PHOTO"
    REQ_PHOTO_VALIDATION = "REQUEST_PHOTO_VALIDATION"
    REQ_MORE_PHOTOS = "REQUEST_MORE_PHOTOS"
    REQ_RELINK_CONFIRM = "REQUEST_RELINK_CONFIRM"
    REQ_RELINK_DOCUMENT = "REQUEST_RELINK_DOCUMENT"
    END = "END"


# Límites (antes atributos de clase de BotController)
SESSION_EXPIRY_HOURS = 12
MAX_MEDICATIONS = 4
MAX_OCR_ATTEMPTS = 2
MAX_DOC_ATTEMPTS = 5

# Antigüedad mínima (horas) para que el job de limpieza borre sobrantes en BASE_DIR/photos/
PHOTOS_CLEANUP_HOURS = 48

# Búsqueda de medicamentos (fuzzy search)
MAX_SEARCH_RESULTS = 5        # máximo de opciones mostradas como botones
FUZZY_SCORE_THRESHOLD = 70    # score mínimo de rapidfuzz (WRatio, 0-100)
MAX_MED_SEARCH_FAILURES = 2   # fallos consecutivos antes de redirigir a la fórmula
