"""Intégration DomoLink-Mistral pour Home Assistant.

Point d'entrée principal. Gère :
- L'initialisation et le déchargement de l'intégration
- L'enregistrement du panneau frontend (sidebar)
- La déclaration de tous les services (analyze, fix, ignore, all-auto)
- La planification des analyses (Live / Boot / Manuel)
- Le stockage persistant des erreurs ignorées
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    CONF_SCAN_FREQUENCY,
    CONF_SCAN_MODE,
    MODE_BOOT,
    MODE_LIVE,
    MODE_MANUAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure DomoLink-Mistral depuis une entrée de configuration."""
    hass.data.setdefault(DOMAIN, {})

    # ── Stockage persistant pour les erreurs ignorées ──
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load()
    ignored_ids: list[str] = stored_data.get("ignored_ids", []) if stored_data else []

    # ── Données de l'intégration ──
    hass.data[DOMAIN][entry.entry_id] = {
        "api_key": entry.data.get("api_key"),
        "options": entry.options,
        "sensor": None,  # Sera peuplé par sensor.py
        "store": store,
        "ignored_ids": ignored_ids,
        "last_issues": [],  # Cache des derniers résultats bruts de Mistral
        "cancel_listeners": [],  # Pour cleanup au unload
    }

    _LOGGER.info(
        "DomoLink-Mistral initialisé — modèle: %s, mode: %s",
        entry.options.get("model"),
        entry.options.get("scan_mode"),
    )

    # ── Enregistrement du panneau frontend (sidebar) ──
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/domolink_mistral_frontend",
                hass.config.path("custom_components/domolink_mistral/frontend"),
                cache_headers=False,
            )
        ]
    )

    from homeassistant.components.frontend import async_register_built_in_panel
    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Mistral AI",
        sidebar_icon="mdi:brain",
        frontend_url_path="domolink_mistral",
        config={
            "_panel_custom": {
                "name": "domolink-mistral-panel",
                "module_url": "/domolink_mistral_frontend/domolink-mistral-panel.js",
            }
        },
        require_admin=True,
    )

    # ═══════════════════════════════════════════════════════
    # SERVICES
    # ═══════════════════════════════════════════════════════

    async def _run_analysis():
        """Logique commune d'analyse utilisée par tous les déclencheurs."""
        from .analyzer import get_recent_logs
        from .mistral_api import analyze_with_mistral

        _LOGGER.info("DomoLink-Mistral: Début de l'analyse des logs...")
        logs = await get_recent_logs(hass)

        if not logs:
            _LOGGER.warning("DomoLink-Mistral: Aucun log récent trouvé.")
            return

        api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
        model = hass.data[DOMAIN][entry.entry_id]["options"].get(
            "model", "mistral-large-latest"
        )

        result = await analyze_with_mistral(hass, api_key, model, logs)
        issues = result.get("issues", [])
        _LOGGER.info("DomoLink-Mistral: Analyse terminée — %s problème(s).", len(issues))

        # Stocker les résultats bruts
        hass.data[DOMAIN][entry.entry_id]["last_issues"] = issues

        # Mettre à jour le capteur (avec filtre des ignorés)
        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        ignored = hass.data[DOMAIN][entry.entry_id]["ignored_ids"]
        if sensor:
            sensor.update_issues(issues, ignored)

        # Notification persistante si erreurs critiques
        high_count = sum(1 for i in issues if i.get("severity") == "high")
        if high_count > 0:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "🧠 DomoLink-Mistral",
                    "message": (
                        f"**{high_count} problème(s) critique(s)** détecté(s) "
                        f"sur {len(issues)} au total.\n\n"
                        "Ouvrez le panneau Mistral AI dans la barre latérale."
                    ),
                    "notification_id": "domolink_mistral_alert",
                },
            )

    async def handle_analyze_now(call):
        """Service : domolink_mistral.analyze_now"""
        await _run_analysis()

    async def handle_apply_fix(call):
        """Service : domolink_mistral.apply_fix"""
        from .reparator import trigger_backup, apply_fix

        fix_payload = call.data.get("fix_script")
        if not fix_payload:
            _LOGGER.error("DomoLink-Mistral: Aucun script de réparation fourni.")
            return

        backup_ok = await trigger_backup(hass)
        if backup_ok:
            result = await apply_fix(hass, fix_payload)
            _LOGGER.info("DomoLink-Mistral: Résultat du fix — %s", result)
        else:
            _LOGGER.error("DomoLink-Mistral: Sauvegarde échouée, réparation annulée.")

    async def handle_ignore_issue(call):
        """Service : domolink_mistral.ignore_issue"""
        issue_id = call.data.get("issue_id")
        if not issue_id:
            return

        data = hass.data[DOMAIN][entry.entry_id]
        if issue_id not in data["ignored_ids"]:
            data["ignored_ids"].append(issue_id)
            await data["store"].async_save({"ignored_ids": data["ignored_ids"]})

        # Rafraîchir le capteur
        sensor = data.get("sensor")
        if sensor and data["last_issues"]:
            sensor.update_issues(data["last_issues"], data["ignored_ids"])

        _LOGGER.info("DomoLink-Mistral: Erreur '%s' ignorée.", issue_id)

    async def handle_unignore_issue(call):
        """Service : domolink_mistral.unignore_issue"""
        issue_id = call.data.get("issue_id")
        if not issue_id:
            return

        data = hass.data[DOMAIN][entry.entry_id]
        if issue_id in data["ignored_ids"]:
            data["ignored_ids"].remove(issue_id)
            await data["store"].async_save({"ignored_ids": data["ignored_ids"]})

        sensor = data.get("sensor")
        if sensor and data["last_issues"]:
            sensor.update_issues(data["last_issues"], data["ignored_ids"])

        _LOGGER.info("DomoLink-Mistral: Erreur '%s' réactivée.", issue_id)

    async def handle_apply_all_fixes(call):
        """Service : domolink_mistral.apply_all_fixes"""
        from .reparator import trigger_backup, apply_fix

        data = hass.data[DOMAIN][entry.entry_id]
        issues = data.get("last_issues", [])
        ignored = data["ignored_ids"]

        # Filtrer les issues actives avec un auto_fix_script non-vide
        fixable = [
            i
            for i in issues
            if i.get("id") not in ignored
            and i.get("auto_fix_script")
            and i["auto_fix_script"] != []
        ]

        if not fixable:
            _LOGGER.info("DomoLink-Mistral: Aucune correction automatique disponible.")
            return

        _LOGGER.info(
            "DomoLink-Mistral: All Auto — %s correction(s) à appliquer.", len(fixable)
        )

        # Une seule sauvegarde pour toutes les corrections
        backup_ok = await trigger_backup(hass)
        if not backup_ok:
            _LOGGER.error("DomoLink-Mistral: Sauvegarde échouée, All Auto annulé.")
            return

        total_applied = 0
        total_skipped = 0

        for issue in fixable:
            result = await apply_fix(hass, issue["auto_fix_script"])
            total_applied += result["applied"]
            total_skipped += result["skipped"]

        _LOGGER.info(
            "DomoLink-Mistral: All Auto terminé — %s appliqué(s), %s ignoré(s).",
            total_applied,
            total_skipped,
        )

    # ── Enregistrement des services ──
    hass.services.async_register(DOMAIN, "analyze_now", handle_analyze_now)
    hass.services.async_register(DOMAIN, "apply_fix", handle_apply_fix)
    hass.services.async_register(DOMAIN, "ignore_issue", handle_ignore_issue)
    hass.services.async_register(DOMAIN, "unignore_issue", handle_unignore_issue)
    hass.services.async_register(DOMAIN, "apply_all_fixes", handle_apply_all_fixes)

    # ═══════════════════════════════════════════════════════
    # PLANIFICATION DES ANALYSES (Live / Boot / Manuel)
    # ═══════════════════════════════════════════════════════

    scan_mode = entry.options.get(CONF_SCAN_MODE, MODE_MANUAL)
    cancel_listeners = hass.data[DOMAIN][entry.entry_id]["cancel_listeners"]

    if scan_mode == MODE_LIVE:
        frequency = entry.options.get(CONF_SCAN_FREQUENCY, 1)
        interval_hours = max(1, 24 // frequency)
        _LOGGER.info(
            "DomoLink-Mistral: Mode Live activé — analyse toutes les %sh.", interval_hours
        )

        async def _live_callback(_now):
            await _run_analysis()

        cancel = async_track_time_interval(
            hass, _live_callback, timedelta(hours=interval_hours)
        )
        cancel_listeners.append(cancel)

    elif scan_mode == MODE_BOOT:
        _LOGGER.info("DomoLink-Mistral: Mode Boot activé — analyse 3 min après démarrage.")

        async def _boot_callback(_event):
            async def _delayed_analysis(_now):
                await _run_analysis()

            cancel = async_call_later(hass, 180, _delayed_analysis)
            cancel_listeners.append(cancel)

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _boot_callback)

    else:
        _LOGGER.info("DomoLink-Mistral: Mode Manuel — analyse uniquement à la demande.")

    # ── Charger les plateformes (sensor) ──
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge proprement l'intégration."""
    # Annuler tous les timers/listeners
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    for cancel in data.get("cancel_listeners", []):
        cancel()

    # Désenregistrer les services
    for service_name in [
        "analyze_now",
        "apply_fix",
        "ignore_issue",
        "unignore_issue",
        "apply_all_fixes",
    ]:
        hass.services.async_remove(DOMAIN, service_name)

    # Supprimer le panneau latéral
    try:
        from homeassistant.components.frontend import async_remove_panel
        async_remove_panel(hass, "domolink_mistral")
    except Exception:
        pass

    # Décharger les plateformes
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
