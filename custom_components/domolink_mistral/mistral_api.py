"""Client API Mistral pour DomoLink-Mistral.

Envoie les logs nettoyés à l'API Mistral et parse la réponse JSON structurée.
"""
import logging
import json

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"
API_TIMEOUT = aiohttp.ClientTimeout(total=60)

SYSTEM_PROMPT = """Tu es un expert en domotique et en Home Assistant.
Tu analyses les logs d'une instance Home Assistant pour trouver :
- Les erreurs et exceptions
- Les avertissements importants
- Les problèmes de configuration
- Les optimisations possibles (intégrations dépréciées, entités indisponibles, etc.)

Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après."""

USER_PROMPT_TEMPLATE = """Analyse les logs suivants et retourne un JSON avec cette structure exacte :
{{
  "issues": [
    {{
      "id": "identifiant_unique_sans_espace",
      "severity": "high|medium|low",
      "title": "Titre court et clair du problème",
      "description": "Explication détaillée de ce qui ne va pas et pourquoi c'est un problème.",
      "manual_fix": "Instructions pas-à-pas numérotées pour résoudre le problème manuellement. Sois très précis sur les menus, fichiers et lignes à modifier.",
      "auto_fix_script": [
        {{
          "domain": "domaine_ha",
          "service": "nom_du_service",
          "service_data": {{}}
        }}
      ]
    }}
  ]
}}

Règles importantes :
- "auto_fix_script" doit être un tableau JSON d'appels de services Home Assistant.
- Si le problème ne peut pas être corrigé automatiquement via un service HA, mets un tableau vide [].
- Classe les problèmes par gravité décroissante (high en premier).
- Ne signale pas les messages INFO normaux.

Voici les logs :
```
{logs}
```"""


async def validate_api_key(hass: HomeAssistant, api_key: str) -> bool:
    """Valide la clé API en appelant l'endpoint /models de Mistral."""
    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(
            MISTRAL_MODELS_URL, headers=headers, timeout=API_TIMEOUT
        ) as response:
            return response.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


async def analyze_with_mistral(
    hass: HomeAssistant, api_key: str, model: str, logs: str
) -> dict:
    """Envoie les logs nettoyés à Mistral et retourne un dictionnaire JSON."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(logs=logs)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,  # Réponses plus déterministes pour du diagnostic
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            response.raise_for_status()
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)

            # Validation de la structure
            if "issues" not in result:
                result = {"issues": []}

            return result

    except aiohttp.ClientResponseError as e:
        _LOGGER.error("Erreur HTTP de Mistral: %s - %s", e.status, e.message)
        return {"issues": []}
    except TimeoutError:
        _LOGGER.error("Timeout : Mistral n'a pas répondu dans les 60 secondes.")
        return {"issues": []}
    except json.JSONDecodeError:
        _LOGGER.error("Mistral n'a pas renvoyé un JSON valide.")
        return {"issues": []}
    except Exception as e:
        _LOGGER.error("Erreur inattendue lors de l'appel à Mistral: %s", e)
        return {"issues": []}
