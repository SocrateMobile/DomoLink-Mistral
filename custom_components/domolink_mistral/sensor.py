"""Plateforme Sensor pour DomoLink-Mistral.

Crée un capteur qui affiche le nombre de problèmes détectés par l'IA.
Pour éviter de dépasser la limite de 16 Ko de l'enregistreur Home Assistant (recorder),
les détails complets sont conservés dans hass.data et un résumé compact est exposé en attributs.
"""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VERSION


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Configure la plateforme sensor."""
    sensor = DomolinkMistralSensor(entry)

    # Stocke l'instance pour la mise à jour depuis les services
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entry_data["sensor"] = sensor

    async_add_entities([sensor])


class DomolinkMistralSensor(SensorEntity):
    """Capteur affichant le nombre de problèmes détectés par Mistral."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialisation."""
        self._attr_unique_id = f"{entry.entry_id}_issues"
        self._attr_translation_key = "issues"
        self._attr_name = "Problèmes détectés"
        self._attr_icon = "mdi:alert-circle-outline"
        self._state = 0
        self._issues: list = []
        self._ignored_issues: list = []
        self._last_analysis: str | None = None
        self._current_status: str = "En attente"
        self._last_error: str | None = None
        self._entry_id = entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Associe ce capteur au device DomoLink-Mistral."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DomoLink-Mistral IA",
            manufacturer="SocrateMobile",
            model="Mistral AI Log Analyzer",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> int:
        """Nombre de problèmes actifs (non ignorés)."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        """Attributs compacts sécurisés (< 16 Ko) pour l'enregistreur."""
        high_count = sum(1 for i in self._issues if i.get("severity") == "high")
        medium_count = sum(1 for i in self._issues if i.get("severity") == "medium")
        low_count = sum(1 for i in self._issues if i.get("severity") == "low")

        # Résumé allégé pour le dashboard sans exploser la taille en base
        compact_issues = [
            {
                "id": str(i.get("id", "")),
                "title": str(i.get("title", ""))[:80],
                "severity": i.get("severity", "medium"),
            }
            for i in self._issues[:15]
        ]

        return {
            "high_issues": high_count,
            "medium_issues": medium_count,
            "low_issues": low_count,
            "ignored_count": len(self._ignored_issues),
            "recent_issues": compact_issues,
            "last_analysis": self._last_analysis,
            "current_status": self._current_status,
            "last_error": self._last_error,
        }

    def set_status(self, status: str) -> None:
        """Met à jour le statut en direct."""
        self._current_status = status
        if getattr(self, "hass", None) and getattr(self, "entity_id", None):
            self.async_write_ha_state()

    def set_error(self, error_msg: str) -> None:
        """Enregistre et diffuse une erreur d'analyse."""
        self._current_status = f"❌ {error_msg}"
        self._last_error = error_msg
        if getattr(self, "hass", None) and getattr(self, "entity_id", None):
            self.async_write_ha_state()

    def update_issues(self, issues: list, ignored_ids: list | None = None) -> None:
        """Met à jour les problèmes détectés et conserve l'historique complet dans hass.data."""
        ignored_ids = ignored_ids or []

        self._issues = [i for i in issues if i.get("id") not in ignored_ids]
        self._ignored_issues = [i for i in issues if i.get("id") in ignored_ids]
        self._state = len(self._issues)
        self._last_analysis = dt_util.now().isoformat()
        self._last_error = None
        self._current_status = "Analyse terminée"

        # Stocker les listes complètes dans hass.data pour le frontend
        if getattr(self, "hass", None):
            entry_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry_id, {})
            entry_data["issues"] = self._issues
            entry_data["ignored_issues"] = self._ignored_issues

        if getattr(self, "hass", None) and getattr(self, "entity_id", None):
            self.async_write_ha_state()
