"""Module d'analyse avancée pour DomoLink-Mistral.

Responsabilités :
- Lecture optimisée des dernières lignes du fichier homeassistant.log
- Récupération des erreurs structurées du composant system_log
- Inspection des automations, scripts, scènes et blueprints
- Détection des entités indisponibles référencées dans les configs
- Nettoyage des données sensibles avant envoi à Mistral
"""
import re
import logging
from collections import deque

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── Expressions régulières pour détecter et masquer les données sensibles ──
SENSITIVE_PATTERNS = [
    # Mots de passe, clés API, secrets
    (
        re.compile(
            r'(?i)((?:password|secret|api_key|api\.key|token|access_token|'
            r'client_secret|private_key|bearer)[\s:="\']+)[^\s,\]}"\']+',
        ),
        r"\1[REDACTED]",
    ),
    # URLs avec credentials intégrées
    (re.compile(r"://[^:]+:[^@]+@"), "://[CREDENTIALS]@"),
    # Adresses IPv4
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP_REMOVED]"),
    # Adresses IPv6 complètes
    (re.compile(r"\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b"), "[IPV6_REMOVED]"),
    # Tokens longs type JWT
    (
        re.compile(r"[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{15,}\.[a-zA-Z0-9_-]{20,}"),
        "[TOKEN_REMOVED]",
    ),
    # Chaînes hexadécimales longues
    (re.compile(r"\b[a-fA-F0-9]{32,}\b"), "[HEX_KEY_REMOVED]"),
]


def sanitize_logs(log_content: str) -> str:
    """Nettoie les logs en masquant les informations sensibles."""
    sanitized = log_content
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ═══════════════════════════════════════════════════════
# SECTION 1 : Extraction des logs
# ═══════════════════════════════════════════════════════

