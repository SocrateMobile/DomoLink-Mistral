"""Module d'analyse avancée pour DomoLink-Mistral.

Responsabilités :
- Lecture optimisée des logs (homeassistant.log + system_log)
- Analyse approfondie des fichiers YAML :
  * configuration.yaml et tous ses !include (!include, !include_dir_list, etc.)
  * automations.yaml, scripts.yaml, scenes.yaml
  * Blueprints (blueprints/automation, blueprints/script)
  * Périphériques ESPHome Builder (esphome/*.yaml)
- Validation de la syntaxe YAML et détection des erreurs de formatage
- Détection des entités orphelines / manquantes référencées dans les configs
- Inspection des intégrations, automations et scripts actifs
- Nettoyage rigoureux des données sensibles (mots de passe, tokens, secrets)
"""
import os
import re
import glob
import logging
from collections import deque

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── Expressions régulières pour détecter et masquer les données sensibles ──
SENSITIVE_PATTERNS = [
    # Mots de passe, clés API, secrets, tokens, identifiants WiFi, clés ESPHome
    (
        re.compile(
            r'(?i)((?:password|passwd|secret|api_key|api\.key|access_token|'
            r'client_secret|private_key|bearer|wifi_password|auth_token|pin_code|'
            r'encryption_key|noise_psk|ota_password|wifi_psk|ssid|ap_password)[\s:="\']+)[^\r\n,;\'"]+',
        ),
        r"\1[REDACTED]",
    ),
    # Clés de chiffrement ESPHome / Noise PSK (ex: 32 bytes base64 = 44 chars)
    (
        re.compile(r'(?i)(key:\s*["\']?)[A-Za-z0-9+/]{43}=?["\']?'),
        r"\1[KEY_REDACTED]",
    ),
    # URLs avec credentials intégrées (user:pass@host)
    (re.compile(r"://[^:\s]+:[^@\s]+@"), "://[CREDENTIALS]@"),
    # Webhooks Home Assistant
    (re.compile(r'/api/webhook/[a-zA-Z0-9_-]+'), "/api/webhook/[REDACTED]"),
    # Tokens bot Telegram (ex: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ)
    (re.compile(r"\b\d{9,10}:[a-zA-Z0-9_-]{35}\b"), "[TELEGRAM_TOKEN_REMOVED]"),
    # Adresses email
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[EMAIL_REDACTED]",
    ),
    # Adresses IPv4 valides
    (
        re.compile(r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"),
        "[IP_REDACTED]",
    ),
    # Adresses MAC réseau
    (
        re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
        "[MAC_REDACTED]",
    ),
    # Coordonnées GPS format texte (latitude, longitude avec au moins 4 décimales)
    (
        re.compile(r"\b-?\d{1,2}\.\d{4,8}\s*,\s*-?\d{1,3}\.\d{4,8}\b"),
        "[GPS_REDACTED]",
    ),
    # Coordonnées GPS au format JSON ("latitude": 48.8566)
    (
        re.compile(r'(?i)("(?:latitude|longitude|lat|lon|lng)"\s*:\s*)[-+]?\d+(?:\.\d+)?'),
        r'\1"[COORDINATE_REDACTED]"',
    ),
    # Tokens longs type JWT (xxx.yyy.zzz)
    (
        re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
        "[JWT_TOKEN_REMOVED]",
    ),
    # Clés API préfixées connues (Mistral, OpenAI, GitHub, Anthropic, GitLab, etc.)
    (
        re.compile(r"\b(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|glpat-[a-zA-Z0-9_-]{20,})\b"),
        "[API_KEY_REMOVED]",
    ),
]


def sanitize_logs(log_content: str) -> str:
    """Nettoie le contenu en masquant toutes les informations sensibles."""
    sanitized = log_content
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ═══════════════════════════════════════════════════════
# SECTION 1 : Extraction des logs
# ═══════════════════════════════════════════════════════

