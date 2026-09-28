"""Client API Mistral pour DomoLink-Mistral.

Envoie les données système, logs et fichiers YAML à l'API Mistral et parse la réponse JSON structurée.
"""
import logging
import json
import re

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

from .analyzer import sanitize_logs

_LOGGER = logging.getLogger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"
API_TIMEOUT = aiohttp.ClientTimeout(total=120)


def _safe_json_loads(content: str) -> dict:
    """Nettoie et parse de manière ultra-robuste une réponse JSON de Mistral."""
    if not content:
        return {}

    cleaned = content.strip()

    # 1. Tentative directe
    try:
        res = json.loads(cleaned, strict=False)
        if isinstance(res, dict):
            return res
        if isinstance(res, list):
            return {"issues": res}
    except Exception:
        pass

    # 2. Si le texte commence par une balise markdown ```json, on retire uniquement la balise d'en-tête et de fin globale
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # 3. Extraction entre le premier "{" et le dernier "}" de niveau racine
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = cleaned[first_brace : last_brace + 1]
        try:
            res = json.loads(candidate, strict=False)
            if isinstance(res, dict):
                return res
            if isinstance(res, list):
                return {"issues": res}
        except Exception:
            pass

    if first_brace != -1:
        cleaned = cleaned[first_brace:]

    # 4. Correction des antislashs non valides en JSON (ex: \s, \d, \w, regex, chemins)
    sanitized = re.sub(r'\\(?![/\"\\bfnrtu])', r'\\\\', cleaned)
    try:
        res = json.loads(sanitized, strict=False)
        if isinstance(res, dict):
            return res
        if isinstance(res, list):
            return {"issues": res}
    except Exception:
        pass

    # 5. Nettoyage des virgules orphelines (ex: [1, 2, ])
    no_trailing = re.sub(r",\s*([}\]])", r"\1", sanitized)
    try:
        res = json.loads(no_trailing, strict=False)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # 6. Sauvetage chirurgical en cas de JSON tronqué (max_tokens atteint ou coupure)
    in_str = False
    esc = False
    for ch in no_trailing:
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str

    repaired = no_trailing.rstrip()
    if in_str:
        # Fermer la chaîne coupée au milieu d'un nom de clé ou d'une valeur
        repaired += '"'

    # Supprimer les clés orphelines partielles ou sans valeur
    repaired = re.sub(r',\s*"[^"]*"\s*:\s*$', "", repaired)
    repaired = re.sub(r',\s*"[^"]*"\s*$', "", repaired)
    repaired = re.sub(r',\s*([}\]])', r"\1", repaired)

    # Reconstitution de la pile exacte d'accolades et de crochets ouverts
    stack = []
    in_str = False
    esc = False
    for ch in repaired:
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in '}]':
            if stack and stack[-1] == ch:
                stack.pop()

    repaired_with_closing = repaired + ''.join(reversed(stack))
    try:
        res = json.loads(repaired_with_closing, strict=False)
        if isinstance(res, dict):
            _LOGGER.warning("DomoLink-Mistral: Réponse JSON tronquée réparée avec succès.")
            return res
        if isinstance(res, list):
            return {"issues": res}
    except Exception:
        pass

    # 7. Filet de sécurité : extraction regex de chaque bloc d'anomalie {...}
    issue_objects = []
    pattern = re.compile(r'\{[^{}]*"id"\s*:\s*"[^"]+"[^{}]*\}', re.DOTALL)
    for m in pattern.finditer(cleaned):
        try:
            obj = json.loads(m.group(0), strict=False)
            if isinstance(obj, dict) and "id" in obj:
                issue_objects.append(obj)
        except Exception:
            pass

    if issue_objects:
        _LOGGER.warning("DomoLink-Mistral: %s anomalies extraites par parsing résilient.", len(issue_objects))
        return {"issues": issue_objects}

    # 8. En cas d'échec total, lever une erreur explicite avec le début de la réponse pour le débug
    snippet = cleaned[:200] if len(cleaned) > 200 else cleaned
    raise json.JSONDecodeError(f"Contenu non convertible en JSON (extrait: '{snippet}')", cleaned, 0)

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
- IMPORTANT JSON : Pour citer des mots, entités ou plateformes dans les textes (title, description, manual_fix), utilise UNIQUEMENT des apostrophes simples '...' (ex: 'dallas' ou 'light.salon') et JAMAIS de guillemets doubles non échappés.
- Reste synthétique et direct dans chaque description pour garantir une réponse complète sans coupure.

