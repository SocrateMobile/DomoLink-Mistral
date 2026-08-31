"""Client API Mistral pour DomoLink-Mistral.

Envoie les données système, logs et fichiers YAML à l'API Mistral et parse la réponse JSON structurée.
"""
import logging
import json
import re

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"
API_TIMEOUT = aiohttp.ClientTimeout(total=120)


def _safe_json_loads(content: str) -> dict:
    """Nettoie et parse de manière robuste une réponse JSON de Mistral."""
    if not content:
        return {}
    cleaned = content.strip()
    # Supprimer les balises ```json ou ``` éventuelles
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    return json.loads(cleaned)

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
            result = _safe_json_loads(content)

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
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lors de la génération d'automation: %s", e)
        return {"success": False, "error": str(e)}


CONVERSATION_SYSTEM_PROMPT = """Tu es l'assistant vocal et domotique de la maison Home Assistant, propulsé par Mistral AI.
Tu es serviable, précis, courtois et très concis (tes réponses sont destinées à être lues ou énoncées oralement).

Tu as accès à la liste et à l'état des appareils disponibles dans la maison.
- Si l'utilisateur demande d'effectuer une action (contrôle de lumières, volets, clim, scènes, etc.), tu dois inclure la liste des appels de services correspondants dans "service_calls".
- Si l'utilisateur pose une question sur l'état d'un appareil, utilise les données fournies pour répondre précisément.
- Réponds toujours dans la langue de l'utilisateur.

Format JSON strict obligatoire :
{{
  "response_text": "Ta réponse courte et naturelle à l'utilisateur",
  "service_calls": [
    {{
      "domain": "nom_du_domaine",
      "service": "nom_du_service",
      "service_data": {{"entity_id": "..."}}
    }}
  ]
}}"""


async def process_conversation_with_mistral(
    hass: HomeAssistant,
    api_key: str,
    model: str,
    user_text: str,
    history: list,
    entities_context: str,
    language: str = "fr",
) -> dict:
    """Traite une commande vocale ou textuelle de l'utilisateur et retourne la réponse et les actions."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Préparer les messages avec l'historique récent
    messages = [{"role": "system", "content": CONVERSATION_SYSTEM_PROMPT}]

    # Ajouter le contexte des entités dans le premier message ou le message système
    context_msg = f"Contexte de la maison (Appareils et états actuels) :\n{entities_context}\nLangue préférée : {language}"
    messages.append({"role": "user", "content": f"[Données domotiques]\n{context_msg}"})
    messages.append({"role": "assistant", "content": '{"response_text": "Compris, je suis prêt à vous aider avec votre maison.", "service_calls": []}'})

    # Ajouter les derniers échanges pour garder la mémoire du dialogue
    for item in history[-6:]:
        messages.append(item)

    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": model,
        "messages": messages,
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
            result = _safe_json_loads(content)
            return {
                "success": True,
                "response_text": result.get("response_text", "D'accord."),
                "service_calls": result.get("service_calls", []),
            }
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Assist: Erreur conversation Mistral: %s", e)
        return {
            "success": False,
            "response_text": f"Désolé, une erreur est survenue lors de la communication avec Mistral : {e}",
            "service_calls": [],
        }


PIXTRAL_DEFAULT_MODEL = "pixtral-12b-2409"


async def analyze_image_with_pixtral(
    hass: HomeAssistant,
    api_key: str,
    base64_image: str,
    prompt: str = "Décris précisément ce que tu vois sur cette image. Détecte les personnes, véhicules, colis, ouvertures ou anomalies.",
    model: str = PIXTRAL_DEFAULT_MODEL,
    mime_type: str = "image/jpeg",
) -> dict:
    """Analyse une image de caméra via le modèle multimodal Pixtral."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    system_instruction = (
        "Tu es l'agent de surveillance visuelle de Home Assistant. "
        "Analyse l'image fournie et réponds UNIQUEMENT en JSON avec la structure :\n"
        "{\n"
        '  "summary": "Court résumé en 1 phrase",\n'
        '  "description": "Description détaillée de la scène",\n'
        '  "anomalies_detected": true/false,\n'
        '  "objects_detected": ["personne", "colis", "véhicule", ...],\n'
        '  "security_alert": true/false\n'
        "}"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{system_instruction}\n\nQuestion de l'utilisateur : {prompt}"},
                    {"type": "image_url", "image_url": f"data:{mime_type};base64,{base64_image}"},
                ],
            }
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
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Vision: Erreur analyse image Pixtral: %s", e)
        return {"success": False, "error": str(e)}


async def generate_daily_briefing_with_mistral(
    hass: HomeAssistant,
    api_key: str,
    model: str,
    system_data: str,
    time_of_day: str = "morning",
    custom_instruction: str = "",
) -> dict:
    """Génère un briefing domotique synthétique et chaleureux (pour TTS ou notification)."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    moment_fr = "matin" if time_of_day == "morning" else ("soir" if time_of_day == "evening" else "journée")

    prompt = f"""Tu es l'assistant de la maison. Rédige un briefing pour le {moment_fr}.
Voici les données actuelles de la maison :
{system_data}

{f"Instruction particulière : {custom_instruction}" if custom_instruction else ""}

Consignes :
1. Ton texte doit être fluide, bienveillant, naturel et agréable à écouter vocalement.
2. Signale les points d'attention importants (portes ouvertes, batteries faibles <20%, alertes météo).
3. Reste concis (3 à 5 phrases au maximum).

Réponds UNIQUEMENT en JSON avec la structure :
{{
  "title": "Titre du briefing",
  "speech_text": "Le texte complet destiné à être lu oralement",
  "highlights": ["Point 1", "Point 2", "Point 3"]
}}"""

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            response.raise_for_status()
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Briefing: Erreur génération briefing: %s", e)
        return {"success": False, "error": str(e)}



