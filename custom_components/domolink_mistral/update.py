"""Plateforme Update pour DomoLink-Mistral IA.

Expose l'entité standard update.domolink_mistralia à Home Assistant,
permettant le suivi natif des versions dans Paramètres > Mises à jour
et l'installation en 1 clic.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, VERSION
from .updater import UpdateManager, get_installed_version

_LOGGER = logging.getLogger(__name__)
UPDATE_CHECK_INTERVAL = timedelta(hours=4)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure la plateforme update."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    updater: UpdateManager = entry_data.get("updater")
    if not updater:
        updater = UpdateManager(hass, entry.entry_id)
        entry_data["updater"] = updater

    entity = DomolinkMistralUpdateEntity(hass, entry, updater)
    entry_data["update_entity"] = entity
    async_add_entities([entity], False)


class DomolinkMistralUpdateEntity(UpdateEntity):
    """Entité de mise à jour native pour DomoLink-Mistral IA."""

    _attr_has_entity_name = True
    _attr_name = "Mise à jour"
    _attr_title = "DomoLink-Mistral IA"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
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
        current_ver = get_installed_version()
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_installed_version = current_ver
        self._attr_latest_version = current_ver
        self._attr_release_url = updater.release_url
        self._attr_release_summary = updater.changelog
        self._unsub_interval = None

    async def async_added_to_hass(self) -> None:
        """Enregistre le suivi périodique et effectue une première vérification."""
        await super().async_added_to_hass()
        self._unsub_interval = async_track_time_interval(
            self.hass, self._async_periodic_check, UPDATE_CHECK_INTERVAL
        )
        self.hass.async_create_task(self.async_update())

    async def async_will_remove_from_hass(self) -> None:
        """Nettoyage lors du retrait de l'entité."""
        if self._unsub_interval:
            self._unsub_interval()
            self._unsub_interval = None
        await super().async_will_remove_from_hass()

    async def _async_periodic_check(self, _now=None) -> None:
        """Vérification périodique."""
        await self.async_update()

    def _update_sidebar_panel(self, has_update: bool) -> None:
        """Met à jour le badge et l'icône dans la barre latérale gauche de HA."""
        try:
            title = "DomoLink-Mistral IA 🔴" if has_update else "DomoLink-Mistral IA"
            icon = "mdi:shield-alert" if has_update else "mdi:brain"
            frontend.async_register_built_in_panel(
                self.hass,
                component_name="custom",
                sidebar_title=title,
                sidebar_icon=icon,
                frontend_url_path="domolink_mistral",
                config={
                    "_panel_custom": {
                        "name": "domolink-mistral-panel",
                        "module_url": f"/domolink_mistral_frontend/domolink-mistral-panel.js?v={get_installed_version()}",
                    }
                },
                require_admin=False,
                update=True,
            )
        except Exception as err:
            _LOGGER.debug("Could not update sidebar panel registration: %s", err)

    @property
    def device_info(self) -> DeviceInfo:
        """Associe cette entité à l'appareil DomoLink-Mistral IA."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="DomoLink-Mistral IA",
            manufacturer="SocrateMobile",
            model="Mistral AI Diagnostic & Assistant",
            sw_version=get_installed_version(),
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

    async def async_install(self, version: str | None = None, backup: bool = True, **kwargs: Any) -> None:
        """Lance le processus d'installation 1-clic."""
        _LOGGER.info("DomoLink-Mistral IA: Lancement de l'installation depuis l'entité Update...")
        self._attr_in_progress = True
        if self.entity_id is not None:
            self.async_write_ha_state()

        try:
            result = await self._updater.async_install_update(restart_after=True, backup=backup)
            if not result.get("success"):
                raise HomeAssistantError(result.get("error", "Échec de l'installation"))
            self._update_sidebar_panel(False)
            self._attr_installed_version = self._updater.current_version
        finally:
            self._attr_in_progress = False
            if self.entity_id is not None:
                self.async_write_ha_state()

    async def async_update(self) -> None:
        """Rafraîchit l'état depuis GitHub."""
        await self._updater.async_check()
        self._attr_installed_version = self._updater.current_version
        self._attr_latest_version = self._updater.latest_version
        self._attr_release_url = self._updater.release_url
        self._attr_release_summary = self._updater.changelog
        self._update_sidebar_panel(self._updater.has_update)
        if self.entity_id is not None:
            self.async_write_ha_state()