Voici le rapport complet de l'instance Home Assistant :
```
{logs}
```"""


def _format_mistral_http_error(status: int, message: str = "") -> dict:
    """Formate une erreur HTTP Mistral avec un diagnostic clair pour l'utilisateur."""
    if status == 400:
        return {
            "type": "bad_request",
            "user_msg": (
                f"⚠️ Requête invalide (HTTP 400 : {message}). "
                "Le modèle sélectionné n'est plus supporté par Mistral AI ou la requête est malformée. "
                "Veuillez choisir un modèle compatible comme 'open-mistral-nemo' ou 'ministral-8b-latest' dans les options de l'intégration."
            ),
            "log": f"Erreur HTTP 400 Bad Request : {message}",
        }
    elif status == 401:
        return {
            "type": "auth_error",
            "user_msg": (
                "🔑 Clé API invalide ou révoquée (HTTP 401 : Unauthorized). "
                "Veuillez vérifier votre clé API sur console.mistral.ai et mettre à jour la configuration DomoLink-Mistral."
            ),
            "log": f"Erreur HTTP 401 Unauthorized (Clé API Mistral invalide) : {message}",
        }
    elif status == 403:
        return {
            "type": "forbidden",
            "user_msg": (
                f"⛔ Accès refusé (HTTP 403 : {message}). "
                "Ce modèle (ex: mistral-large) n'est pas autorisé avec votre formule d'abonnement Mistral. "
                "Si vous avez une clé gratuite, sélectionnez 'open-mistral-nemo' ou 'ministral-8b-latest' dans les options de l'intégration."
            ),
            "log": f"Erreur HTTP 403 Forbidden : {message}",
        }
    elif status == 429:
        return {
            "type": "rate_limit",
            "user_msg": (
                "🚫 Limite de requêtes atteinte (HTTP 429 : Too Many Requests). "
                "Votre quota Mistral AI est temporairement dépassé ou votre palier de requêtes/minute a été atteint. "
                "Vérifiez votre consommation sur console.mistral.ai ou réessayez dans quelques minutes."
            ),
            "log": f"Erreur HTTP 429 Too Many Requests (Quota ou Rate Limit Mistral dépassé) : {message}",
        }
    elif status >= 500:
        return {
            "type": "server_error",
            "user_msg": f"🌐 Panne ou surcharge temporaire des serveurs Mistral AI (HTTP {status}). Veuillez réessayer dans quelques instants.",
            "log": f"Erreur serveur Mistral HTTP {status} : {message}",
        }
    else:
        return {
            "type": "http_error",
            "user_msg": f"❌ Erreur API Mistral (HTTP {status} : {message})",
            "log": f"Erreur HTTP {status} : {message}",
        }


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
        "max_tokens": 8192,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            if response.status != 200:
                err_data = {}
                try:
                    err_data = await response.json()
                except Exception:
                    pass
                raw_msg = err_data.get("message") if isinstance(err_data, dict) else ""
                err_info = _format_mistral_http_error(
                    response.status,
                    raw_msg or response.reason or "",
                )
                _LOGGER.error("DomoLink-Mistral: %s", err_info["log"])
                return {
                    "success": False,
                    "error": err_info["user_msg"],
                    "error_type": err_info["type"],
                    "issues": [],
                }

            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = _safe_json_loads(content)

            if "issues" not in result:
                result = {"issues": []}

            result["success"] = True
            return result

    except aiohttp.ClientResponseError as e:
        err_info = _format_mistral_http_error(e.status, e.message)
        _LOGGER.error("DomoLink-Mistral: %s", err_info["log"])
        return {
            "success": False,
            "error": err_info["user_msg"],
            "error_type": err_info["type"],
            "issues": [],
        }
    except TimeoutError:
        user_msg = "⏱️ Délai dépassé (Timeout 120s) : Mistral n'a pas répondu. Le rapport est peut-être trop volumineux."
        _LOGGER.error("DomoLink-Mistral: %s", user_msg)
        return {
            "success": False,
            "error": user_msg,
            "error_type": "timeout",
            "issues": [],
        }
    except json.JSONDecodeError as e:
        user_msg = "⚠️ Format de réponse invalide : Mistral n'a pas renvoyé un JSON valide."
        _LOGGER.error("DomoLink-Mistral: %s (%s)", user_msg, e)
        return {
            "success": False,
            "error": user_msg,
            "error_type": "json_error",
            "issues": [],
        }
    except Exception as e:
        user_msg = f"❌ Erreur inattendue lors de l'appel à Mistral : {e}"
        _LOGGER.error("DomoLink-Mistral: %s", user_msg)
        return {
            "success": False,
            "error": user_msg,
            "error_type": "unknown",
            "issues": [],
        }


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
    sample_entities = sanitize_logs("\n".join(entity_summaries[:60]))
    if len(entity_summaries) > 60:
        sample_entities += f"\n... et {len(entity_summaries) - 60} autres entités"

    clean_prompt = sanitize_logs(user_prompt or "")

    user_content = f"""Voici les entités disponibles sur mon Home Assistant :
{sample_entities}

Demande de l'utilisateur :
"{clean_prompt}"

Génère l'automation correspondante au format JSON structuré."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GENERATE_AUTOMATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            if response.status != 200:
                err_data = {}
                try:
                    err_data = await response.json()
                except Exception:
                    pass
                raw_msg = err_data.get("message") if isinstance(err_data, dict) else (response.reason or "")
                err_info = _format_mistral_http_error(response.status, raw_msg)
                return {"success": False, "error": err_info["user_msg"], "response_text": err_info["user_msg"], "service_calls": []}
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lors de la génération d'automation: %s", e)
        return {"success": False, "error": str(e), "response_text": f"Désolé, une erreur est survenue: {e}", "service_calls": []}


CONVERSATION_SYSTEM_PROMPT = """Tu es l'assistant vocal et domotique de la maison Home Assistant, propulsé par Mistral AI.
Tu es serviable, précis, courtois et très concis (tes réponses sont destinées à être lues ou énoncées oralement).