async def _get_file_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Lit les dernières lignes de homeassistant.log (tail optimisé avec deque)."""
    log_file = hass.config.path("homeassistant.log")
    try:
        def read_tail():
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                return "".join(deque(f, maxlen=lines))

        content = await hass.async_add_executor_job(read_tail)
        if content:
            _LOGGER.debug("DomoLink-Mistral: %s lignes lues depuis homeassistant.log", lines)
            return content
    except FileNotFoundError:
        _LOGGER.warning("DomoLink-Mistral: Fichier homeassistant.log introuvable.")
    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur lecture homeassistant.log: %s", e)
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

        entries = []
        for record in records[-50:]:
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
# SECTION 2 : Inspection des automations
# ═══════════════════════════════════════════════════════

async def _get_automations_report(hass: HomeAssistant) -> str:
    """Inspecte toutes les automations et génère un rapport."""
    report_lines = []
    states = hass.states.async_all("automation")

    if not states:
        return ""

    total = len(states)
    disabled = 0
    problems = []

    for state in states:
        entity_id = state.entity_id
        attrs = state.attributes
        friendly_name = attrs.get("friendly_name", entity_id)
        current_state = state.state  # "on" ou "off"
        last_triggered = attrs.get("last_triggered")
        mode = attrs.get("mode", "single")

        # Automation désactivée
        if current_state == "off":
            disabled += 1
            problems.append(
                f"  ⚠️ DÉSACTIVÉE: '{friendly_name}' ({entity_id}) — "
                f"Mode: {mode}"
            )

        # Automation jamais déclenchée
        if last_triggered is None and current_state == "on":
            problems.append(
                f"  ℹ️ JAMAIS DÉCLENCHÉE: '{friendly_name}' ({entity_id}) — "
                f"Vérifier les triggers."
            )

        # Blueprint source
        blueprint = attrs.get("blueprint", {})
        if isinstance(blueprint, dict) and blueprint.get("path"):
            bp_path = blueprint["path"]
            report_lines.append(
                f"  📘 '{friendly_name}' utilise le blueprint: {bp_path}"
            )

    summary = (
        f"Total: {total} automations, {disabled} désactivée(s), "
        f"{len(problems)} problème(s) détecté(s)"
    )

    result = [summary]
    if problems:
        result.extend(problems)
    if report_lines:
        result.extend(report_lines)

    _LOGGER.debug("DomoLink-Mistral: Automations analysées — %s", summary)
    return "\n".join(result)


# ═══════════════════════════════════════════════════════
# SECTION 3 : Inspection des scripts
# ═══════════════════════════════════════════════════════

async def _get_scripts_report(hass: HomeAssistant) -> str:
    """Inspecte tous les scripts et génère un rapport."""
    states = hass.states.async_all("script")

    if not states:
        return ""

    total = len(states)
    problems = []
    info_lines = []

    for state in states:
        entity_id = state.entity_id
        attrs = state.attributes
        friendly_name = attrs.get("friendly_name", entity_id)
        current_state = state.state  # "on" = en cours d'exécution, "off" = idle
        mode = attrs.get("mode", "single")
        last_triggered = attrs.get("last_triggered")

        # Script en cours d'exécution
        if current_state == "on":
            problems.append(
                f"  🔄 EN COURS: '{friendly_name}' ({entity_id}) — "
                f"Mode: {mode}. Vérifier s'il n'est pas bloqué."
            )

        # Script jamais utilisé
        if last_triggered is None:
            info_lines.append(
                f"  ℹ️ JAMAIS UTILISÉ: '{friendly_name}' ({entity_id})"
            )

    summary = f"Total: {total} scripts, {len(problems)} en cours d'exécution"
    result = [summary]
    result.extend(problems)
    result.extend(info_lines)

    _LOGGER.debug("DomoLink-Mistral: Scripts analysés — %s", summary)
    return "\n".join(result)


# ═══════════════════════════════════════════════════════
# SECTION 4 : Inspection des scènes
# ═══════════════════════════════════════════════════════

async def _get_scenes_report(hass: HomeAssistant) -> str:
    """Inspecte les scènes configurées."""
    states = hass.states.async_all("scene")

    if not states:
        return ""

    total = len(states)
    _LOGGER.debug("DomoLink-Mistral: %s scènes trouvées", total)
    return f"Total: {total} scènes configurées."


# ═══════════════════════════════════════════════════════
# SECTION 5 : Entités indisponibles ou en erreur
# ═══════════════════════════════════════════════════════

async def _get_unavailable_entities(hass: HomeAssistant) -> str:
    """Détecte les entités en état 'unavailable' ou 'unknown'."""
    problems = []

    all_states = hass.states.async_all()
    unavailable = []
    unknown = []

    for state in all_states:
        entity_id = state.entity_id
        # Ignorer les entités de diagnostic et system
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

    lines = [
        f"Entités indisponibles: {len(unavailable)}, "
        f"Entités en état inconnu: {len(unknown)}"
    ]

    # Limiter à 30 pour ne pas surcharger le prompt
    if unavailable:
        lines.append("--- Indisponibles ---")
        lines.extend(unavailable[:30])
        if len(unavailable) > 30:
            lines.append(f"  ... et {len(unavailable) - 30} de plus")

    if unknown:
        lines.append("--- État inconnu ---")
        lines.extend(unknown[:20])
        if len(unknown) > 20:
            lines.append(f"  ... et {len(unknown) - 20} de plus")

    _LOGGER.debug(
        "DomoLink-Mistral: %s entités indisponibles, %s en état inconnu",
        len(unavailable), len(unknown),
    )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# SECTION 6 : Intégrations en erreur
# ═══════════════════════════════════════════════════════

async def _get_integration_issues(hass: HomeAssistant) -> str:
    """Vérifie l'état des entrées de configuration (intégrations)."""
    lines = []
    entries = hass.config_entries.async_entries()

    failed = []
    not_loaded = []

    for entry in entries:
        state = entry.state
        # ConfigEntryState enum : loaded, setup_error, setup_retry, not_loaded, etc.
        state_str = str(state)

        if "error" in state_str or "failed" in state_str:
            failed.append(
                f"  🔴 {entry.title} ({entry.domain}) — État: {state_str}"
            )
        elif "not_loaded" in state_str or "retry" in state_str:
            not_loaded.append(
                f"  🟡 {entry.title} ({entry.domain}) — État: {state_str}"
            )

    if not failed and not not_loaded:
        return "Toutes les intégrations sont chargées correctement."

    lines.append(
        f"Intégrations en erreur: {len(failed)}, "
        f"en attente: {len(not_loaded)}"
    )
    lines.extend(failed)
    lines.extend(not_loaded)

    _LOGGER.debug(
        "DomoLink-Mistral: %s intégrations en erreur, %s en attente",
        len(failed), len(not_loaded),
    )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# SECTION 7 : Informations système
