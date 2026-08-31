"""Config flow pour l'intégration DomoLink-Mistral.

Étape 1 : Saisie et validation de la clé API Mistral (appel réseau réel)
Étape 2 : Choix du modèle, du mode de scan et de la fréquence
"""
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_SCAN_MODE,
    CONF_SCAN_FREQUENCY,
    MODELS,
    SCAN_MODES,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_key(hass: HomeAssistant, api_key: str) -> None:
    """Valide la clé API en faisant un appel réel à l'API Mistral."""
    from .mistral_api import validate_api_key as _validate

    try:
        is_valid = await _validate(hass, api_key)
        if not is_valid:
            raise InvalidAuth
    except aiohttp.ClientError:
        raise CannotConnect


class DomolinkMistralConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration de DomoLink-Mistral."""

    VERSION = 1

    def __init__(self):
        """Initialisation."""
        self.api_key: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Étape 1 : Saisie de la clé API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                api_key = user_input[CONF_API_KEY].strip()
                if not api_key:
                    raise InvalidAuth

                await validate_api_key(self.hass, api_key)
                self.api_key = api_key
                return await self.async_step_settings()

            except InvalidAuth:
                errors["base"] = "auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Erreur inattendue lors de la validation")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Étape 2 : Choix du modèle et du mode de scan."""
        if user_input is not None:
            return self.async_create_entry(
                title="DomoLink-Mistral",
                data={CONF_API_KEY: self.api_key},
                options=user_input,
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=MODELS[0]): vol.In(MODELS),
                    vol.Required(CONF_SCAN_MODE, default="live"): vol.In(
                        list(SCAN_MODES.keys())
                    ),
                    vol.Optional(CONF_SCAN_FREQUENCY, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    ),
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Crée le gestionnaire d'options."""
        return DomolinkMistralOptionsFlowHandler(config_entry)


class DomolinkMistralOptionsFlowHandler(config_entries.OptionsFlow):
    """Gère la modification des paramètres post-installation."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialisation."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Gère les options modifiables."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_options = self.config_entry.options
        current_model = current_options.get(CONF_MODEL, MODELS[0])
        current_mode = current_options.get(CONF_SCAN_MODE, "live")
        current_freq = current_options.get(CONF_SCAN_FREQUENCY, 1)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=current_model): vol.In(MODELS),
                    vol.Required(CONF_SCAN_MODE, default=current_mode): vol.In(
                        list(SCAN_MODES.keys())
                    ),
                    vol.Optional(CONF_SCAN_FREQUENCY, default=current_freq): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    ),
                }
            ),
        )


class InvalidAuth(HomeAssistantError):
    """Erreur : clé API invalide."""


class CannotConnect(HomeAssistantError):
    """Erreur : impossible de se connecter à l'API Mistral."""
