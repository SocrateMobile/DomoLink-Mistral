"""Plateforme Sensor pour DomoLink-Mistral.

Crée un capteur qui affiche le nombre de problèmes détectés par l'IA.
Les détails des problèmes sont stockés dans les attributs du capteur.
"""
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Configure la plateforme sensor."""
    sensor = DomolinkMistralSensor(entry)

    # Stocke l'instance pour la mise à jour depuis les services
    hass.data[DOMAIN][entry.entry_id]["sensor"] = sensor

    async_add_entities([sensor])


class DomolinkMistralSensor(SensorEntity):
    """Capteur affichant le nombre de problèmes détectés par Mistral."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry):
        """Initialisation."""
        self._attr_unique_id = f"{entry.entry_id}_issues"
        self._attr_translation_key = "issues"
        self._attr_name = "Problèmes détectés"
        self._attr_icon = "mdi:alert-circle-outline"
        self._state = 0
        self._issues: list = []
        self._ignored_issues: list = []
        self._last_analysis: str | None = None
        self._entry_id = entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Associe ce capteur au device DomoLink-Mistral."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DomoLink-Mistral",
            manufacturer="SocrateMobile",
            model="Mistral AI Log Analyzer",
            sw_version="2.0.0",
        )

    @property
    def native_value(self):
        """Nombre de problèmes actifs (non ignorés)."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Attributs contenant les données complètes pour le frontend."""
        return {
            "issues": self._issues,
            "ignored_issues": self._ignored_issues,
            "last_analysis": self._last_analysis,
        }

    def update_issues(self, issues: list, ignored_ids: list | None = None):
        """Met à jour les problèmes détectés.

        Sépare automatiquement les issues actives et ignorées.
        """
        ignored_ids = ignored_ids or []

        self._issues = [i for i in issues if i.get("id") not in ignored_ids]
        self._ignored_issues = [i for i in issues if i.get("id") in ignored_ids]
        self._state = len(self._issues)
        self._last_analysis = datetime.now().isoformat()
        self.async_write_ha_state()