async def _get_file_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Lit les dernières lignes du journal Home Assistant (home-assistant.log)."""
    candidates = [
        hass.config.path("home-assistant.log"),
        hass.config.path("homeassistant.log"),
        hass.config.path("home-assistant.log.1"),
    ]
    log_file = None
    for c in candidates:
        if os.path.exists(c):
            log_file = c
            break

    if not log_file:
        _LOGGER.debug("DomoLink-Mistral: Aucun fichier de log Home Assistant trouvé sur le disque.")
        return ""

    try:
        def read_tail():
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                # Filtrer les logs générés par DomoLink-Mistral lui-même afin d'éviter qu'un scan précédent
                # ne décale la fenêtre des derniers logs et ne produise des résultats différents au scan suivant.
                filtered = [
                    line for line in f
                    if "domolink_mistral" not in line.lower() and "domolink-mistral" not in line.lower()
                ]
                return "".join(filtered[-lines:])

        content = await hass.async_add_executor_job(read_tail)
        if content:
            _LOGGER.debug("DomoLink-Mistral: %s lignes lues depuis %s", lines, os.path.basename(log_file))
            return content
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lecture %s: %s", log_file, e)
    return ""


async def _get_system_log(hass: HomeAssistant) -> str:
    """Récupère les entrées structurées du system_log HA."""
    try:
        system_log = hass.data.get("system_log")
        if not system_log or not hasattr(system_log, "records"):
            return ""

        records = system_log.records
        if not records:
            return ""

        if isinstance(records, dict) or hasattr(records, "values"):
            records_list = list(records.values())
        else:
            try:
                records_list = list(records)
            except Exception:
                records_list = []

        if not records_list:
            return ""

        entries = []
        for record in records_list[-50:]:
            if isinstance(record, dict):
                level = record.get("level", "UNKNOWN")
                name = record.get("name", "")
                message = record.get("message", "")
                exc = record.get("exception", "")
                count = record.get("count", 1)
            else:
                level = getattr(record, "level", "UNKNOWN")
                name = getattr(record, "name", "")
                message = getattr(record, "message", "")
                exc = getattr(record, "exception", "")
                count = getattr(record, "count", 1)

            # Ignorer les propres logs de domolink pour garantir la reproductibilité
            if "domolink_mistral" in str(name).lower() or "domolink" in str(name).lower():
                continue

            if isinstance(message, list):
                message = " ".join(str(m) for m in message)

            entry = f"[{level}] (x{count}) {name}: {message}"
            if exc:
                entry += f"\n  Exception: {exc}"
            entries.append(entry)

        if entries:
            _LOGGER.debug("DomoLink-Mistral: %s entrées system_log récupérées", len(entries))
            return "\n\n".join(entries)
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lecture system_log: %s", e)
    return ""


# ═══════════════════════════════════════════════════════
# SECTION 2 : Analyse des fichiers YAML et des !include
# ═══════════════════════════════════════════════════════

def _check_yaml_syntax_and_read(file_path: str, max_lines: int = 150) -> dict:
    """Vérifie la syntaxe YAML d'un fichier et extrait son contenu sécurisé."""
    result = {
        "file": os.path.basename(file_path),
        "path": file_path,
        "valid": True,
        "error": None,
        "content_excerpt": "",
        "lines_count": 0,
    }

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            result["lines_count"] = len(lines)
            content = "".join(lines)

        # Vérification de syntaxe avec PyYAML si disponible
        try:
            import yaml

            class _HaSafeLoader(yaml.SafeLoader):
                pass

            # Gestionnaire pour toutes les balises custom Home Assistant / ESPHome (!include, !secret, !lambda, etc.)
            def _dummy_constructor(loader, tag_suffix, node):
                if isinstance(node, yaml.ScalarNode):
                    return loader.construct_scalar(node)
                elif isinstance(node, yaml.SequenceNode):
                    return loader.construct_sequence(node)
                elif isinstance(node, yaml.MappingNode):
                    return loader.construct_mapping(node)
                return None

            _HaSafeLoader.add_multi_constructor("!", _dummy_constructor)

            yaml.load(content, Loader=_HaSafeLoader)
        except Exception as yaml_err:
            result["valid"] = False
            result["error"] = str(yaml_err)

        # Préparer un extrait sécurisé (premières lignes)
        excerpt_lines = lines[:max_lines]
        result["content_excerpt"] = "".join(excerpt_lines)
        if len(lines) > max_lines:
            result["content_excerpt"] += f"\n... [{len(lines) - max_lines} lignes supplémentaires non affichées]"

    except FileNotFoundError:
        result["valid"] = False
        result["error"] = "Fichier introuvable"
    except Exception as e:
        result["valid"] = False
        result["error"] = f"Erreur de lecture: {e}"

    return result


