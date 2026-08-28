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

PLATFORMS: list[str] = ["sensor", "button", "conversation"]


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
                "module_url": "/domolink_mistral_frontend/domolink-mistral-panel.js?v=2.8.0",
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
        import time

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        start_time = time.monotonic()

        try:
            # ── Étape 1 : Collecte des données ──
            _LOGGER.info("DomoLink-Mistral: ═══ DÉBUT DE L'ANALYSE ═══")
            if sensor:
                sensor.set_status("📊 [1/3] Collecte des données système, logs, automations, scripts...")

            logs = await get_recent_logs(hass)

            if not logs:
                _LOGGER.info("DomoLink-Mistral: Aucune donnée à analyser (système sain).")
                if sensor:
                    sensor.update_issues([], hass.data[DOMAIN][entry.entry_id]["ignored_ids"])
                return

            elapsed = round(time.monotonic() - start_time, 1)
            _LOGGER.info(
                "DomoLink-Mistral: Collecte terminée en %ss — %s caractères récupérés.",
                elapsed, len(logs),
            )

            # ── Étape 2 : Envoi à Mistral ──
            api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
            model = hass.data[DOMAIN][entry.entry_id]["options"].get(
                "model", "mistral-large-latest"
            )

            if sensor:
                sensor.set_status(
                    f"🧠 [2/3] Envoi à Mistral AI ({model})... "
                    f"({len(logs)} caractères, peut prendre 30-60s)"
                )

            _LOGGER.info(
                "DomoLink-Mistral: Envoi de %s caractères à %s...",
                len(logs), model,
            )

            result = await analyze_with_mistral(hass, api_key, model, logs)

            elapsed = round(time.monotonic() - start_time, 1)
            _LOGGER.info("DomoLink-Mistral: Réponse Mistral reçue en %ss.", elapsed)

            # ── Étape 3 : Traitement des résultats ──
            if sensor:
                sensor.set_status("📋 [3/3] Traitement et classement des résultats...")

            issues = result.get("issues", [])

            # Stocker les résultats bruts
            hass.data[DOMAIN][entry.entry_id]["last_issues"] = issues

            # Mettre à jour le capteur (avec filtre des ignorés)
            ignored = hass.data[DOMAIN][entry.entry_id]["ignored_ids"]
            if sensor:
                sensor.update_issues(issues, ignored)

            # ── Résumé final ──
            elapsed = round(time.monotonic() - start_time, 1)
            high_count = sum(1 for i in issues if i.get("severity") == "high")
            medium_count = sum(1 for i in issues if i.get("severity") == "medium")
            low_count = sum(1 for i in issues if i.get("severity") == "low")

            summary = (
                f"✅ Analyse terminée en {elapsed}s — "
                f"{len(issues)} problème(s) : "
                f"🔴 {high_count} critique(s), "
                f"🟠 {medium_count} moyen(s), "
                f"🟢 {low_count} faible(s)"
            )

            _LOGGER.info("DomoLink-Mistral: %s", summary)

            if sensor:
                sensor.set_status(summary)

            # Notification persistante avec résumé
            if issues:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "🧠 DomoLink-Mistral — Analyse terminée",
                        "message": (
                            f"**{len(issues)} problème(s)** détecté(s) en {elapsed}s :\n\n"
                            f"- 🔴 **{high_count}** critique(s)\n"
                            f"- 🟠 **{medium_count}** moyen(s)\n"
                            f"- 🟢 **{low_count}** faible(s)\n\n"
                            "Ouvrez le panneau **Mistral AI** dans la barre latérale."
                        ),
                        "notification_id": "domolink_mistral_alert",
                    },
                )
            else:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "🧠 DomoLink-Mistral — Tout est OK !",
                        "message": (
                            f"Analyse terminée en {elapsed}s.\n\n"
                            "✅ Aucun problème détecté. Votre système est sain !"
                        ),
                        "notification_id": "domolink_mistral_alert",
                    },
                )

        except Exception as e:
            elapsed = round(time.monotonic() - start_time, 1)
            error_msg = f"Erreur lors de l'analyse après {elapsed}s : {e}"
            _LOGGER.error("DomoLink-Mistral: %s", error_msg)
            if sensor:
                sensor.set_status(f"❌ {error_msg}")

    async def handle_analyze_now(call):
        """Service : domolink_mistral.analyze_now"""
        await _run_analysis()

    async def handle_apply_fix(call):
        """Service : domolink_mistral.apply_fix"""
        from .reparator import trigger_backup, apply_fix

        fix_payload = call.data.get("fix_script")
        issue_id = call.data.get("issue_id")

        if not fix_payload:
            _LOGGER.error("DomoLink-Mistral: Aucun script de réparation fourni.")
            return

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        if sensor:
            sensor.set_status("⏳ Application du correctif en cours...")

        backup_ok = await trigger_backup(hass)
        if backup_ok:
            result = await apply_fix(hass, fix_payload)
            _LOGGER.info("DomoLink-Mistral: Résultat du fix — %s", result)

            # Si succès et qu'un issue_id a été fourni, retirer l'issue résolue
            data = hass.data[DOMAIN][entry.entry_id]
            if result.get("success") and issue_id and data.get("last_issues"):
                data["last_issues"] = [i for i in data["last_issues"] if i.get("id") != issue_id]
                if sensor:
                    sensor.update_issues(data["last_issues"], data["ignored_ids"])
                    sensor.set_status(f"✅ Correctif appliqué avec succès ({result.get('applied')} action(s)).")
            elif sensor:
                sensor.set_status(f"Résultat: {result.get('applied')} appliqué(s), {result.get('skipped')} ignoré(s).")

            # Notification
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "🧠 DomoLink-Mistral — Correctif appliqué",
                    "message": (
                        f"**Résultat du correctif :**\n"
                        f"- Appliqué(s) : {result.get('applied')}\n"
                        f"- Ignoré(s) : {result.get('skipped')}\n\n"
                        f"Détails : {', '.join(result.get('details', [])) or 'OK'}"
                    ),
                    "notification_id": "domolink_mistral_fix_result",
                },
            )
        else:
            _LOGGER.error("DomoLink-Mistral: Sauvegarde échouée, réparation annulée.")
            if sensor:
                sensor.set_status("❌ Échec de la sauvegarde, réparation annulée.")

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
        sensor = data.get("sensor")

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
            if sensor:
                sensor.set_status("ℹ️ Aucune correction automatique disponible.")
            return

        if sensor:
            sensor.set_status(f"⏳ All Auto : Application de {len(fixable)} correctif(s)...")

        # Une seule sauvegarde pour toutes les corrections
        backup_ok = await trigger_backup(hass)
        if not backup_ok:
            _LOGGER.error("DomoLink-Mistral: Sauvegarde échouée, All Auto annulé.")
            if sensor:
                sensor.set_status("❌ Échec de la sauvegarde préalable, All Auto annulé.")
            return

        total_applied = 0
        total_skipped = 0
        all_details = []
        fixed_ids = set()

        for issue in fixable:
            result = await apply_fix(hass, issue["auto_fix_script"])
            total_applied += result["applied"]
            total_skipped += result["skipped"]
            all_details.extend(result.get("details", []))
            if result.get("success"):
                fixed_ids.add(issue.get("id"))

        # Retirer les issues résolues
        data["last_issues"] = [i for i in data["last_issues"] if i.get("id") not in fixed_ids]
        if sensor:
            sensor.update_issues(data["last_issues"], data["ignored_ids"])
            sensor.set_status(f"⚡ All Auto terminé : {total_applied} appliqué(s), {total_skipped} ignoré(s).")

        # Notification
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🧠 DomoLink-Mistral — All Auto terminé",
                "message": (
                    f"**{total_applied} correctif(s) appliqué(s)** avec succès.\n"
                    f"{total_skipped} ignoré(s).\n\n"
                    f"Détails : {', '.join(all_details) or 'Terminé'}"
                ),
                "notification_id": "domolink_mistral_all_auto_result",
            },
        )

    async def handle_generate_automation(call):
        """Service : domolink_mistral.generate_automation"""
        from .mistral_api import generate_automation_with_mistral

        prompt = call.data.get("prompt", "").strip()
        if not prompt:
            _LOGGER.error("DomoLink-Mistral: Prompt vide pour la génération d'automation.")
            return {"success": False, "error": "Prompt vide"}

        api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
        model = hass.data[DOMAIN][entry.entry_id]["options"].get(
            "model", "mistral-large-latest"
        )

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        if sensor:
            sensor.set_status("✨ Génération de l'automation en cours par Mistral...")

        result = await generate_automation_with_mistral(hass, api_key, model, prompt)
        
        if result.get("success"):
            data = result.get("data", {})
            hass.data[DOMAIN][entry.entry_id]["last_generated_automation"] = data
            if sensor:
                sensor.set_status(f"✅ Automation '{data.get('title', 'Nouvelle automation')}' générée avec succès !")
            # Déclencher un event HA pour notifier le frontend
            hass.bus.async_fire("domolink_mistral_automation_generated", data)
            return data
        else:
            err = result.get("error", "Erreur inconnue")
            if sensor:
                sensor.set_status(f"❌ Échec génération automation : {err}")
            return {"success": False, "error": err}

    async def handle_save_automation(call):
        """Service : domolink_mistral.save_automation"""
        from .reparator import append_automation_to_yaml

        yaml_content = call.data.get("yaml", "").strip()
        if not yaml_content:
            _LOGGER.error("DomoLink-Mistral: Code YAML vide.")
            return {"success": False, "error": "Code YAML vide"}

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        if sensor:
            sensor.set_status("💾 Enregistrement de l'automation dans automations.yaml...")

        res = await append_automation_to_yaml(hass, yaml_content)
        if sensor:
            if res.get("success"):
                sensor.set_status("✅ Automation injectée et active dans Home Assistant !")
            else:
                sensor.set_status(f"❌ {res.get('message')}")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🧠 DomoLink-Mistral — Automation ajoutée",
                "message": res.get("message", "Opération terminée."),
                "notification_id": "domolink_mistral_auto_created",
            },
        )
        return res

    async def handle_analyze_image(call):
        """Service : domolink_mistral.analyze_image (Vision par Pixtral)."""
        import base64
        from .mistral_api import analyze_image_with_pixtral, PIXTRAL_DEFAULT_MODEL

        camera_entity_id = call.data.get("camera_entity_id")
        image_path = call.data.get("image_path")
        prompt = call.data.get(
            "prompt",
            "Décris précisément ce que tu vois sur cette image. Détecte les personnes, véhicules, colis, ouvertures ou anomalies.",
        )
        model = call.data.get("model", PIXTRAL_DEFAULT_MODEL)

        image_bytes = None
        mime_type = "image/jpeg"

        # Cas 1 : Capture directe depuis une caméra Home Assistant
        if camera_entity_id:
            try:
                from homeassistant.components import camera
                image = await camera.async_get_image(hass, camera_entity_id)
                image_bytes = image.content
                mime_type = image.content_type or "image/jpeg"
            except Exception as e:
                _LOGGER.error("DomoLink-Mistral Vision: Échec capture caméra %s: %s", camera_entity_id, e)
                return {"success": False, "error": f"Échec capture caméra : {e}"}

        # Cas 2 : Fichier image local
        elif image_path:
            def _read_file():
                with open(image_path, "rb") as f:
                    return f.read()

            try:
                image_bytes = await hass.async_add_executor_job(_read_file)
                if image_path.lower().endswith(".png"):
                    mime_type = "image/png"
            except Exception as e:
                _LOGGER.error("DomoLink-Mistral Vision: Échec lecture fichier %s: %s", image_path, e)
                return {"success": False, "error": f"Échec lecture fichier : {e}"}

        if not image_bytes:
            return {"success": False, "error": "Aucune source d'image fournie (camera_entity_id ou image_path requis)"}

        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        if sensor:
            sensor.set_status("👁️ Analyse de l'image de caméra via Pixtral...")

        res = await analyze_image_with_pixtral(
            hass, api_key=api_key, base64_image=b64_str, prompt=prompt, model=model, mime_type=mime_type
        )

        if res.get("success"):
            data = res.get("data", {})
            if sensor:
                sensor.set_status(f"👁️ Analyse caméra : {data.get('summary', 'Terminée')}")
            hass.bus.async_fire("domolink_mistral_image_analyzed", data)
            return data
        else:
            err = res.get("error", "Erreur inconnue")
            if sensor:
                sensor.set_status(f"❌ Échec analyse image : {err}")
            return {"success": False, "error": err}

    async def handle_generate_daily_briefing(call):
        """Service : domolink_mistral.generate_daily_briefing (Briefing matinal/soirée)."""
        from .mistral_api import generate_daily_briefing_with_mistral

        time_of_day = call.data.get("time_of_day", "auto")
        custom_instruction = call.data.get("custom_instruction", "")

        if time_of_day == "auto":
            import datetime
            hour = datetime.datetime.now().hour
            time_of_day = "morning" if hour < 14 else "evening"

        # Collecte synthétique des données
        summary_lines = []
        
        # Météo
        weather_states = [s for s in hass.states.async_all("weather")]
        if weather_states:
            w = weather_states[0]
            summary_lines.append(f"Météo actuelle : {w.state}, Température : {w.attributes.get('temperature')}°C, Humidité : {w.attributes.get('humidity')}%")

        # Lumières allumées
        lights_on = [s.attributes.get("friendly_name", s.entity_id) for s in hass.states.async_all("light") if s.state == "on"]
        if lights_on:
            summary_lines.append(f"Lumières allumées ({len(lights_on)}) : {', '.join(lights_on[:10])}")
        else:
            summary_lines.append("Toutes les lumières sont éteintes.")

        # Portes / Fenêtres ouvertes
        openings = [s.attributes.get("friendly_name", s.entity_id) for s in hass.states.async_all("binary_sensor") if s.attributes.get("device_class") in ("door", "window", "garage_door", "opening") and s.state == "on"]
        if openings:
            summary_lines.append(f"⚠️ Ouvertures ouvertes ({len(openings)}) : {', '.join(openings)}")
        else:
            summary_lines.append("Toutes les portes et fenêtres sont fermées.")

        # Batteries faibles (<20%)
        low_batteries = [
            f"{s.attributes.get('friendly_name', s.entity_id)} ({s.state}%)"
            for s in hass.states.async_all("sensor")
            if s.attributes.get("device_class") == "battery" and s.state.isdigit() and int(s.state) < 20
        ]
        if low_batteries:
            summary_lines.append(f"⚠️ Batteries faibles : {', '.join(low_batteries)}")

        system_data = "\n".join(summary_lines)
        api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
        model = hass.data[DOMAIN][entry.entry_id]["options"].get("model", "mistral-large-latest")

        sensor = hass.data[DOMAIN][entry.entry_id].get("sensor")
        if sensor:
            sensor.set_status("📰 Génération du Smart Briefing en cours...")

        res = await generate_daily_briefing_with_mistral(
            hass, api_key=api_key, model=model, system_data=system_data, time_of_day=time_of_day, custom_instruction=custom_instruction
        )

        if res.get("success"):
            data = res.get("data", {})
            if sensor:
                sensor.set_status("✅ Briefing généré avec succès !")
            hass.bus.async_fire("domolink_mistral_daily_briefing_generated", data)
            return data
        else:
            err = res.get("error", "Erreur inconnue")
            if sensor:
                sensor.set_status(f"❌ Échec briefing : {err}")
            return {"success": False, "error": err}

    # ── Enregistrement des services ──
    hass.services.async_register(DOMAIN, "analyze_now", handle_analyze_now)
    hass.services.async_register(DOMAIN, "apply_fix", handle_apply_fix)
    hass.services.async_register(DOMAIN, "ignore_issue", handle_ignore_issue)
    hass.services.async_register(DOMAIN, "unignore_issue", handle_unignore_issue)
    hass.services.async_register(DOMAIN, "apply_all_fixes", handle_apply_all_fixes)
    hass.services.async_register(DOMAIN, "generate_automation", handle_generate_automation)
    hass.services.async_register(DOMAIN, "save_automation", handle_save_automation)
    hass.services.async_register(DOMAIN, "analyze_image", handle_analyze_image)
    hass.services.async_register(DOMAIN, "generate_daily_briefing", handle_generate_daily_briefing)

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
        "generate_automation",
        "save_automation",
        "analyze_image",
        "generate_daily_briefing",
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
