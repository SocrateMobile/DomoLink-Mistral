"""Plateforme Conversation pour DomoLink-Mistral (Home Assistant Assist).

Permet d'utiliser Mistral AI comme agent de conversation officiel dans Home Assistant
pour le contrôle vocal et textuel en langage naturel avec exécution d'actions domotiques.
"""
import logging
from collections import defaultdict
from datetime import datetime

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.intent import IntentResponse, IntentResponseType

from .const import DOMAIN, VERSION, DEFAULT_MODEL
from .mistral_api import process_conversation_with_mistral

_LOGGER = logging.getLogger(__name__)

# Domaines autorisés pour le pilotage vocal/conversationnel (aucun accès fichier/yaml/système)
ASSIST_ALLOWED_DOMAINS = {
    "light",
    "switch",
    "cover",
    "climate",
    "media_player",
    "fan",
    "scene",
    "lock",
    "vacuum",
    "button",
    "input_boolean",
}


async def _run_assist_calls(hass: HomeAssistant, calls: list, context=None) -> None:
    """Exécute uniquement des actions domotiques courantes sécurisées (sans accès fichiers ni admin)."""
    if not isinstance(calls, list):
        return

    for call in calls:
        if not isinstance(call, dict):
            continue

        svc = call.get("service")
        domain = call.get("domain")
        service = None

        if svc and "." in svc:
            parts = svc.split(".", 1)
            domain = parts[0]
            service = parts[1]
        elif svc and domain:
            service = svc
        elif call.get("action"):
            act = call.get("action")
            if "." in act:
                domain, service = act.split(".", 1)

        if not domain or not service:
            continue

        domain = str(domain).strip().lower()
        service = str(service).strip().lower()

        if domain not in ASSIST_ALLOWED_DOMAINS:
            _LOGGER.warning(
                "DomoLink-Mistral Assist: Domaine refusé '%s' (seuls les appareils domestiques sont autorisés)",
                domain,
            )
            continue

        # Données de service : interdire les paramètres dangereux
        data = call.get("service_data") or call.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        # Refuser entity_id 'all' pour éviter les actions globales non désirées
        target_entity = data.get("entity_id")
        if target_entity == "all" or target_entity == ["all"]:
            _LOGGER.warning("DomoLink-Mistral Assist: Appel global sur 'all' refusé par sécurité")
            continue

        # Filtrer toute clé suspecte liée aux fichiers ou à des injections
        safe_data = {
            k: v
            for k, v in data.items()
            if k not in ("file", "path", "content", "filename", "command", "url")
        }

        try:
            await hass.services.async_call(
                domain,
                service,
                safe_data,
                blocking=True,
                context=context,
            )
            _LOGGER.debug("DomoLink-Mistral Assist: Appel réussi %s.%s", domain, service)
        except Exception as err:
            _LOGGER.error(
                "DomoLink-Mistral Assist: Erreur lors de l'appel %s.%s : %s",
                domain,
                service,
                err,
            )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Configure la plateforme conversation pour DomoLink-Mistral."""
    async_add_entities([DomoLinkMistralConversationEntity(entry)])


class DomoLinkMistralConversationEntity(ConversationEntity):
    """Entité Agent de conversation DomoLink-Mistral."""

    _attr_has_entity_name = True
    _attr_name = "Mistral AI"
    _attr_icon = "mdi:brain"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialisation."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        self._history = {}

        # Activer le support du contrôle domotique si disponible
        if hasattr(conversation, "ConversationEntityFeature") and hasattr(
            conversation.ConversationEntityFeature, "CONTROL"
        ):
            self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> list[str]:
        """Langues supportées par l'agent."""
        return ["fr", "en", "es", "de", "it", "nl", "pt"]

    @property
    def device_info(self) -> DeviceInfo:
        """Associe cet agent à l'appareil DomoLink-Mistral."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="DomoLink-Mistral IA",
            manufacturer="SocrateMobile",
            model="Mistral AI Assist Agent",
            sw_version=VERSION,
        )

    def _get_entities_context(self) -> str:
        """Collecte l'état compact des principaux appareils exposés à Assist pour Mistral."""
        relevant_domains = (
            "light", "switch", "cover", "climate", "media_player",
            "fan", "lock", "vacuum", "scene", "script", "binary_sensor", "sensor"
        )

        try:
            from homeassistant.components.homeassistant.exposed_entities import (
                async_should_expose,
            )
            have_exposed_check = True
        except ImportError:
            have_exposed_check = False

        lines = [f"Date et heure actuelles : {datetime.now().strftime('%A %d %B %Y %H:%M')}"]
        count = 0

        for state in self.hass.states.async_all():
            domain = state.domain
            if domain in relevant_domains:
                # Filtrer les entités non exposées à la conversation par l'utilisateur
                if have_exposed_check and not async_should_expose(
                    self.hass, conversation.DOMAIN, state.entity_id
                ):
                    continue

                name = state.attributes.get("friendly_name", state.entity_id)
                st = state.state
                unit = state.attributes.get("unit_of_measurement", "")

                # Ignorer les capteurs de diagnostic trop verbeux
                if domain == "sensor" and any(x in state.entity_id for x in ("_uptime", "_ip", "_mac", "_version")):
                    continue

                val_str = f"{st} {unit}".strip()
                lines.append(f"- {state.entity_id} ('{name}'): {val_str}")
                count += 1
                if count >= 80:  # Limiter à 80 entités pour ne pas dépasser le quota
                    break

        return "\n".join(lines)

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Traite la demande vocale ou textuelle de l'utilisateur."""
        text = user_input.text
        conv_id = user_input.conversation_id or "default"
        lang = user_input.language or "fr"

        _LOGGER.info("DomoLink-Mistral Assist: Reçu '%s' (lang: %s, conv: %s)", text, lang, conv_id)

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        api_key = entry_data.get("api_key") or self._entry.data.get("api_key")
        model = entry_data.get("options", {}).get(
            "model", self._entry.options.get("model", DEFAULT_MODEL)
        )

        # Contexte domotique
        entities_context = self._get_entities_context()

        # Récupérer l'historique existant pour cette conversation
        conv_history = self._history.get(conv_id, [])

        # Appel à Mistral
        res = await process_conversation_with_mistral(
            self.hass,
            api_key=api_key,
            model=model,
            user_text=text,
            history=conv_history,
            entities_context=entities_context,
            language=lang,
        )

        response_text = res.get("response_text", "Je n'ai pas compris votre demande.")
        service_calls = res.get("service_calls", [])

        # Exécution des actions domotiques demandées (strictement isolée du réparateur système)
        if service_calls:
            _LOGGER.info("DomoLink-Mistral Assist: Exécution de %s action(s)", len(service_calls))
            await _run_assist_calls(self.hass, service_calls, context=user_input.context)

        # Mémoriser dans l'historique de session
        conv_history.append({"role": "user", "content": text})
        conv_history.append({"role": "assistant", "content": response_text})

        # Nettoyage de l'historique (max 10 tours)
        if len(conv_history) > 10:
            conv_history = conv_history[-10:]

        self._history[conv_id] = conv_history

        # Bander la mémoire globale à 50 conversations max
        if len(self._history) > 50:
            oldest_key = next(iter(self._history))
            self._history.pop(oldest_key, None)

        # Création de la réponse d'intention standard Home Assistant
        intent_response = IntentResponse(language=lang)
        intent_response.async_set_speech(response_text)

        return ConversationResult(
            response=intent_response,
            conversation_id=conv_id,
        )
