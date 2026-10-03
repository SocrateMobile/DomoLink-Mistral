"""Client API Mistral pour DomoLink-Mistral.

Envoie les données système, logs et fichiers YAML à l'API Mistral et parse la réponse JSON structurée.
"""
import logging
import asyncio
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


def _normalize_parsed_result(res) -> dict:
    """Normalise n'importe quelle structure parsée en un dict {'issues': [dict, ...]} standard et sécurisé."""
    if not res:
        return {"issues": []}

    # 1. Si res est directement une liste
    if isinstance(res, list):
        normalized = []
        for item in res:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str) and item.strip():
                normalized.append({
                    "id": f"text_issue_{len(normalized) + 1}",
                    "title": item[:80],
                    "severity": "medium",
                    "category": "optimization",
                    "description": item,
                    "manual_fix": "Vérifier la configuration manuellement.",
                    "auto_fix_script": [],
                })
        return {"issues": normalized}

    # 2. Si res est un dictionnaire
    if isinstance(res, dict):
        raw_issues = None
        for key in ("issues", "anomalies", "erreurs", "errors", "problemes", "problems", "findings"):
            if key in res:
                raw_issues = res[key]
                break

        # Si aucune clé trouvée, mais que res est lui-même une anomalie unique
        if raw_issues is None and "id" in res:
            return {"issues": [res]}

        # Si aucune clé trouvée, chercher une valeur qui soit une liste ou un dict d'anomalies
        if raw_issues is None:
            for val in res.values():
                if isinstance(val, list) and val and isinstance(val[0], dict) and "id" in val[0]:
                    raw_issues = val
                    break
                elif isinstance(val, dict) and "id" in val:
                    raw_issues = [val]
                    break

        normalized_list = []
        if isinstance(raw_issues, list):
            for item in raw_issues:
                if isinstance(item, dict):
                    normalized_list.append(item)
                elif isinstance(item, str) and item.strip():
                    normalized_list.append({
                        "id": f"text_issue_{len(normalized_list) + 1}",
                        "title": item[:80],
                        "severity": "medium",
                        "category": "optimization",
                        "description": item,
                        "manual_fix": "Vérifier la configuration manuellement.",
                        "auto_fix_script": [],
                    })
        elif isinstance(raw_issues, dict):
            # Si "issues" est un dict unique : {"issues": {"id": "...", ...}}
            if "id" in raw_issues:
                normalized_list.append(raw_issues)
            else:
                # Ou un dict de dicts : {"issues": {"issue1": {...}, "issue2": {...}}}
                for item in raw_issues.values():
                    if isinstance(item, dict):
                        normalized_list.append(item)
        elif isinstance(raw_issues, str) and raw_issues.strip():
            normalized_list.append({
                "id": "text_issue_1",
                "title": raw_issues[:80],
                "severity": "medium",
                "category": "optimization",
                "description": raw_issues,
                "manual_fix": "Vérifier la configuration manuellement.",
                "auto_fix_script": [],
            })

        return {"issues": normalized_list}

    return {"issues": []}


