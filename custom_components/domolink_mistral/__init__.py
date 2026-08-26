"""L'intégration Domolink-Mistral pour Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure Domolink-Mistral depuis une entrée de configuration."""
    hass.data.setdefault(DOMAIN, {})

    # Stockage de la configuration dans hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api_key": entry.data.get("api_key"),
        "options": entry.options,
    }

    _LOGGER.info(
        "Domolink-Mistral initialisé avec le modèle: %s", 
        entry.options.get("model")
    )

    # Déclaration des services de l'intégration
    async def handle_analyze_now(call):
        """Gère l'appel du service pour déclencher une analyse manuelle."""
        _LOGGER.info("Domolink-Mistral : Analyse déclenchée manuellement.")
        # L'intégration des appels à l'analyzer se fera ici

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
