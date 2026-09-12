"""Plateforme Update pour DomoLink-Mistral IA.

Expose l'entité standard update.domolink_mistralia à Home Assistant,
permettant le suivi natif des versions dans Paramètres > Mises à jour
et l'installation en 1 clic.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERSION
from .updater import UpdateManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure la plateforme update."""
    updater: UpdateManager = hass.data[DOMAIN][entry.entry_id].get("updater")
    if not updater:
        updater = UpdateManager(hass, entry.entry_id)
        hass.data[DOMAIN][entry.entry_id]["updater"] = updater

    entity = DomolinkMistralUpdateEntity(hass, entry, updater)
    hass.data[DOMAIN][entry.entry_id]["update_entity"] = entity
    async_add_entities([entity], True)


class DomolinkMistralUpdateEntity(UpdateEntity):
    """Entité de mise à jour native pour DomoLink-Mistral IA."""

    _attr_has_entity_name = True
    _attr_name = "Mise à jour"
    _attr_title = "DomoLink-Mistral IA"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, updater: UpdateManager) -> None:
        """Initialisation."""
        self.hass = hass
        self._entry = entry
        self._updater = updater
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_installed_version = VERSION
        self._attr_latest_version = VERSION
        self._attr_release_url = updater.release_url
        self._attr_release_summary = updater.changelog

    @property
    def device_info(self) -> DeviceInfo:
        """Associe cette entité à l'appareil DomoLink-Mistral IA."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="DomoLink-Mistral IA",
            manufacturer="SocrateMobile",
            model="Mistral AI Diagnostic & Assistant",
            sw_version=VERSION,
        )

    @property
    def installed_version(self) -> str | None:
        """Version actuellement installée."""
        return self._updater.current_version

    @property
    def latest_version(self) -> str | None:
        """Dernière version disponible sur GitHub."""
        return self._updater.latest_version

    @property
    def release_url(self) -> str | None:
        """URL de la release GitHub."""
        return self._updater.release_url

    @property
    def release_summary(self) -> str | None:
        """Résumé / Notes de version."""
        return self._updater.changelog

    @property
    def in_progress(self) -> bool | int | None:
        """Indicateur de progression pendant l'installation."""
        if self._updater.is_updating:
            return self._updater.update_progress
        return False

    async def async_release_notes(self) -> str | None:
        """Renvoie le changelog complet de la release."""
        if not self._updater.changelog:
            await self._updater.async_check()
        return self._updater.changelog

    async def async_install(self, version: str | None = None, backup: bool = False, **kwargs: Any) -> None:
        """Lance le processus d'installation 1-clic."""
        _LOGGER.info("DomoLink-Mistral IA: Lancement de l'installation depuis l'entité Update...")
        self._attr_in_progress = True
        self.async_write_ha_state()

        result = await self._updater.async_install_update(restart_after=True)
        if not result.get("success"):
            _LOGGER.error("DomoLink-Mistral IA: Échec installation: %s", result.get("error"))

        self._attr_in_progress = False
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Rafraîchit l'état depuis GitHub."""
        await self._updater.async_check()
        self._attr_installed_version = self._updater.current_version
        self._attr_latest_version = self._updater.latest_version
        self._attr_release_url = self._updater.release_url
        self._attr_release_summary = self._updater.changelog
