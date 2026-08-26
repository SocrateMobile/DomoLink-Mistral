"""Plateforme Button pour DomoLink-Mistral.

Expose des boutons dans l'interface Home Assistant pour déclencher
facilement les actions de l'intégration sans passer par les services.
"""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Configure la plateforme button."""
    async_add_entities(
        [
            AnalyzeButton(hass, entry),
            FixAllButton(hass, entry),
        ]
    )


class DomolinkMistralBaseButton(ButtonEntity):
    """Bouton de base pour DomoLink-Mistral."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialisation."""
        self.hass = hass
        self._entry_id = entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Associe ce bouton au device DomoLink-Mistral."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )


class AnalyzeButton(DomolinkMistralBaseButton):
    """Bouton pour lancer une analyse manuelle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_analyze_btn"
        self._attr_name = "Analyser les logs"
        self._attr_icon = "mdi:magnify-scan"

    async def async_press(self) -> None:
        """Action au clic."""
        await self.hass.services.async_call(DOMAIN, "analyze_now", {})


class FixAllButton(DomolinkMistralBaseButton):
    """Bouton pour appliquer toutes les corrections (All Auto)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_fix_all_btn"
        self._attr_name = "Appliquer les correctifs (All Auto)"
        self._attr_icon = "mdi:auto-fix"

    async def async_press(self) -> None:
        """Action au clic."""
        await self.hass.services.async_call(DOMAIN, "apply_all_fixes", {})
