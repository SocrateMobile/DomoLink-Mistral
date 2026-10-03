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
        """Attributs d'état pour le panneau et le dashboard Home Assistant.

        Garantit que la taille JSON des attributs reste strictement sous le seuil
        de 16384 octets imposé par l'enregistreur Home Assistant (recorder).
        """
        import json

        valid_issues = [i for i in (self._issues or []) if isinstance(i, dict)]
        valid_ignored = [i for i in (self._ignored_issues or []) if isinstance(i, dict)]

        high_count = sum(1 for i in valid_issues if i.get("severity") == "high")
        medium_count = sum(1 for i in valid_issues if i.get("severity") == "medium")
        low_count = sum(1 for i in valid_issues if i.get("severity") == "low")

        base_attrs = {
            "high_issues": high_count,
            "medium_issues": medium_count,
            "low_issues": low_count,
            "total_issues": len(valid_issues),
            "ignored_count": len(valid_ignored),
            "last_analysis": self._last_analysis,
            "current_status": self._current_status,
            "last_error": self._last_error,
        }

        # 1. Tester si les données complètes tiennent sous 13000 octets (< 16384 octets recorder)
        full_candidate = {
            **base_attrs,
            "issues": valid_issues,
            "ignored_issues": valid_ignored,
        }
        try:
            if len(json.dumps(full_candidate, ensure_ascii=False)) < 13000:
                return full_candidate
        except Exception:
            pass

        # 2. Si trop volumineux, créer une version résumée (sans scripts ni descriptions volumineuses)
        # pour respecter strictement le plafond de 16KB du Recorder Home Assistant SQLite.
        # Tous les détails complets (auto_fix_script, YAML diff, etc.) sont servis en temps réel
        # sans aucune limite de taille par la commande WebSocket 'domolink_mistral/get_issues'.
        compact_issues = [
            {
                "id": str(i.get("id", "")),
                "title": str(i.get("title", ""))[:80],
                "severity": i.get("severity", "medium"),
                "category": i.get("category", "optimization"),
                "file": i.get("file", ""),
            }
            for i in valid_issues
        ]
        compact_ignored = [
            {
                "id": str(i.get("id", "")),
                "title": str(i.get("title", ""))[:80],
                "severity": i.get("severity", "medium"),
            }
            for i in valid_ignored
        ]

        candidate_compact = {
            **base_attrs,
            "issues": compact_issues,
            "ignored_issues": compact_ignored,
        }
        try:
            if len(json.dumps(candidate_compact, ensure_ascii=False)) < 12000:
                return candidate_compact
        except Exception:
            pass

        # 3. Dernier recours strict sous 10 KB
        safe_issues = compact_issues[:20]
        return {
            **base_attrs,
            "issues": safe_issues,
            "ignored_issues": compact_ignored[:10],
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
        safe_issues = [i for i in (issues or []) if isinstance(i, dict)]

        self._issues = [i for i in safe_issues if i.get("id") not in ignored_ids]
        self._ignored_issues = [i for i in safe_issues if i.get("id") in ignored_ids]
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
