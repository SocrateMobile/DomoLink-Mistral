"""L'intégration Domolink-Mistral pour Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

from homeassistant.components.frontend import async_register_built_in_panel

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure Domolink-Mistral depuis une entrée de configuration."""
    hass.data.setdefault(DOMAIN, {})

    # Stockage de la configuration dans hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api_key": entry.data.get("api_key"),
        "options": entry.options,
        "sensor": None # Sera peuplé par sensor.py
    }

    _LOGGER.info(
        "Domolink-Mistral initialisé avec le modèle: %s", 
        entry.options.get("model")
    )
    
    # Enregistrement du fichier Javascript
    hass.http.register_static_path(
        "/domolink_mistral_frontend",
        hass.config.path("custom_components/domolink_mistral/frontend"),
        cache_headers=False,
    )

    # Enregistrement du panneau latéral
    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Mistral AI",
        sidebar_icon="mdi:brain",
        frontend_url_path="domolink_mistral",
        config={
            "_panel_custom": {
                "name": "domolink-mistral-panel",
                "module_url": "/domolink_mistral_frontend/domolink-mistral-panel.js",
            }
        },
        require_admin=True,
    )

    # Déclaration des services de l'intégration
    async def handle_analyze_now(call):
        """Gère l'appel du service pour déclencher une analyse manuelle."""
        from .analyzer import get_recent_logs
        from .mistral_api import analyze_with_mistral
        
        _LOGGER.info("Domolink-Mistral : Analyse déclenchée manuellement, récupération des logs...")
        logs = await get_recent_logs(hass)
        
        if logs:
            api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
            model = hass.data[DOMAIN][entry.entry_id]["options"].get("model", "mistral-large-latest")
            
            _LOGGER.info("Envoi des logs à Mistral...")
            result = await analyze_with_mistral(hass, api_key, model, logs)
            issues = result.get("issues", [])
            _LOGGER.info("Analyse terminée, %s problème(s) trouvé(s).", len(issues))
            
            # Mise à jour du capteur (Sensor)
            sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
            if sensor:
                sensor.update_issues(issues)
        else:
            _LOGGER.warning("Aucun log récent trouvé ou erreur de lecture.")

    async def handle_apply_fix(call):
        """Gère l'application d'un correctif automatique."""
        from .reparator import trigger_backup, apply_fix
        
        fix_payload = call.data.get("fix_script")
        if not fix_payload:
            _LOGGER.error("Aucun script de réparation fourni.")
            return

        # 1. On lance la sauvegarde (Comportement du bouton Automatique)
        backup_ok = await trigger_backup(hass)
        if backup_ok:
            # 2. On applique la modification
            await apply_fix(hass, fix_payload)
        else:
            _LOGGER.error("Annulation de la réparation automatique car la sauvegarde a échoué.")

    hass.services.async_register(DOMAIN, "analyze_now", handle_analyze_now)
    hass.services.async_register(DOMAIN, "apply_fix", handle_apply_fix)

    # Transférer la configuration aux plateformes (ex: sensor, s'il y en a)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharger l'intégration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