Tu as accès à la liste et à l'état des appareils disponibles dans la maison via le contexte.
- Si l'utilisateur demande d'effectuer une action (contrôle de lumières, volets, clim, scènes, etc.), tu dois utiliser l'outil 'call_service' pour l'exécuter.
- Si l'utilisateur pose une question, réponds simplement avec les informations du contexte.
- Réponds toujours dans la langue de l'utilisateur."""

async def process_conversation_with_mistral(
    hass: HomeAssistant,
    api_key: str,
    model: str,
    user_text: str,
    history: list,
    entities_context: str,
    language: str = "fr",
) -> dict:
    """Traite une commande vocale ou textuelle de l'utilisateur avec Function Calling natif."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    messages = [{"role": "system", "content": CONVERSATION_SYSTEM_PROMPT}]
    context_msg = f"Contexte de la maison (Appareils et états actuels) :\n{entities_context}\nLangue préférée : {language}"
    messages.append({"role": "user", "content": f"[Données domotiques]\n{context_msg}"})
    messages.append({"role": "assistant", "content": "Compris, je suis prêt à vous aider avec votre maison."})

    for item in history[-6:]:
        messages.append(item)

    messages.append({"role": "user", "content": user_text})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "call_service",
                "description": "Appelle un service Home Assistant pour contrôler la maison.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Le domaine HA (ex: light, switch, climate, scene)"},
                        "service": {"type": "string", "description": "Le nom du service (ex: turn_on, turn_off, set_temperature)"},
                        "service_data": {"type": "object", "description": "Les données du service, contenant obligatoirement entity_id"}
                    },
                    "required": ["domain", "service", "service_data"]
                }
            }
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.1,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            if response.status != 200:
                err_data = {}
                try:
                    err_data = await response.json()
                except Exception:
                    pass
                raw_msg = err_data.get("message") if isinstance(err_data, dict) else (response.reason or "")
                err_info = _format_mistral_http_error(response.status, raw_msg)
                return {"success": False, "response_text": err_info["user_msg"], "service_calls": []}
            data = await response.json()
            message_obj = data["choices"][0]["message"]
            response_text = message_obj.get("content") or ""
            
            service_calls = []
            if "tool_calls" in message_obj and message_obj["tool_calls"]:
                for tool in message_obj["tool_calls"]:
                    if tool["function"]["name"] == "call_service":
                        try:
                            args = json.loads(tool["function"]["arguments"])
                            service_calls.append(args)
                        except Exception as e:
                            _LOGGER.error("Erreur parsing arguments tool_call: %s", e)
                            
                if not response_text:
                    response_text = "C'est fait !"

            return {
                "success": True,
                "response_text": response_text,
                "service_calls": service_calls,
            }

    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Assist Error: %s", e)
        return {"success": False, "response_text": f"Désolé, une erreur est survenue: {e}", "service_calls": []}


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

    clean_prompt = sanitize_logs(prompt or "")

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
                    {"type": "text", "text": f"{system_instruction}\n\nQuestion de l'utilisateur : {clean_prompt}"},
                    {"type": "image_url", "image_url": f"data:{mime_type};base64,{base64_image}"},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            if response.status != 200:
                err_data = {}
                try:
                    err_data = await response.json()
                except Exception:
                    pass
                raw_msg = err_data.get("message") if isinstance(err_data, dict) else (response.reason or "")
                err_info = _format_mistral_http_error(response.status, raw_msg)
                return {"success": False, "error": err_info["user_msg"], "response_text": err_info["user_msg"]}
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Vision: Erreur analyse image Pixtral: %s", e)
        return {"success": False, "error": str(e), "response_text": f"Désolé, une erreur est survenue: {e}"}


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

    clean_data = sanitize_logs(system_data or "")
    clean_custom = sanitize_logs(custom_instruction or "")

    moment_fr = "matin" if time_of_day == "morning" else ("soir" if time_of_day == "evening" else "journée")

    prompt = f"""Tu es l'assistant de la maison. Rédige un briefing pour le {moment_fr}.
Voici les données actuelles de la maison :
{clean_data}

{f"Instruction particulière : {clean_custom}" if clean_custom else ""}

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
        "max_tokens": 4096,
    }

    try:
        async with session.post(
            MISTRAL_URL, headers=headers, json=payload, timeout=API_TIMEOUT
        ) as response:
            if response.status != 200:
                err_data = {}
                try:
                    err_data = await response.json()
                except Exception:
                    pass
                raw_msg = err_data.get("message") if isinstance(err_data, dict) else (response.reason or "")
                err_info = _format_mistral_http_error(response.status, raw_msg)
                return {"success": False, "error": err_info["user_msg"], "response_text": err_info["user_msg"]}
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            result = _safe_json_loads(content)
            return {"success": True, "data": result}
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral Briefing: Erreur génération briefing: %s", e)
        return {"success": False, "error": str(e), "response_text": f"Désolé, une erreur est survenue: {e}"}



