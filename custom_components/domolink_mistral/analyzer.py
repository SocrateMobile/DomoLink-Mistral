import re
import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Expressions régulières pour détecter les données sensibles
SENSITIVE_PATTERNS = [
    # Adresses IPv4
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "[IP_ADDRESS_REMOVED]"),
    # Adresses IPv6
    (re.compile(r'\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b'), "[IPV6_ADDRESS_REMOVED]"),
    # Tokens longs (ex: JWT)
    (re.compile(r'[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{15,}\.[a-zA-Z0-9_-]{20,}'), "[TOKEN_REMOVED]"),
    # Mots de passe, clés ou secrets (basique)
    (re.compile(r'(?i)(?:password|secret|api_key|token)[\s:=]+([^\s,]+)'), r'\g<0>_REDACTED'),
]

def sanitize_logs(log_content: str) -> str:
    """Nettoie les logs en masquant les informations sensibles."""
    sanitized = log_content
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized

async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Récupère les dernières lignes du fichier homeassistant.log."""
    log_file = hass.config.path("homeassistant.log")
    try:
        def read_tail():
            # Lecture des X dernières lignes
            # Note: Pour un très gros fichier, on utiliserait un seek par la fin,
            # mais ceci est un bon point de départ pour récupérer le contexte.
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        
        # Exécution de la lecture de fichier dans un thread séparé pour ne pas bloquer Home Assistant
        log_content = await hass.async_add_executor_job(read_tail)
        
        # Nettoyage des données sensibles
        return sanitize_logs(log_content)
    except Exception as e:
        _LOGGER.error("Erreur lors de la lecture des logs: %s", e)
        return ""
