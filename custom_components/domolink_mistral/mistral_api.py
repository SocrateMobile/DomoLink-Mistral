import logging
import json
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

PROMPT_TEMPLATE = """
Tu es un expert en domotique et en Home Assistant.
Analyse les logs suivants de Home Assistant. 
Trouve les erreurs, avertissements ou problèmes d'optimisation.

Réponds obligatoirement au format JSON strict avec la structure suivante :
{
  "issues": [
    {
      "id": "identifiant_unique_du_probleme_sans_espace",
      "severity": "high/medium/low",
      "title": "Titre court du problème",
      "description": "Explication détaillée de ce qui ne va pas.",
      "manual_fix": "Explication pas-à-pas pour l'utilisateur pour résoudre le problème manuellement",
      "auto_fix_script": "Le code de l'appel de service HA ou la modification JSON à appliquer. Laisse vide si non applicable."
    }
  ]
}

Voici les logs extraits du système :
```
{logs}
```
"""

async def analyze_with_mistral(hass: HomeAssistant, api_key: str, model: str, logs: str) -> dict:
    """Envoie les logs nettoyés à Mistral via l'API REST et retourne un dictionnaire JSON."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": PROMPT_TEMPLATE.format(logs=logs)}
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        async with session.post(MISTRAL_URL, headers=headers, json=payload) as response:
            response.raise_for_status()
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except aiohttp.ClientResponseError as e:
        _LOGGER.error("Erreur HTTP de Mistral: %s - %s", e.status, e.message)
        return {"issues": []}
    except json.JSONDecodeError:
        _LOGGER.error("Mistral n'a pas renvoyé un JSON valide.")
        return {"issues": []}
    except Exception as e:
        _LOGGER.error("Erreur inattendue lors de l'appel à Mistral: %s", e)
        return {"issues": []}