# ═══════════════════════════════════════════════════════

async def _get_system_info(hass: HomeAssistant) -> str:
    """Collecte les infos système de base."""
    lines = []
    try:
        ha_version = hass.config.version
        lines.append(f"Version Home Assistant: {ha_version}")
        lines.append(f"Fuseau horaire: {hass.config.time_zone}")
        lines.append(f"Composants chargés: {len(hass.config.components)}")
        lines.append(f"Entités totales: {len(hass.states.async_all())}")
        lines.append(
            f"Intégrations configurées: "
            f"{len(hass.config_entries.async_entries())}"
        )
    except Exception as e:
        _LOGGER.debug("DomoLink-Mistral: Erreur info système: %s", e)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ═══════════════════════════════════════════════════════

async def get_recent_logs(hass: HomeAssistant, lines: int = 200) -> str:
    """Collecte complète de l'état du système HA pour analyse par Mistral.

    Retourne un rapport structuré contenant :
    1. Informations système
    2. Logs du fichier homeassistant.log
    3. Entrées structurées du system_log
    4. État des intégrations
    5. Entités indisponibles
    6. Rapport sur les automations
    7. Rapport sur les scripts
    8. Rapport sur les scènes
    """
    sections = []

    # ── 1. Infos système ──
    _LOGGER.info("DomoLink-Mistral: [1/7] Collecte des informations système...")
    sys_info = await _get_system_info(hass)
    if sys_info:
        sections.append(f"=== INFORMATIONS SYSTÈME ===\n{sys_info}")

    # ── 2. Logs fichier ──
    _LOGGER.info("DomoLink-Mistral: [2/7] Lecture de homeassistant.log...")
    file_logs = await _get_file_logs(hass, lines)
    if file_logs:
        sections.append(f"=== HOMEASSISTANT.LOG (dernières {lines} lignes) ===\n{file_logs}")

    # ── 3. System log structuré ──
    _LOGGER.info("DomoLink-Mistral: [3/7] Lecture du system_log structuré...")
    sys_log = await _get_system_log(hass)
    if sys_log:
        sections.append(f"=== SYSTEM_LOG (entrées structurées) ===\n{sys_log}")

    # ── 4. Intégrations en erreur ──
    _LOGGER.info("DomoLink-Mistral: [4/7] Vérification des intégrations...")
    integrations = await _get_integration_issues(hass)
    if integrations:
        sections.append(f"=== ÉTAT DES INTÉGRATIONS ===\n{integrations}")

    # ── 5. Entités indisponibles ──
    _LOGGER.info("DomoLink-Mistral: [5/7] Détection des entités indisponibles...")
    entities = await _get_unavailable_entities(hass)
    if entities:
        sections.append(f"=== ENTITÉS INDISPONIBLES ===\n{entities}")

    # ── 6. Automations ──
    _LOGGER.info("DomoLink-Mistral: [6/7] Analyse des automations et blueprints...")
    automations = await _get_automations_report(hass)
    if automations:
        sections.append(f"=== AUTOMATIONS & BLUEPRINTS ===\n{automations}")

    # ── 7. Scripts & Scènes ──
    _LOGGER.info("DomoLink-Mistral: [7/7] Analyse des scripts et scènes...")
    scripts = await _get_scripts_report(hass)
    if scripts:
        sections.append(f"=== SCRIPTS ===\n{scripts}")

    scenes = await _get_scenes_report(hass)
    if scenes:
        sections.append(f"=== SCÈNES ===\n{scenes}")

    if not sections:
        _LOGGER.warning("DomoLink-Mistral: Aucune donnée collectée.")
        return ""

    combined = "\n\n" + "═" * 60 + "\n\n".join(sections)

    _LOGGER.info(
        "DomoLink-Mistral: Collecte terminée — %s sections, %s caractères au total.",
        len(sections),
        len(combined),
    )

    return sanitize_logs(combined)
