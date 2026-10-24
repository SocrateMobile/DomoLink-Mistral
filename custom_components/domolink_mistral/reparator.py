"""Module de réparation automatique pour DomoLink-Mistral.

Responsabilités :
- Déclenchement de sauvegardes de sécurité avant toute modification
- Exécution sécurisée des correctifs de services Home Assistant (avec whitelist)
"""
import asyncio
import json
import logging

from homeassistant.core import HomeAssistant

from .const import ALLOWED_FIX_DOMAINS, BLOCKED_SERVICES

_LOGGER = logging.getLogger(__name__)


async def trigger_backup(hass: HomeAssistant) -> bool:
    """Déclenche une sauvegarde de sécurité avant d'appliquer une modification.

    Tente une sauvegarde globale via Home Assistant ou Supervisor (avec timeout de sécurité).
    """
    try:
        # HA 2023.x+ : service natif backup.create
        if hass.services.has_service("backup", "create"):
            _LOGGER.info("DomoLink-Mistral: Déclenchement de la sauvegarde système préalable...")
            try:
                await asyncio.wait_for(
                    hass.services.async_call("backup", "create", {}, blocking=True),
                    timeout=45.0,
                )
                _LOGGER.info("DomoLink-Mistral: Sauvegarde système préalable complétée avec succès.")
                return True
            except (asyncio.TimeoutError, Exception) as be:
                _LOGGER.warning(
                    "DomoLink-Mistral: Le service backup.create a échoué ou a dépassé le délai (%s).",
                    be,
                )
                return True

        # Méthode via Hass.io / Supervisor
        if hass.services.has_service("hassio", "backup_full"):
            _LOGGER.info("DomoLink-Mistral: Déclenchement de la sauvegarde Supervisor préalable...")
            try:
                await asyncio.wait_for(
                    hass.services.async_call("hassio", "backup_full", {}, blocking=True),
                    timeout=45.0,
                )
                _LOGGER.info("DomoLink-Mistral: Sauvegarde Supervisor complétée avec succès.")
                return True
            except (asyncio.TimeoutError, Exception) as se:
                _LOGGER.warning(
                    "DomoLink-Mistral: Le service hassio.backup_full a échoué ou a dépassé le délai (%s).",
                    se,
                )
                return True

        _LOGGER.debug("DomoLink-Mistral: Aucun service de backup global actif.")
        return True

    except Exception as e:
        _LOGGER.warning(
            "DomoLink-Mistral: Impossible d'exécuter la sauvegarde système globale: %s.",
            e,
        )
        return True


def _is_service_allowed(domain: str, service: str) -> bool:
    """Vérifie qu'un service est autorisé (whitelist) et non bloqué (blacklist)."""
    full_service = f"{domain}.{service}"

    if full_service in BLOCKED_SERVICES:
        _LOGGER.warning("DomoLink-Mistral: Service bloqué par sécurité: %s", full_service)
        return False

    if domain not in ALLOWED_FIX_DOMAINS:
        _LOGGER.warning(
            "DomoLink-Mistral: Domaine '%s' non autorisé pour l'auto-fix. Domaines autorisés: %s",
            domain,
            ", ".join(sorted(ALLOWED_FIX_DOMAINS)),
        )
        return False

    return True


async def apply_fix(hass: HomeAssistant, fix_payload) -> dict:
    """Exécute de manière sécurisée les correctifs proposés par Mistral (appels de services Home Assistant uniquement).

    Retourne un dict avec le résultat : {"success": bool, "applied": int, "skipped": int, "details": list}
    """
    if isinstance(fix_payload, str):
        if not fix_payload.strip():
            return {"success": False, "applied": 0, "skipped": 0, "details": []}
        try:
            actions = json.loads(fix_payload)
        except json.JSONDecodeError:
            _LOGGER.error("Impossible de parser le script de correction (JSON invalide).")
            return {"success": False, "applied": 0, "skipped": 0, "details": ["JSON invalide"]}
    elif isinstance(fix_payload, list):
        actions = fix_payload
    elif isinstance(fix_payload, dict):
        actions = [fix_payload]
    else:
        return {"success": False, "applied": 0, "skipped": 0, "details": []}

    if not isinstance(actions, list):
        actions = [actions]

    applied = 0
    skipped = 0
    details = []

    for action in actions:
        if not isinstance(action, dict):
            continue

        action_type = action.get("action_type", "")
        if action_type in ("yaml_edit", "yaml_write") or ("file" in action and "service" not in action and "domain" not in action):
            skipped += 1
            details.append("Modification YAML ignorée (consultez le guide manuel)")
            continue

        domain = action.get("domain", "")
        service = action.get("service", "")
        data = action.get("service_data", {})

        if not domain or not service:
            skipped += 1
            continue

        # Vérification de sécurité
        if not _is_service_allowed(domain, service):
            skipped += 1
            details.append(f"Service non autorisé: {domain}.{service}")
            continue

        # Vérification que le service existe dans HA
        if not hass.services.has_service(domain, service):
            _LOGGER.warning("DomoLink-Mistral: Service %s.%s introuvable dans Home Assistant.", domain, service)
            skipped += 1
            details.append(f"Service introuvable: {domain}.{service}")
            continue

        try:
            _LOGGER.info("DomoLink-Mistral: Application du service %s.%s", domain, service)
            await hass.services.async_call(domain, service, data, blocking=True)
            applied += 1
            details.append(f"Service exécuté: {domain}.{service}")
        except Exception as e:
            _LOGGER.error("DomoLink-Mistral: Échec de %s.%s: %s", domain, service, e)
            skipped += 1
            details.append(f"Erreur {domain}.{service}: {e}")

    success = applied > 0 and skipped == 0
    _LOGGER.info("DomoLink-Mistral: Réparation terminée — %s appliqué(s), %s ignoré(s).", applied, skipped)
    return {"success": success, "applied": applied, "skipped": skipped, "details": details}
