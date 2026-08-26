import logging
import json
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def trigger_backup(hass: HomeAssistant) -> bool:
    """Déclenche une sauvegarde de sécurité avant d'appliquer une modification."""
    try:
        _LOGGER.info("DomoLink-Mistral: Lancement d'une sauvegarde...")
        # Depuis HA 2023.x, le domaine de sauvegarde natif est "backup"
        if hass.services.has_service("backup", "create"):
            await hass.services.async_call("backup", "create", {}, blocking=True)
            return True
        # Ancienne méthode via Hass.io / Supervisor
        elif hass.services.has_service("hassio", "backup_full"):
            await hass.services.async_call("hassio", "backup_full", {}, blocking=True)
            return True
        else:
            _LOGGER.warning("DomoLink-Mistral: Aucun composant de sauvegarde disponible sur ce système.")
            return False
    except Exception as e:
        _LOGGER.error("Erreur critique lors de la tentative de sauvegarde: %s", e)
        return False

async def apply_fix(hass: HomeAssistant, fix_payload: str) -> bool:
    """Exécute de manière sécurisée les correctifs proposés par Mistral."""
    if not fix_payload or fix_payload.strip() == "":
        return False
        
    try:
        # Mistral est instruit de renvoyer un tableau JSON d'appels de services
        actions = json.loads(fix_payload)
        if not isinstance(actions, list):
            actions = [actions]
            
        success = True
        for action in actions:
            domain = action.get("domain")
            service = action.get("service")
            data = action.get("service_data", {})
            
            if domain and service and hass.services.has_service(domain, service):
                _LOGGER.info("DomoLink-Mistral: Application auto de la commande %s.%s", domain, service)
                await hass.services.async_call(domain, service, data, blocking=True)
            else:
                _LOGGER.warning("Action corrective ignorée: Service %s.%s inconnu.", domain, service)
                success = False
                
        return success
    except json.JSONDecodeError:
        _LOGGER.error("Impossible de parser l'action automatique (JSON invalide).")
        return False
    except Exception as e:
        _LOGGER.error("Erreur lors de l'application de la correction: %s", e)
        return False
