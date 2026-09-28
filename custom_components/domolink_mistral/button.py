"""Plateforme Button pour DomoLink-Mistral.

Expose un bouton d'analyse manuelle dans l'interface Home Assistant.
(Le bouton All-Auto a été retiré pour des raisons de sécurité : les réparations
YAML et système restent réservées aux administrateurs depuis le panneau dédié).
"""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Configure la plateforme button."""
    async_add_entities([AnalyzeButton(entry)])


class DomolinkMistralBaseButton(ButtonEntity):
    """Bouton de base pour DomoLink-Mistral."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialisation."""
        self._entry_id = entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DomoLink-Mistral IA",
            manufacturer="SocrateMobile",
            model="Mistral AI Integration",
        )


class AnalyzeButton(DomolinkMistralBaseButton):
    """Bouton pour lancer une analyse manuelle."""

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_analyze_btn"
        self._attr_name = "Analyser les logs"
        self._attr_icon = "mdi:magnify-scan"

    async def async_press(self) -> None:
        """Action au clic avec transmission du contexte utilisateur."""
        await self.hass.services.async_call(
            DOMAIN, "analyze_now", {}, context=self._context
        )
