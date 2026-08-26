"""Module d'analyse des logs pour DomoLink-Mistral.

Responsabilités :
- Lecture optimisée des dernières lignes du fichier homeassistant.log
- Récupération des erreurs structurées du composant system_log
- Nettoyage des données sensibles (mots de passe, tokens, IP) avant envoi à Mistral
"""
import re
import logging
from collections import deque

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── Expressions régulières pour détecter et masquer les données sensibles ──
SENSITIVE_PATTERNS = [
    # Mots de passe, clés API, secrets (capture le préfixe, remplace la valeur)
    (
        re.compile(
            r'(?i)((?:password|secret|api_key|api\.key|token|access_token|'
            r'client_secret|private_key|bearer)[\s:="\']+)[^\s,\]}"\']+',
        ),
        r"\1[REDACTED]",
    ),
    # URLs avec credentials intégrées (user:pass@host)
    (re.compile(r"://[^:]+:[^@]+@"), "://[CREDENTIALS]@"),
    # Adresses IPv4
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP_REMOVED]"),
    # Adresses IPv6 complètes
    (re.compile(r"\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b"), "[IPV6_REMOVED]"),
    # Tokens longs type JWT (xxx.yyy.zzz)
    (
        re.compile(r"[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{15,}\.[a-zA-Z0-9_-]{20,}"),
        "[TOKEN_REMOVED]",
    ),
    # Chaînes hexadécimales longues (clés API, hashes)
    (re.compile(r"\b[a-fA-F0-9]{32,}\b"), "[HEX_KEY_REMOVED]"),
]


def sanitize_logs(log_content: str) -> str:
    """Nettoie les logs en masquant les informations sensibles."""
    sanitized = log_content
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Récupère les dernières lignes du fichier homeassistant.log + system_log.

    Utilise un deque pour éviter de charger tout le fichier en mémoire.
    """
    parts = []

    # ── 1. Lecture du fichier homeassistant.log (tail optimisé) ──
    log_file = hass.config.path("homeassistant.log")
    try:

        def read_tail():
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                return "".join(deque(f, maxlen=lines))

        log_content = await hass.async_add_executor_job(read_tail)
        if log_content:
            parts.append("=== homeassistant.log (dernières lignes) ===\n" + log_content)
    except FileNotFoundError:
        _LOGGER.warning("Fichier homeassistant.log introuvable.")
    except Exception as e:
        _LOGGER.error("Erreur lors de la lecture de homeassistant.log: %s", e)

    # ── 2. Lecture des entrées structurées du system_log ──
    try:
        system_log = hass.data.get("system_log")
        if system_log and hasattr(system_log, "records"):
            records = system_log.records
            if records:
                system_entries = []
                for record in records[-50:]:  # Les 50 dernières entrées
                    # Gérer à la fois les dictionnaires et les objets dataclass/LogEntry
                    if isinstance(record, dict):
                        level = record.get("level", "UNKNOWN")
                        name = record.get("name", "")
                        message = record.get("message", "")
                        exc = record.get("exception", "")
                    else:
                        level = getattr(record, "level", "UNKNOWN")
                        name = getattr(record, "name", "")
                        message = getattr(record, "message", "")
                        exc = getattr(record, "exception", "")
                        
                    # Le message peut être une liste dans les versions récentes
                    if isinstance(message, list):
                        message = " ".join(str(m) for m in message)

                    entry = f"[{level}] {name}: {message}"
                    if exc:
                        entry += f"\n{exc}"
                        
                    system_entries.append(entry)
                
                if system_entries:
                    parts.append(
                        "=== system_log (entrées structurées) ===\n"
                        + "\n\n".join(system_entries)
                    )
    except Exception as e:
        _LOGGER.error("Erreur lors de la lecture du system_log: %s", e)

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    return sanitize_logs(combined)
