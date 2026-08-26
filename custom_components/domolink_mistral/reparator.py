"""Module de réparation automatique pour DomoLink-Mistral.

Responsabilités :
- Déclenchement de sauvegardes de sécurité avant toute modification
- Exécution sécurisée des correctifs via les services Home Assistant
- Filtrage de sécurité (whitelist/blacklist de services)
"""
import logging
import json

from homeassistant.core import HomeAssistant

from .const import ALLOWED_FIX_DOMAINS, BLOCKED_SERVICES

_LOGGER = logging.getLogger(__name__)


async def trigger_backup(hass: HomeAssistant) -> bool:
    """Déclenche une sauvegarde de sécurité avant d'appliquer une modification."""
    try:
        _LOGGER.info("DomoLink-Mistral: Lancement d'une sauvegarde de sécurité...")

        # HA 2023.x+ : service natif backup.create
        if hass.services.has_service("backup", "create"):
            await hass.services.async_call("backup", "create", {}, blocking=True)
            _LOGGER.info("DomoLink-Mistral: Sauvegarde créée avec succès.")
            return True

        # Ancienne méthode via Hass.io / Supervisor
        if hass.services.has_service("hassio", "backup_full"):
            await hass.services.async_call("hassio", "backup_full", {}, blocking=True)
            _LOGGER.info("DomoLink-Mistral: Sauvegarde Supervisor créée avec succès.")
            return True

        _LOGGER.warning(
            "DomoLink-Mistral: Aucun composant de sauvegarde disponible. "
            "La correction sera appliquée sans sauvegarde préalable."
        )
        # On retourne True pour ne pas bloquer la correction
        # L'utilisateur a été averti par le warning
        return True

    except Exception as e:
        _LOGGER.error("Erreur critique lors de la tentative de sauvegarde: %s", e)
        return False


def _is_service_allowed(domain: str, service: str) -> bool:
    """Vérifie qu'un service est autorisé (whitelist) et non bloqué (blacklist)."""
    full_service = f"{domain}.{service}"

    if full_service in BLOCKED_SERVICES:
        _LOGGER.warning(
            "DomoLink-Mistral: Service bloqué par sécurité: %s", full_service
        )
        return False

    if domain not in ALLOWED_FIX_DOMAINS:
        _LOGGER.warning(
            "DomoLink-Mistral: Domaine '%s' non autorisé pour l'auto-fix. "
            "Domaines autorisés: %s",
            domain,
            ", ".join(sorted(ALLOWED_FIX_DOMAINS)),
        )
        return False

    return True


async def apply_fix(hass: HomeAssistant, fix_payload) -> dict:
    """Exécute de manière sécurisée les correctifs proposés par Mistral.

    Retourne un dict avec le résultat : {"success": bool, "applied": int, "skipped": int}
    """
    # Accepte un str JSON ou directement une liste
    if isinstance(fix_payload, str):
        if not fix_payload.strip():
            return {"success": False, "applied": 0, "skipped": 0}
        try:
            actions = json.loads(fix_payload)
        except json.JSONDecodeError:
            _LOGGER.error("Impossible de parser le script de correction (JSON invalide).")
            return {"success": False, "applied": 0, "skipped": 0}
    elif isinstance(fix_payload, list):
        actions = fix_payload
    else:
        return {"success": False, "applied": 0, "skipped": 0}

    if not isinstance(actions, list):
        actions = [actions]

    applied = 0
    skipped = 0

    for action in actions:
        domain = action.get("domain", "")
        service = action.get("service", "")
        data = action.get("service_data", {})

        # Vérification de sécurité
        if not _is_service_allowed(domain, service):
            skipped += 1
            continue

        # Vérification que le service existe dans HA
        if not hass.services.has_service(domain, service):
            _LOGGER.warning(
                "DomoLink-Mistral: Service %s.%s introuvable dans Home Assistant.",
                domain,
                service,
            )
            skipped += 1
            continue

        try:
            _LOGGER.info(
                "DomoLink-Mistral: Application du correctif %s.%s", domain, service
            )
            await hass.services.async_call(domain, service, data, blocking=True)
            applied += 1
        except Exception as e:
            _LOGGER.error(
                "DomoLink-Mistral: Échec de %s.%s: %s", domain, service, e
            )
            skipped += 1

    success = applied > 0 and skipped == 0
    _LOGGER.info(
        "DomoLink-Mistral: Réparation terminée — %s appliqué(s), %s ignoré(s).",
        applied,
        skipped,
    )
    return {"success": success, "applied": applied, "skipped": skipped}
