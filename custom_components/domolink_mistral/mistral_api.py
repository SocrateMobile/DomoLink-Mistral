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
API_TIMEOUT = aiohttp.ClientTimeout(total=120)

SYSTEM_PROMPT = """Tu es un expert senior en domotique et en Home Assistant.
Tu analyses un rapport complet d'une instance Home Assistant contenant :
- Les logs d'erreurs et d'avertissements (homeassistant.log et system_log)
- L'état des intégrations configurées
- La liste des entités indisponibles ou en état inconnu
- L'état des automations (activées, désactivées, jamais déclenchées, blueprints)
- L'état des scripts (en cours, jamais utilisés)
- Les scènes configurées

Pour chaque section, tu dois chercher :
1. Les ERREURS CRITIQUES : exceptions, intégrations cassées, entités indisponibles utilisées dans des automations
2. Les PROBLÈMES DE CONFIGURATION : automations désactivées sans raison, scripts bloqués, entités orphelines
3. Les OPTIMISATIONS : intégrations dépréciées, doublons, automations jamais déclenchées, entités inutilisées
4. Les BONNES PRATIQUES : modes d'automation incorrects (single vs parallel), nommage incohérent, blueprints obsolètes

Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après."""

USER_PROMPT_TEMPLATE = """Analyse les logs suivants et retourne un JSON avec cette structure exacte :
{{
  "issues": [
    {{
      "id": "identifiant_unique_sans_espace",
      "severity": "high|medium|low",
      "category": "log_error|integration|entity|automation|script|optimization|best_practice",
      "title": "Titre court et clair du problème",
      "description": "Explication détaillée de ce qui ne va pas, pourquoi c'est un problème, et quel est l'impact.",
      "manual_fix": "Instructions pas-à-pas numérotées pour résoudre le problème manuellement. Sois très précis : quels fichiers ouvrir, quels menus, quelles lignes modifier, quels addons installer.",
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
- Ne signale pas les messages INFO normaux ni les warnings sans conséquence.
- Pour les automations désactivées, propose de les réactiver via automation.turn_on si pertinent.
- Pour les entités indisponibles, indique la cause probable (intégration hors ligne, appareil éteint, etc.).
- Sois concret et actionnable dans tes recommandations.

Voici le rapport complet de l'instance Home Assistant :
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
