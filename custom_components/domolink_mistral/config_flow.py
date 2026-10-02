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

try:
    from homeassistant.config_entries import ConfigFlowResult, OptionsFlowResult
except ImportError:
    ConfigFlowResult = config_entries.FlowResult
    OptionsFlowResult = config_entries.FlowResult

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_SCAN_MODE,
    CONF_SCAN_FREQUENCY,
    DEFAULT_MODEL,
    MODELS,
    SCAN_MODES,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_key(hass: HomeAssistant, api_key: str) -> None:
    """Valide la clé API en faisant un appel direct avec timeout court (15s)."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(
            "https://api.mistral.ai/v1/models",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status in (401, 403):
                raise InvalidAuth
            elif response.status != 200:
                raise CannotConnect
    except (aiohttp.ClientError, TimeoutError):
        raise CannotConnect


class DomolinkMistralConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère le flux de configuration de DomoLink-Mistral."""

    VERSION = 1

    def __init__(self):
        """Initialisation."""
        self.api_key: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 1 : Saisie de la clé API."""
        errors: dict[str, str] = {}

        await self.async_set_unique_id("domolink_mistral")
        self._abort_if_unique_id_configured()

        if user_input is not None:
            try:
                api_key = user_input[CONF_API_KEY].strip()
                if not api_key:
                    raise InvalidAuth

                await validate_api_key(self.hass, api_key)
                self.api_key = api_key
                return await self.async_step_settings()

            except InvalidAuth:
                errors["base"] = "invalid_auth"
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
    ) -> ConfigFlowResult:
        """Étape 2 : Choix du modèle et du mode de scan."""
        if user_input is not None:
            return self.async_create_entry(
                title="DomoLink-Mistral IA",
                data={CONF_API_KEY: self.api_key},
                options=user_input,
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=DEFAULT_MODEL): vol.In(MODELS),
                    vol.Required(CONF_SCAN_MODE, default="live"): vol.In(
                        list(SCAN_MODES.keys())
                    ),
                    vol.Optional(CONF_SCAN_FREQUENCY, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    ),
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Déclenche la réauthentification suite à une clé révoquée ou invalide."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirme la nouvelle clé API lors de la réauthentification."""
        errors: dict[str, str] = {}
        if user_input is not None:
            new_key = user_input.get(CONF_API_KEY, "").strip()
            try:
                await validate_api_key(self.hass, new_key)
                entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_API_KEY: new_key},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
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
        """Initialise le gestionnaire d'options."""
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Retourne la configuration actuelle."""
        return self._config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> OptionsFlowResult:
        """Gère les options modifiables."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Si une nouvelle clé API est saisie, la valider et l'enregistrer dans config_entry.data
            new_api_key = user_input.pop(CONF_API_KEY, "").strip()
            if new_api_key and new_api_key != self.config_entry.data.get(CONF_API_KEY, ""):
                try:
                    await validate_api_key(self.hass, new_api_key)
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_API_KEY: new_api_key},
                    )
                except InvalidAuth:
                    errors[CONF_API_KEY] = "invalid_auth"
                except CannotConnect:
                    errors[CONF_API_KEY] = "cannot_connect"
                except Exception:
                    errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current_options = self.config_entry.options
        current_model = current_options.get(CONF_MODEL, DEFAULT_MODEL)
        if current_model not in MODELS:
            current_model = DEFAULT_MODEL
        current_mode = current_options.get(CONF_SCAN_MODE, "live")
        current_freq = current_options.get(CONF_SCAN_FREQUENCY, 1)
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_KEY, default=current_api_key): str,
                    vol.Required(CONF_MODEL, default=current_model): vol.In(MODELS),
                    vol.Required(CONF_SCAN_MODE, default=current_mode): vol.In(
                        list(SCAN_MODES.keys())
                    ),
                    vol.Optional(CONF_SCAN_FREQUENCY, default=current_freq): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    ),
                }
            ),
            errors=errors,
        )


class InvalidAuth(HomeAssistantError):
    """Erreur : clé API invalide."""


class CannotConnect(HomeAssistantError):
    """Erreur : impossible de se connecter à l'API Mistral."""