def _find_includes_in_yaml(content: str) -> list[str]:
    """Extrait tous les fichiers et dossiers référencés par des balises !include non commentées."""
    includes = []
    # Match !include <path>, !include_dir_list <path>, !include_dir_named <path>, etc.
    pattern = re.compile(r"!include(?:_dir_list|_dir_named|_dir_merge_list|_dir_merge_named)?\s+([^\s\n#]+)")
    for line in content.splitlines():
        clean_line = line.strip()
        if clean_line.startswith("#"):
            continue
        line_clean = line.split("#")[0]
        for match in pattern.finditer(line_clean):
            inc_path = match.group(1).strip("'\"")
            if inc_path and inc_path not in includes:
                includes.append(inc_path)
    return includes


async def _analyze_all_yaml_files(hass: HomeAssistant) -> str:
    """Analyse configuration.yaml, tous ses includes, automations, scripts, scenes, blueprints et ESPHome."""
    config_dir = hass.config.config_dir
    all_findings = []
    discovered_files = set()
    yaml_syntax_errors = []

    def _collect_yaml_data():
        nonlocal all_findings, discovered_files, yaml_syntax_errors
        findings = []
        yaml_excerpts = []

        # ── 1. configuration.yaml et includes récursifs ──
        config_yaml_path = os.path.join(config_dir, "configuration.yaml")
        queue = [config_yaml_path]

        # Ajouter aussi les fichiers standards s'ils existent
        for std_name in ["automations.yaml", "automation.yaml", "scripts.yaml", "script.yaml", "scenes.yaml", "scene.yaml"]:
            p = os.path.join(config_dir, std_name)
            if os.path.exists(p) and p not in queue:
                queue.append(p)

        while queue:
            current_path = queue.pop(0)
            if current_path in discovered_files:
                continue
            discovered_files.add(current_path)

            if os.path.isdir(current_path):
                # Dossier inclus via !include_dir_*
                for yaml_file in sorted(glob.glob(os.path.join(current_path, "**", "*.yaml"), recursive=True)):
                    if yaml_file not in discovered_files:
                        queue.append(yaml_file)
                continue

            if not os.path.exists(current_path):
                findings.append(f"❌ FICHIER INCLUS INTROUVABLE : {os.path.relpath(current_path, config_dir)}")
                continue

            # Ne pas exposer le contenu direct de secrets.yaml (juste valider sa syntaxe)
            is_secrets = os.path.basename(current_path) == "secrets.yaml"
            res = _check_yaml_syntax_and_read(current_path, max_lines=50 if is_secrets else 120)

            rel_path = os.path.relpath(current_path, config_dir)
            if not res["valid"]:
                yaml_syntax_errors.append(f"🔴 ERREUR SYNTAXE YAML dans {rel_path} :\n  {res['error']}")
                findings.append(f"🔴 [ERREUR SYNTAXE] {rel_path} :\n  {res['error']}")
            else:
                findings.append(f"📄 {rel_path} ({res['lines_count']} lignes) - Syntaxe OK")

            # BUG-MAJ-04 FIX: Transmettre un extrait assaini des fichiers fonctionnels clés (automations, scripts, configuration)
            base_filename = os.path.basename(current_path)
            if not is_secrets and base_filename in ("automations.yaml", "automation.yaml", "scripts.yaml", "script.yaml", "configuration.yaml"):
                excerpt = res.get("content_excerpt", "").strip()
                if excerpt:
                    yaml_excerpts.append(f"--- Fichier: {rel_path} ---\n{excerpt}")

            # Chercher les includes imbriqués
            if res.get("content_excerpt") and not is_secrets:
                nested = _find_includes_in_yaml(res["content_excerpt"])
                for n in nested:
                    target = os.path.normpath(os.path.join(os.path.dirname(current_path), n))
                    if target not in discovered_files and target.startswith(config_dir):
                        queue.append(target)

        # ── 2. Blueprints ──
        blueprints_dir = os.path.join(config_dir, "blueprints")
        if os.path.exists(blueprints_dir):
            bp_files = sorted(glob.glob(os.path.join(blueprints_dir, "**", "*.yaml"), recursive=True))
            for bp_path in bp_files:
                discovered_files.add(bp_path)
                rel_bp = os.path.relpath(bp_path, config_dir)
                bp_res = _check_yaml_syntax_and_read(bp_path, max_lines=60)
                if not bp_res["valid"]:
                    yaml_syntax_errors.append(f"🔴 ERREUR SYNTAXE BLUEPRINT dans {rel_bp} :\n  {bp_res['error']}")
                    findings.append(f"🔴 [BLUEPRINT ERREUR] {rel_bp} :\n  {bp_res['error']}")
                else:
                    findings.append(f"📘 Blueprint: {rel_bp} - Syntaxe OK")

        # ── 3. ESPHome Builder configs (esphome/*.yaml) ──
        esphome_dir = os.path.join(config_dir, "esphome")
        esphome_devices = []
        if os.path.exists(esphome_dir):
            esp_files = sorted(glob.glob(os.path.join(esphome_dir, "*.yaml")))
            for esp_path in esp_files:
                # Ignorer les fichiers internes esphome
                if os.path.basename(esp_path).startswith("."):
                    continue
                discovered_files.add(esp_path)
                rel_esp = os.path.relpath(esp_path, config_dir)
                esp_res = _check_yaml_syntax_and_read(esp_path, max_lines=80)
                
                if not esp_res["valid"]:
                    yaml_syntax_errors.append(f"🔴 ERREUR SYNTAXE ESPHOME dans {rel_esp} :\n  {esp_res['error']}")
                    esphome_devices.append(f"🔴 [ESPHOME ERREUR] {rel_esp} :\n  {esp_res['error']}")
                else:
                    # Analyse sémantique rapide ESPHome (en ignorant les lignes commentées avec #)
                    content = esp_res.get("content_excerpt", "")
                    active_lines = [
                        line.strip() for line in content.splitlines()
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    active_content = "\n".join(active_lines)
                    esp_name = re.search(r"name:\s*([a-zA-Z0-9_-]+)", active_content)
                    dev_name = esp_name.group(1) if esp_name else os.path.splitext(os.path.basename(esp_path))[0]
                    
                    notes = []
                    if any("dallas:" in l for l in active_lines):
                        notes.append("⚠️ Utilise la plateforme dépréciée 'dallas' (remplacée par 'one_wire')")
                    if not any("captive_portal:" in l for l in active_lines) and any("wifi:" in l for l in active_lines):
                        notes.append("ℹ️ Pas de 'captive_portal:' en cas de perte WiFi")

                    status_str = f" ({', '.join(notes)})" if notes else " (OK)"
                    esphome_devices.append(f"⚡ ESPHome Device '{dev_name}' ({rel_esp}){status_str}")

        return findings, esphome_devices, yaml_syntax_errors, yaml_excerpts

    try:
        findings, esphome_devices, syntax_errors, excerpts = await hass.async_add_executor_job(_collect_yaml_data)

        report = []
        if syntax_errors:
            report.append("=== ERREURS DE SYNTAXE YAML DÉTECTÉES ===")
            report.extend(syntax_errors)
            report.append("")

        report.append(f"=== FICHIERS YAML ANALYSÉS ({len(discovered_files)} fichiers) ===")
        report.extend(findings[:50])
        if len(findings) > 50:
            report.append(f"  ... et {len(findings) - 50} autres fichiers analysés")

        if excerpts:
            report.append("\n=== EXTRAITS DE CODE YAML POUR ANALYSE SÉMANTIQUE ===")
            report.extend(excerpts)

        if esphome_devices:
            report.append("\n=== PÉRIPHÉRIQUES ESPHOME BUILDER ===")
            report.extend(esphome_devices)

        return "\n".join(report)

    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur analyse YAML: %s", e)
        return f"Erreur lors de l'analyse YAML: {e}"


# ═══════════════════════════════════════════════════════
# SECTION 3 : Inspection des automations et scripts
# ═══════════════════════════════════════════════════════

async def _get_automations_report(hass: HomeAssistant) -> str:
    """Inspecte toutes les automations et génère un rapport."""
    raw_states = hass.states.async_all("automation")
    if not raw_states:
        return ""

    # Tri par entity_id pour garantir la reproductibilité entre deux scans
    states = sorted(raw_states, key=lambda s: s.entity_id)

    total = len(states)
    disabled = 0
    problems = []

    for state in states:
        entity_id = state.entity_id
        attrs = state.attributes
        friendly_name = attrs.get("friendly_name", entity_id)
        current_state = state.state
        last_triggered = attrs.get("last_triggered")
        mode = attrs.get("mode", "single")

        if current_state == "off":
            disabled += 1
            problems.append(f"  ⚠️ DÉSACTIVÉE: '{friendly_name}' ({entity_id}) — Mode: {mode}")

        if last_triggered is None and current_state == "on":
            problems.append(f"  ℹ️ JAMAIS DÉCLENCHÉE: '{friendly_name}' ({entity_id}) — Vérifier triggers")

    summary = f"Total: {total} automations, {disabled} désactivée(s), {len(problems)} anomalie(s)"
    result = [summary]
    result.extend(problems[:40])
    return "\n".join(result)


async def _get_scripts_report(hass: HomeAssistant) -> str:
    """Inspecte tous les scripts."""
    raw_states = hass.states.async_all("script")
    if not raw_states:
        return ""

    # Tri par entity_id pour un résultat stable
    states = sorted(raw_states, key=lambda s: s.entity_id)

    total = len(states)
    problems = []
    for state in states:
        entity_id = state.entity_id
        attrs = state.attributes
        friendly_name = attrs.get("friendly_name", entity_id)
        if state.state == "on":
            problems.append(f"  🔄 EN COURS: '{friendly_name}' ({entity_id})")

    summary = f"Total: {total} scripts, {len(problems)} en cours d'exécution"
    result = [summary]
    result.extend(problems)
    return "\n".join(result)


# ═══════════════════════════════════════════════════════
# SECTION 4 : Entités indisponibles et intégrations
# ═══════════════════════════════════════════════════════

async def _get_unavailable_entities(hass: HomeAssistant) -> str:
    """Détecte les entités en état 'unavailable' ou 'unknown'."""
    raw_states = hass.states.async_all()
    # Tri stable par entity_id
    all_states = sorted(raw_states, key=lambda s: s.entity_id)
    unavailable = []
    unknown = []

    for state in all_states:
        entity_id = state.entity_id
        if entity_id.startswith(("persistent_notification.", "zone.", "sun.", "weather.")):
            continue

        if state.state == "unavailable":
            friendly = state.attributes.get("friendly_name", entity_id)
            unavailable.append(f"  🔴 {friendly} ({entity_id})")
        elif state.state == "unknown":
            friendly = state.attributes.get("friendly_name", entity_id)
            unknown.append(f"  🟡 {friendly} ({entity_id})")

    if not unavailable and not unknown:
        return "Toutes les entités sont disponibles."

    lines = [f"Entités indisponibles: {len(unavailable)}, en état inconnu: {len(unknown)}"]
    if unavailable:
        lines.append("--- Indisponibles ---")
        lines.extend(unavailable[:25])
    if unknown:
        lines.append("--- État inconnu ---")
        lines.extend(unknown[:15])

    return "\n".join(lines)


async def _get_integration_issues(hass: HomeAssistant) -> str:
    """Vérifie l'état des intégrations configurées."""
    try:
        from homeassistant.config_entries import ConfigEntryState
        error_states = {ConfigEntryState.SETUP_ERROR, ConfigEntryState.MIGRATION_ERROR}
        retry_states = {ConfigEntryState.SETUP_RETRY, ConfigEntryState.NOT_LOADED}
    except Exception:
        error_states = set()
        retry_states = set()

    raw_entries = hass.config_entries.async_entries()
    # Tri stable par domaine et titre
    entries = sorted(raw_entries, key=lambda e: (getattr(e, "domain", ""), getattr(e, "title", "")))
    failed = []
    not_loaded = []

    for entry in entries:
        if getattr(entry, "disabled_by", None):
            continue  # Ne pas signaler les intégrations volontairement désactivées par l'utilisateur

        state = getattr(entry, "state", None)
        state_str = str(state)
        state_lower = state_str.lower()

        if state in error_states or "error" in state_lower or "failed" in state_lower:
            failed.append(f"  🔴 {entry.title} ({entry.domain}) — État: {state_str}")
        elif state in retry_states or "not_loaded" in state_lower or "retry" in state_lower:
            not_loaded.append(f"  🟡 {entry.title} ({entry.domain}) — État: {state_str}")

    if not failed and not not_loaded:
        return "Toutes les intégrations sont chargées correctement."

    lines = [f"Intégrations en erreur: {len(failed)}, en attente: {len(not_loaded)}"]
    lines.extend(failed)
    lines.extend(not_loaded)
    return "\n".join(lines)


async def _get_system_info(hass: HomeAssistant) -> str:
    """Collecte les infos système de base."""
    lines = []
    try:
        lines.append(f"Version Home Assistant: {hass.config.version}")
        lines.append(f"Fuseau horaire: {hass.config.time_zone}")
        lines.append(f"Composants chargés: {len(hass.config.components)}")
        lines.append(f"Entités totales: {len(hass.states.async_all())}")
        lines.append(f"Intégrations configurées: {len(hass.config_entries.async_entries())}")
    except Exception as e:
        _LOGGER.debug("DomoLink-Mistral: Erreur info système: %s", e)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# SECTION X : Analyse des traces d'automatisation
# ═══════════════════════════════════════════════════════

async def _get_automation_traces(hass: HomeAssistant) -> str:
    """Récupère les dernières traces d'automatisations en erreur."""
    import json
    import os
    trace_file = hass.config.path(".storage", "trace.saved_traces")
    if not os.path.exists(trace_file):
        return ""
    try:
        def read_traces():
            with open(trace_file, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                if "data" in data and isinstance(data["data"], dict):
                    traces = []
                    for auto_id, run_list in sorted(data["data"].items(), key=lambda item: str(item[0])):
                        for run in run_list:
                            traces.append(run)
                    def _get_ts(r):
                        try:
                            return r.get("timestamp", {}).get("start", "")
                        except Exception:
                            return ""
                    traces.sort(key=_get_ts)
                    return "\n\n".join(json.dumps(t) for t in traces[-5:])
            return ""
            
        traces_str = await hass.async_add_executor_job(read_traces)
        if traces_str:
            return traces_str
    except Exception as e:
        _LOGGER.debug("DomoLink-Mistral: Erreur lecture des traces d'automatisations: %s", e)
    return ""

async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Collecte complète de l'état du système HA, des fichiers YAML et des logs pour Mistral."""
    sections = []

    # 1. Infos système
    _LOGGER.info("DomoLink-Mistral: [1/9] Collecte des informations système...")
    sys_info = await _get_system_info(hass)
    if sys_info:
        sections.append(f"=== INFORMATIONS SYSTÈME ===\n{sys_info}")

    # 2. Analyse complète des fichiers YAML (configuration.yaml, !include, automations, scripts, blueprints, esphome)
    _LOGGER.info("DomoLink-Mistral: [2/9] Analyse de configuration.yaml, des !include, blueprints et ESPHome...")
    yaml_report = await _analyze_all_yaml_files(hass)
    if yaml_report:
        sections.append(yaml_report)

    # 3. Logs fichier
    _LOGGER.info("DomoLink-Mistral: [3/9] Lecture de homeassistant.log...")
    file_logs = await _get_file_logs(hass, lines)
    if file_logs:
        sections.append(f"=== HOMEASSISTANT.LOG (dernières {lines} lignes) ===\n{file_logs}")

    # 4. System log structuré
    _LOGGER.info("DomoLink-Mistral: [4/9] Lecture du system_log structuré...")
    sys_log = await _get_system_log(hass)
    if sys_log:
        sections.append(f"=== SYSTEM_LOG (entrées structurées) ===\n{sys_log}")

    # 5. Intégrations en erreur
    _LOGGER.info("DomoLink-Mistral: [5/9] Vérification des intégrations...")
    integrations = await _get_integration_issues(hass)
    if integrations:
        sections.append(f"=== ÉTAT DES INTÉGRATIONS ===\n{integrations}")

    # 6. Entités indisponibles
    _LOGGER.info("DomoLink-Mistral: [6/9] Détection des entités indisponibles...")
    entities = await _get_unavailable_entities(hass)
    if entities:
        sections.append(f"=== ENTITÉS INDISPONIBLES ===\n{entities}")

    # 7. Automations
    _LOGGER.info("DomoLink-Mistral: [7/9] Analyse des automations...")
    automations = await _get_automations_report(hass)
    if automations:
        sections.append(f"=== AUTOMATIONS ===\n{automations}")

    # 8. Scripts
    _LOGGER.info("DomoLink-Mistral: [8/9] Analyse des scripts...")
    scripts = await _get_scripts_report(hass)
    if scripts:
        sections.append(f"=== SCRIPTS ===\n{scripts}")


    # 9. Traces d'automatisations
    _LOGGER.info("DomoLink-Mistral: [9/9] Analyse des traces...")
    traces = await _get_automation_traces(hass)
    if traces:
        sections.append(f"=== TRACES D'AUTOMATISATIONS (Récentes) ===\n{traces}")

    if not sections:

        _LOGGER.warning("DomoLink-Mistral: Aucune donnée collectée.")
        return ""

    separator = "\n\n" + "═" * 60 + "\n\n"
    combined = separator.join(sections)
    _LOGGER.info(
        "DomoLink-Mistral: Collecte terminée — %s sections, %s caractères au total.",
        len(sections), len(combined),
    )

    return sanitize_logs(combined)
