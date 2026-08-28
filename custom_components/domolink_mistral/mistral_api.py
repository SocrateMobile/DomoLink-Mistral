"""Client API Mistral pour DomoLink-Mistral.

Envoie les données système, logs et fichiers YAML à l'API Mistral et parse la réponse JSON structurée.
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

SYSTEM_PROMPT = """Tu es un expert senior en domotique, en Home Assistant et en ESPHome.
Tu analyses un diagnostic approfondi d'une instance Home Assistant contenant :
- Les fichiers YAML : configuration.yaml, tous ses !include, automations.yaml, scripts.yaml, scenes.yaml
- Les Blueprints (automations et scripts)
- Les configurations ESPHome Builder (fichiers esphome/*.yaml)
- Les erreurs et avertissements des logs (homeassistant.log et system_log)
- L'état des intégrations configurées et des entités indisponibles ou inconnues
- L'état des automations et scripts

Pour chaque élément, tu dois chercher :
1. ERREURS DE SYNTAXE & CONFIGURATION YAML : indentation invalide, clés inconnues ou dépréciées, !include cassés
2. PROBLÈMES D'AUTOMATIONS / BLUEPRINTS : entités orphelines, déclencheurs impossibles, automations désactivées par erreur
3. DÉFAUTS ESPHOME : plateformes dépréciées (ex: dallas remplacé par one_wire), conflits de pins GPIO, composants manquants
4. ERREURS SYSTÈME & LOGS : exceptions récurrentes, intégrations plantées, timeouts réseau
5. OPTIMISATIONS : nettoyages de doublons, simplifications, bonnes pratiques de nommage

Tu réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après."""

USER_PROMPT_TEMPLATE = """Analyse le rapport d'audit Home Assistant ci-dessous et retourne un JSON avec cette structure exacte :
{{
  "issues": [
    {{
      "id": "identifiant_unique_sans_espace",
      "severity": "high|medium|low",
      "category": "yaml_syntax|esphome|blueprint|automation|script|integration|entity|log_error|optimization",
      "title": "Titre court et clair du problème",
      "description": "Explication détaillée : quel fichier ou entité est concerné, pourquoi c'est un problème, et quel est l'impact.",
      "manual_fix": "Instructions pas-à-pas numérotées pour résoudre le problème manuellement (fichiers précis à ouvrir, lignes à modifier, code exact à coller).",
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

Format pour "auto_fix_script" :
- Pour une action via service HA : {{"domain": "automation", "service": "turn_on", "service_data": {{"entity_id": "automation.xyz"}}}}
- Pour une correction dans un fichier YAML : {{"action_type": "yaml_edit", "file": "automations.yaml", "find": "ancien_texte_a_remplacer", "replace": "nouveau_texte_corrige"}}
- Si aucune correction automatique sûre n'est possible, mets un tableau vide [].

Règles importantes :
- Classe les problèmes par gravité décroissante (high en premier).
- Ne signale pas les messages INFO normaux.
- Pour les erreurs de syntaxe YAML ou ESPHome, propose la correction exacte dans "manual_fix" et "auto_fix_script".

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
    """Envoie les données à Mistral et retourne un dictionnaire JSON."""
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
        "temperature": 0.1,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            response.raise_for_status()
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)

            if "issues" not in result:
                result = {"issues": []}

            return result

    except aiohttp.ClientResponseError as e:
        _LOGGER.error("Erreur HTTP de Mistral: %s - %s", e.status, e.message)
        return {"issues": []}
    except TimeoutError:
        _LOGGER.error("Timeout : Mistral n'a pas répondu dans le délai imparti.")
        return {"issues": []}
    except json.JSONDecodeError:
        _LOGGER.error("Mistral n'a pas renvoyé un JSON valide.")
        return {"issues": []}
    except Exception as e:
        _LOGGER.error("Erreur inattendue lors de l'appel à Mistral: %s", e)
        return {"issues": []}


GENERATE_AUTOMATION_SYSTEM_PROMPT = """Tu es un expert créateur d'automations Home Assistant.
L'utilisateur te décrit en langage naturel ce qu'il souhaite automatiser.
Tu dois générer une automation Home Assistant complète, moderne, sécurisée et syntaxiquement parfaite.

Règles de génération :
1. Utilise les vraies entités fournies dans le contexte si elles correspondent, sinon utilise des noms d'entités clairs et standard.
2. Structure YAML requise :
   alias: "Titre court et explicite"
   description: "Description de ce que fait l'automation"
   trigger:
     - ...
   condition: [] (ou liste de conditions)
   action:
     - ...
   mode: single (ou restart/parallel/queued selon le besoin)
3. Tu réponds UNIQUEMENT sous forme d'un objet JSON avec la structure :
{{
  "title": "Titre clair de l'automation",
  "description": "Courte description",
  "yaml": "le code YAML complet prêt à être injecté",
  "explanation": "Explication pas-à-pas en français du fonctionnement de l'automation"
}}"""


async def generate_automation_with_mistral(
    hass: HomeAssistant, api_key: str, model: str, user_prompt: str
) -> dict:
    """Génère une automation YAML complète via Mistral à partir d'une description textuelle."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Collecter un résumé compact des entités principales pour donner du contexte sans exploser les tokens
    relevant_domains = ("light", "switch", "binary_sensor", "sensor", "cover", "climate", "media_player", "input_boolean", "person", "alarm_control_panel")
    entity_summaries = []
    for state in hass.states.async_all():
        domain = state.domain
        if domain in relevant_domains:
            name = state.attributes.get("friendly_name", state.entity_id)
            entity_summaries.append(f"- {state.entity_id} ({name})")

    # Limiter à 60 entités pour économiser les tokens
    sample_entities = "\n".join(entity_summaries[:60])
    if len(entity_summaries) > 60:
        sample_entities += f"\n... et {len(entity_summaries) - 60} autres entités"

    user_content = f"""Voici les entités disponibles sur mon Home Assistant :
{sample_entities}

Demande de l'utilisateur :
"{user_prompt}"

Génère l'automation correspondante au format JSON structuré."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GENERATE_AUTOMATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            response.raise_for_status()
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lors de la génération d'automation: %s", e)
        return {"success": False, "error": str(e)}