def _extract_array_objects(text: str) -> list[str]:
    """Extrait chirurgicalement chaque bloc JSON {...} d'un tableau sans être perturbé par les accolades imbriquées."""
    idx_issues = text.find('"issues"')
    start_bracket = text.find("[", idx_issues if idx_issues != -1 else 0)
    if start_bracket == -1:
        start_bracket = text.find("[")
    if start_bracket == -1:
        return []

    blocks = []
    in_str = False
    esc = False
    depth = 0
    start_idx = -1

    for i in range(start_bracket + 1, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            if in_str:
                esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue

        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx != -1:
                    blocks.append(text[start_idx : i + 1])
                    start_idx = -1
        elif ch == "]" and depth == 0:
            break

    if depth > 0 and start_idx != -1:
        # Sauvetage du dernier bloc tronqué en cas de coupure inattendue
        blocks.append(text[start_idx:] + "}")

    return blocks


def _parse_issue_block(block: str) -> dict:
    """Parse un bloc d'anomalie unique de façon tolérante même en cas de guillemets mal échappés."""
    # 1. Tentative directe
    try:
        obj = json.loads(block, strict=False)
        if isinstance(obj, dict) and "id" in obj:
            return obj
    except Exception:
        pass

    # 2. Nettoyage des antislashs et trailing commas
    try:
        sanitized = re.sub(r'\\(?![/\"\\bfnrtu])', r'\\\\', block)
        no_trailing = re.sub(r",\s*([}\]])", r"\1", sanitized)
        obj = json.loads(no_trailing, strict=False)
        if isinstance(obj, dict) and "id" in obj:
            return obj
    except Exception:
        pass

    # 3. Extraction ciblée champ par champ pour récupérer l'anomalie intacte
    issue = {}
    for field in ["id", "severity", "category", "file"]:
        m = re.search(r'"' + field + r'"\s*:\s*"([^"]+)"', block)
        if m:
            issue[field] = m.group(1).strip()

    m_title = re.search(r'"title"\s*:\s*"(.*?)(?:",|"\s*\n|"\s*})', block)
    if m_title:
        issue["title"] = m_title.group(1).strip()
    else:
        m_title2 = re.search(r'"title"\s*:\s*"([^"]+)"', block)
        if m_title2:
            issue["title"] = m_title2.group(1).strip()

    m_script = re.search(r'"auto_fix_script"\s*:\s*(\[.*?\])', block, re.DOTALL)
    if m_script:
        try:
            issue["auto_fix_script"] = json.loads(m_script.group(1))
        except Exception:
            cleaned_s = re.sub(r",\s*([}\]])", r"\1", m_script.group(1))
            try:
                issue["auto_fix_script"] = json.loads(cleaned_s)
            except Exception:
                issue["auto_fix_script"] = []
    else:
        issue["auto_fix_script"] = []

    m_desc = re.search(
        r'"description"\s*:\s*"(.*?)(?=",\s*"|"\s*,\s*\n\s*"|"\s*,\s*"manual_fix"|"\s*,\s*"auto_fix_script")',
        block,
        re.DOTALL,
    )
    if m_desc:
        issue["description"] = m_desc.group(1).strip().replace('\\"', '"')
    else:
        m_desc2 = re.search(r'"description"\s*:\s*"(.*?)(?="manual_fix"|"auto_fix_script"|\}\s*$)', block, re.DOTALL)
        if m_desc2:
            issue["description"] = m_desc2.group(1).strip().rstrip(",").rstrip('"').strip()

    m_man = re.search(
        r'"manual_fix"\s*:\s*"(.*?)(?=",\s*"|"\s*,\s*\n\s*"|"\s*,\s*"auto_fix_script"|"\s*\n\s*"auto_fix_script")',
        block,
        re.DOTALL,
    )
    if m_man:
        issue["manual_fix"] = m_man.group(1).strip().replace('\\"', '"')
    else:
        m_man2 = re.search(r'"manual_fix"\s*:\s*"(.*?)(?="auto_fix_script"|\}\s*$)', block, re.DOTALL)
        if m_man2:
            issue["manual_fix"] = m_man2.group(1).strip().rstrip(",").rstrip('"').strip()

    if "id" in issue:
        return issue
    return {}


def _safe_json_loads(content: str) -> dict:
    """Nettoie et parse de manière ultra-robuste une réponse JSON de Mistral."""
    if not content:
        return {}

    # Suppression préventive des boucles de tabulations dégénératives
    cleaned = re.sub(r"[\t]{3,}", " ", content).strip()
    cleaned = re.sub(r"[\t\s]+$", "", cleaned)

    # 1. Tentative directe
    try:
        res = json.loads(cleaned, strict=False)
        norm = _normalize_parsed_result(res)
        if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
            return norm
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

    # 3. Extraction entre le premier délimiteur racine ("{" ou "[") et son correspondant final
    first_brace = cleaned.find("{")
    first_bracket = cleaned.find("[")

    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        last_bracket = cleaned.rfind("]")
        if last_bracket > first_bracket:
            candidate = cleaned[first_bracket : last_bracket + 1]
            try:
                res = json.loads(candidate, strict=False)
                norm = _normalize_parsed_result(res)
                if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
                    return norm
            except Exception:
                pass
        cleaned = cleaned[first_bracket:]
    elif first_brace != -1:
        last_brace = cleaned.rfind("}")
        if last_brace > first_brace:
            candidate = cleaned[first_brace : last_brace + 1]
            try:
                res = json.loads(candidate, strict=False)
                norm = _normalize_parsed_result(res)
                if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
                    return norm
            except Exception:
                pass
        cleaned = cleaned[first_brace:]

    # 4. Correction des antislashs non valides en JSON (ex: \s, \d, \w, regex, chemins)
    sanitized = re.sub(r'\\(?![/\"\\bfnrtu])', r'\\\\', cleaned)
    try:
        res = json.loads(sanitized, strict=False)
        norm = _normalize_parsed_result(res)
        if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
            return norm
    except Exception:
        pass

    # 5. Nettoyage des virgules orphelines (ex: [1, 2, ])
    no_trailing = re.sub(r",\s*([}\]])", r"\1", sanitized)
    try:
        res = json.loads(no_trailing, strict=False)
        norm = _normalize_parsed_result(res)
        if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
            return norm
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
        repaired += '"'

    repaired = re.sub(r',\s*"[^"]*"\s*:\s*$', "", repaired)
    repaired = re.sub(r',\s*"[^"]*"\s*$', "", repaired)
    repaired = re.sub(r',\s*([}\]])', r"\1", repaired)

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
        norm = _normalize_parsed_result(res)
        if isinstance(norm, dict) and "issues" in norm and isinstance(norm["issues"], list):
            _LOGGER.info("DomoLink-Mistral: Réponse JSON tronquée réparée avec succès.")
            return norm
    except Exception:
        pass

    # 7. Filet de sécurité résilient : extraction multi-blocs par équilibrage d'accolades
    blocks = _extract_array_objects(cleaned)
    parsed_issues = []
    for b in blocks:
        item = _parse_issue_block(b)
        if item and "id" in item:
            parsed_issues.append(item)

    if parsed_issues:
        _LOGGER.info("DomoLink-Mistral: %s anomalies extraites par parsing résilient multi-blocs.", len(parsed_issues))
        return {"issues": parsed_issues}

    # 8. Filet ultime : regex pour récupérer n'importe quel bloc isolé contenant "id"
    pattern = re.compile(r'\{[^{}]*"id"\s*:\s*"[^"]+"[^{}]*\}', re.DOTALL)
    for m in pattern.finditer(cleaned):
        item = _parse_issue_block(m.group(0))
        if item and "id" in item and item not in parsed_issues:
            parsed_issues.append(item)

    if parsed_issues:
        _LOGGER.info("DomoLink-Mistral: %s anomalies extraites via regex de secours.", len(parsed_issues))
        return {"issues": parsed_issues}

    # 9. En cas d'échec total, lever une erreur explicite avec le début de la réponse pour le débug
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

RÈGLE FONDAMENTALE SUR LES LIGNES COMMENTÉES (#) :
- Dans les configurations, templates, automatisations et fichiers YAML, TOUTE ligne ou bloc annoté ou précédé par un dièse '#' est un COMMENTAIRE ou du code volontairement désactivé par l'utilisateur.
- Tu ne dois JAMAIS considérer ces lignes comme actives.
- Ne signale AUCUNE anomalie, erreur de syntaxe, entité orpheline ou dépréciation portant sur une ligne ou un bloc commenté avec '#'. Ignore-les intégralement lors de ton analyse.

Tu réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après."""

USER_PROMPT_TEMPLATE = """Tu es l'auditeur expert de Home Assistant.
Analyse le rapport technique ci-dessous et retourne la liste COMPLÈTE de TOUTES les anomalies détectées dans un objet JSON avec cette structure exacte :
{{
  "issues": [
    {{
      "id": "identifiant_stable_sans_espace",
      "severity": "high|medium|low",
      "category": "yaml_syntax|esphome|blueprint|automation|script|integration|entity|log_error|optimization",
      "title": "Titre court et clair du problème",
      "description": "Explication directe en 1-2 phrases : quel composant/fichier est en cause et quel est l'impact.",
      "manual_fix": "Instructions pas-à-pas concises en 2 à 4 étapes claires. Ne recopie JAMAIS de gros fichiers complets pour ne pas saturer la réponse.",
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

RÈGLES D'AUDIT CRUCIALES :
1. COUVERTURE EXHAUSTIVE DE TOUTES LES SECTIONS DU RAPPORT :
   Tu DOIS inspecter chaque section du rapport et extraire TOUS les problèmes réels :
   - Fichiers YAML & syntaxe (ex: blocs sensors invalides, clés manquantes)
   - ESPHome Builder (ex: plateformes dépréciées 'dallas', 'captive_portal' absent)
   - Erreurs et avertissements des logs et de system_log (ex: notify file, unique_id dupliqués, template warnings, erreurs de traces)
   - Intégrations en erreur ou en attente
   - Entités indisponibles ou inconnues (regroupe les entités d'un même équipement déconnecté en une anomalie dédiée)
   - Automations et scripts (automations désactivées par inadvertance ou jamais exécutées)
   Ne te limite JAMAIS à la première catégorie trouvée (ex: ne t'arrête pas au YAML) ! Rapporte TOUTES les anomalies détectées dans le tableau "issues" (il y a généralement entre 25 et 35 anomalies réelles dans ce rapport complet). Ne regroupe pas toutes les anomalies en 1 seul titre vague : détaille chaque anomalie distinctement.

2. CONCISION STRICTE ET SÉCURITÉ DE SYNTAXE :
   - Pour chaque anomalie, "description" doit faire 1 seule phrase courte et directe.
   - "manual_fix" doit être UNE SEULE CHAÎNE DE TEXTE concise en français (1 ou 2 étapes en texte brut, JAMAIS un tableau).
   - RÈGLE ABSOLUE ANTI-CORRUPTION JSON : N'INCLUS JAMAIS DE GUILLEMETS DOUBLES (") DANS LES VALEURS DE TEXTE ("title", "description", "manual_fix"). Si tu dois citer un nom ou une entité, utilise EXCLUSIVEMENT des apostrophes simples '...'.
   - INTERDICTION STRICTE d'écrire des blocs de code, des exemples syntaxiques YAML complets avec accolades ou des caractères spéciaux dans "manual_fix". Reste en texte explicatif pur.
   - N'utilise AUCUN caractère de tabulation (\t).

3. GRANULARITÉ STRICTE (pour des résultats reproductibles d'un audit à l'autre) :
   - UNE seule anomalie par cause racine ou par composant/intégration, JAMAIS une anomalie par entité, par automation ou par ligne de log.
   - Toutes les automations désactivées = 1 seule anomalie (liste leurs noms dans la description). Idem pour les automations jamais déclenchées.
   - Toutes les entités indisponibles ou inconnues = 1 anomalie par équipement/intégration concerné (maximum), jamais une par entité.
   - Toutes les dépréciations/avertissements d'une même intégration (ex: Zigbee/ZHA, Xiaomi MiOT) = 1 seule anomalie.
   - Les ID dupliqués d'une même catégorie (groupes, input_text, boutons MQTT) = 1 anomalie par type.

4. DÉTERMINISME ET REPRODUCTIBILITÉ :
   - Base ton analyse rigoureusement sur les faits concrets du rapport sans spéculer.
   - Génère des 'id' uniques, stables et standardisés (ex: 'yaml_syntax_configuration_yaml_sensors_invalid', 'esphome_dallas_deprecated', 'log_error_notify_file_failed').
   - IGNORER STRICTEMENT LES LIGNES COMMENTÉES (#) : Tout élément précédé d'un '#' ne doit JAMAIS générer d'anomalie.
   - IMPORTANT JSON : Pour citer des termes ou entités dans les textes, utilise UNIQUEMENT des apostrophes simples '...' et JAMAIS de guillemets doubles non échappés.

Voici le rapport technique complet de l'instance Home Assistant :
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


async def _analyze_single(
    hass: HomeAssistant, api_key: str, model: str, logs: str, save_report: bool = True
) -> dict:
    """Envoie UN lot de données à Mistral et retourne un dictionnaire JSON."""
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
            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length":
                _LOGGER.warning(
                    "DomoLink-Mistral: La réponse de Mistral AI a atteint la limite max_tokens (finish_reason=length). "
                    "Certaines anomalies peuvent avoir été tronquées."
                )
            content = choice["message"]["content"]
            result = _safe_json_loads(content)

            if not isinstance(result, dict):
                result = {"issues": []}
            elif "issues" not in result or not isinstance(result.get("issues"), list):
                result["issues"] = []

            # Garantir strictement que chaque élément de issues est un dictionnaire
            result["issues"] = [i for i in result["issues"] if isinstance(i, dict)]
            result["success"] = True

            # Sauvegarde automatique du rapport JSON et de la réponse brute dans /config/
            try:
                if not save_report:
                    raise _SkipSave()
                def _save_reports():
                    import json, os
                    cfg = hass.config.config_dir
                    report_path = os.path.join(cfg, "domolink_mistral_latest_analysis.json")
                    with open(report_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                    raw_path = os.path.join(cfg, "domolink_mistral_raw_response.json")
                    with open(raw_path, "w", encoding="utf-8") as f:
                        f.write(content)

                await hass.async_add_executor_job(_save_reports)
                _LOGGER.info("DomoLink-Mistral: Rapport JSON sauvegardé dans domolink_mistral_latest_analysis.json")
            except _SkipSave:
                pass
            except Exception as save_err:
                _LOGGER.warning("DomoLink-Mistral: Erreur écriture sauvegarde rapport JSON: %s", save_err)

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


class _SkipSave(Exception):
    """Signal interne : ne pas écrire le rapport pour un lot intermédiaire."""


_SECTION_SEPARATOR = "\n\n" + "═" * 60 + "\n\n"
MAX_BATCH_CHARS = 100000
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _split_report_in_batches(logs: str, max_chars: int = MAX_BATCH_CHARS) -> list[str]:
    """Regroupe les sections du rapport en lots de taille raisonnable.

    Un seul gros prompt fait varier fortement le nombre d'anomalies renvoyées (le modèle
    s'arrête quand son budget de sortie est consommé). Plusieurs lots courts sont beaucoup
    plus reproductibles : chaque lot a tout son budget de sortie pour lui.
    """
    sections = [sec for sec in logs.split(_SECTION_SEPARATOR) if sec.strip()]
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for sec in sections:
        if current and size + len(sec) > max_chars:
            batches.append(_SECTION_SEPARATOR.join(current))
            current, size = [], 0
        current.append(sec)
        size += len(sec)
    if current:
        batches.append(_SECTION_SEPARATOR.join(current))
    return batches or [logs]


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.sub(r"[^\w]+", " ", str(title).lower()).split() if len(t) > 3}


def _merge_similar(issues: list[dict]) -> list[dict]:
    """Fusionne les anomalies quasi identiques (même catégorie, titres très proches)."""
    kept: list[dict] = []
    for issue in issues:
        tokens = _title_tokens(issue.get("title", ""))
        duplicate = False
        for other in kept:
            if other.get("category") != issue.get("category"):
                continue
            ot = _title_tokens(other.get("title", ""))
            if tokens and ot and len(tokens & ot) / len(tokens | ot) >= 0.6:
                duplicate = True
                break
        if not duplicate:
            kept.append(issue)
    return kept


def _merge_issues(results: list[dict]) -> list[dict]:
    """Fusionne les anomalies de tous les lots, sans doublon (id ou titre identique)."""
    merged: list[dict] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    for res in results:
        for issue in res.get("issues", []):
            iid = str(issue.get("id", "")).strip().lower()
            title = re.sub(r"\W+", " ", str(issue.get("title", "")).lower()).strip()
            if (iid and iid in seen_ids) or (title and title in seen_titles):
                continue
            if iid:
                seen_ids.add(iid)
            if title:
                seen_titles.add(title)
            merged.append(issue)
    merged = _merge_similar(merged)
    merged.sort(key=lambda i: _SEVERITY_ORDER.get(str(i.get("severity", "medium")).lower(), 1))
    return merged


async def analyze_with_mistral(
    hass: HomeAssistant, api_key: str, model: str, logs: str
) -> dict:
    """Analyse le rapport complet en plusieurs lots indépendants puis fusionne les résultats."""
    batches = _split_report_in_batches(logs)
    if len(batches) == 1:
        return await _analyze_single(hass, api_key, model, batches[0], save_report=True)

    total = len(batches)
    _LOGGER.info("DomoLink-Mistral: Rapport découpé en %s lots (%s caractères).", total, len(logs))

    def _wrap(i: int, text: str) -> str:
        return (
            f"[LOT {i}/{total} DU RAPPORT — ne signale que les anomalies présentes dans ce lot ; "
            f"les autres lots sont analysés séparément]\n\n{text}"
        )

    results = await asyncio.gather(
        *[
            _analyze_single(hass, api_key, model, _wrap(i + 1, b), save_report=False)
            for i, b in enumerate(batches)
        ],
        return_exceptions=True,
    )

    ok: list[dict] = []
    first_error: dict | None = None
    for r in results:
        if isinstance(r, dict) and r.get("success", True) and not r.get("error"):
            ok.append(r)
        elif isinstance(r, dict) and first_error is None:
            first_error = r
        elif isinstance(r, Exception) and first_error is None:
            first_error = {"success": False, "error": f"❌ {r}", "error_type": "unknown", "issues": []}

    if not ok:
        return first_error or {"success": False, "error": "Analyse impossible.", "error_type": "unknown", "issues": []}
    if first_error:
        _LOGGER.warning(
            "DomoLink-Mistral: %s lot(s) sur %s en échec (%s) — résultats partiels conservés.",
            total - len(ok), total, first_error.get("error"),
        )

    result = {"success": True, "issues": _merge_issues(ok)}
    if first_error:
        result["partial"] = True

    try:
        def _save():
            import os
            with open(os.path.join(hass.config.config_dir, "domolink_mistral_latest_analysis.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        await hass.async_add_executor_job(_save)
    except Exception as err:
        _LOGGER.warning("DomoLink-Mistral: Erreur écriture rapport JSON: %s", err)
    return result


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



