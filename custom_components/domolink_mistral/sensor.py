"""Sensor platform for Domolink-Mistral."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Configure la plateforme sensor (Capteur d'anomalies)."""
    sensor = DomolinkMistralSensor(entry)
    
    # On stocke l'instance du capteur pour pouvoir la mettre à jour depuis les services
    hass.data[DOMAIN][entry.entry_id]["sensor"] = sensor
    
    async_add_entities([sensor])

class DomolinkMistralSensor(SensorEntity):
    """Représente le capteur affichant le nombre de problèmes détectés."""

    def __init__(self, entry: ConfigEntry):
        """Initialisation."""
        self._attr_unique_id = f"{entry.entry_id}_issues"
        self._attr_name = "Problèmes Mistral"
        self._attr_icon = "mdi:brain"
        self._state = 0
        self._issues = []
        self._entry_id = entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Associe ce capteur à un Appareil (Device) physique/virtuel dans Home Assistant."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DomoLink-Mistral Hub",
            manufacturer="SocrateMobile",
            model="Mistral AI Log Analyzer",
            sw_version="1.0.0",
        )

    @property
    def native_value(self):
        """La valeur principale du capteur est le nombre d'erreurs."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Les attributs contiennent le JSON complet des erreurs pour le Frontend."""
        return {
            "issues": self._issues
        }

    def update_issues(self, issues: list):
        """Méthode appelée par l'analyseur pour mettre à jour les données."""
        self._issues = issues
        self._state = len(issues)
        self.async_write_ha_state()
