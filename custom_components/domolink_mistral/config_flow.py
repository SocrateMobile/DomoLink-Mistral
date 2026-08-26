"""Config flow for Domolink-Mistral integration."""
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_API_KEY, CONF_MODEL, CONF_SCAN_MODE, CONF_SCAN_FREQUENCY, MODELS, SCAN_MODES

_LOGGER = logging.getLogger(__name__)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    if not data.get(CONF_API_KEY):
        raise InvalidAuth
    # Ici, nous pourrions faire un appel test à l'API Mistral pour valider la clé.
    return {"title": "Domolink-Mistral"}

class DomolinkMistralConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Domolink-Mistral."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self.api_key: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step (API Key)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
                self.api_key = user_input[CONF_API_KEY]
                return await self.async_step_settings()
            except InvalidAuth:
                errors["base"] = "auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the settings step."""
        if user_input is not None:
            return self.async_create_entry(
                title="Domolink-Mistral",
                data={CONF_API_KEY: self.api_key},
                options=user_input
            )
        
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Required(CONF_MODEL, default=MODELS[0]): vol.In(MODELS),
                vol.Required(CONF_SCAN_MODE, default="live"): vol.In(list(SCAN_MODES.keys())),
                vol.Optional(CONF_SCAN_FREQUENCY, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            })
        )

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
