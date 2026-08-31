"""Module de réparation automatique pour DomoLink-Mistral.

Responsabilités :
- Déclenchement de sauvegardes de sécurité avant toute modification
- Exécution sécurisée des correctifs de services Home Assistant (avec whitelist)
- Application sécurisée des corrections dans les fichiers YAML (avec backup .bak et validation)
- Rechargement automatique des configurations après modification
"""
import os
import shutil
import logging
import json
from datetime import datetime

from homeassistant.core import HomeAssistant

from .const import ALLOWED_FIX_DOMAINS, BLOCKED_SERVICES, ALLOWED_YAML_FILES

_LOGGER = logging.getLogger(__name__)


async def trigger_backup(hass: HomeAssistant) -> bool:
    """Déclenche une sauvegarde de sécurité avant d'appliquer une modification."""
    try:
        # HA 2023.x+ : service natif backup.create (lancé sans bloquer pour éviter les timeouts)
        if hass.services.has_service("backup", "create"):
            await hass.services.async_call("backup", "create", {}, blocking=False)
            _LOGGER.info("DomoLink-Mistral: Sauvegarde système lancée en arrière-plan.")
            return True

        # Ancienne méthode via Hass.io / Supervisor
        if hass.services.has_service("hassio", "backup_full"):
            await hass.services.async_call("hassio", "backup_full", {}, blocking=False)
            _LOGGER.info("DomoLink-Mistral: Sauvegarde Supervisor lancée en arrière-plan.")
            return True

        _LOGGER.debug(
            "DomoLink-Mistral: Aucun service de backup global. "
            "La correction sera sécurisée par le backup local .bak."
        )
        return True

    except Exception as e:
        _LOGGER.warning("DomoLink-Mistral: Erreur lors de la sauvegarde globale: %s (backup local .bak actif)", e)
        return True


def _is_service_allowed(domain: str, service: str) -> bool:
    """Vérifie qu'un service est autorisé (whitelist) et non bloqué (blacklist)."""
    full_service = f"{domain}.{service}"

    if full_service in BLOCKED_SERVICES:
        _LOGGER.warning("DomoLink-Mistral: Service bloqué par sécurité: %s", full_service)
        return False

    if domain not in ALLOWED_FIX_DOMAINS:
        _LOGGER.warning(
            "DomoLink-Mistral: Domaine '%s' non autorisé pour l'auto-fix. Domaines autorisés: %s",
            domain, ", ".join(sorted(ALLOWED_FIX_DOMAINS)),
        )
        return False

    return True


def _apply_yaml_file_fix(hass: HomeAssistant, file_rel_path: str, find_text: str = None, replace_text: str = None, new_content: str = None) -> dict:
    """Modifie un fichier YAML de manière sécurisée avec backup préalable."""
    config_dir = hass.config.config_dir
    target_path = os.path.normpath(os.path.join(config_dir, file_rel_path))

    # Sécurité : interdire de sortir du dossier config (path traversal)
    if not target_path.startswith(config_dir):
        _LOGGER.error("DomoLink-Mistral: Chemin de fichier non autorisé: %s", file_rel_path)
        return {"success": False, "reason": "Chemin interdit (en dehors de config)"}

    # Sécurité : vérifier que le nom de fichier ou sous-dossier est autorisé
    base_name = os.path.basename(target_path)
    is_allowed = (
        base_name in ALLOWED_YAML_FILES
        or file_rel_path.startswith("esphome/")
        or file_rel_path.startswith("blueprints/")
    )
    if not is_allowed:
        _LOGGER.error("DomoLink-Mistral: Type de fichier non autorisé pour modification: %s", file_rel_path)
        return {"success": False, "reason": f"Fichier non autorisé: {base_name}"}

    if not os.path.exists(target_path) and new_content is None:
        return {"success": False, "reason": f"Fichier introuvable: {file_rel_path}"}

    # 1. Création d'un backup .bak timestampé
    if os.path.exists(target_path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{target_path}.{ts}.bak"
        try:
            shutil.copy2(target_path, backup_path)
            _LOGGER.info("DomoLink-Mistral: Backup créé -> %s", backup_path)
        except Exception as e:
            return {"success": False, "reason": f"Échec de la sauvegarde préalable: {e}"}

    # 2. Calcul du nouveau contenu
    try:
        if new_content is not None:
            updated = new_content
        else:
            with open(target_path, "r", encoding="utf-8") as f:
                original = f.read()

            if find_text and find_text in original:
                # Remplacer uniquement la première occurrence ciblée pour éviter d'altérer d'autres blocs
                updated = original.replace(find_text, replace_text or "", 1)
            else:
                return {"success": False, "reason": f"Texte cible non trouvé dans {file_rel_path}"}

        # 3. Validation de syntaxe YAML avant écriture
        try:
            import yaml
            class _SafeLoader(yaml.SafeLoader):
                pass
            def _dummy(loader, tag, node):
                return None
            _SafeLoader.add_multi_constructor("!", _dummy)
            yaml.load(updated, Loader=_SafeLoader)
        except Exception as yaml_err:
            _LOGGER.error("DomoLink-Mistral: La modification produirait un YAML invalide: %s", yaml_err)
            return {"success": False, "reason": f"Syntaxe YAML invalide dans le correctif: {yaml_err}"}

        # 4. Écriture
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(updated)

        _LOGGER.info("DomoLink-Mistral: Fichier %s modifié avec succès.", file_rel_path)
        return {"success": True, "file": file_rel_path}

    except Exception as e:
        _LOGGER.error("DomoLink-Mistral: Erreur écriture %s: %s", file_rel_path, e)
        return {"success": False, "reason": str(e)}


async def apply_fix(hass: HomeAssistant, fix_payload) -> dict:
    """Exécute de manière sécurisée les correctifs proposés par Mistral (Services ou Fichiers YAML).

    Retourne un dict avec le résultat : {"success": bool, "applied": int, "skipped": int, "details": list}
    """
    if isinstance(fix_payload, str):
        if not fix_payload.strip():
            return {"success": False, "applied": 0, "skipped": 0, "details": []}
        try:
            actions = json.loads(fix_payload)
        except json.JSONDecodeError:
            _LOGGER.error("Impossible de parser le script de correction (JSON invalide).")
            return {"success": False, "applied": 0, "skipped": 0, "details": ["JSON invalide"]}
    elif isinstance(fix_payload, list):
        actions = fix_payload
    elif isinstance(fix_payload, dict):
        actions = [fix_payload]
    else:
        return {"success": False, "applied": 0, "skipped": 0, "details": []}

    if not isinstance(actions, list):
        actions = [actions]

    applied = 0
    skipped = 0
    details = []
    yaml_files_modified = set()

    for action in actions:
        if not isinstance(action, dict):
            continue

        action_type = action.get("action_type", "")

        # ── CAS 1 : Modification de fichier YAML ──
        if action_type in ("yaml_edit", "yaml_write") or "file" in action:
            file_path = action.get("file", "")
            find_txt = action.get("find")
            replace_txt = action.get("replace")
            new_cont = action.get("content") or action.get("new_content")

            res = await hass.async_add_executor_job(
                _apply_yaml_file_fix, hass, file_path, find_txt, replace_txt, new_cont
            )
            if res.get("success"):
                applied += 1
                yaml_files_modified.add(file_path)
                details.append(f"Fichier modifié: {file_path}")
            else:
                skipped += 1
                details.append(f"Échec {file_path}: {res.get('reason')}")
            continue

        # ── CAS 2 : Appel de service Home Assistant standard ──
        domain = action.get("domain", "")
        service = action.get("service", "")
        data = action.get("service_data", {})

        if not domain or not service:
            skipped += 1
            continue

        # Vérification de sécurité
        if not _is_service_allowed(domain, service):
            skipped += 1
            details.append(f"Service non autorisé: {domain}.{service}")
            continue

        # Vérification que le service existe dans HA
        if not hass.services.has_service(domain, service):
            _LOGGER.warning("DomoLink-Mistral: Service %s.%s introuvable dans Home Assistant.", domain, service)
            skipped += 1
            details.append(f"Service introuvable: {domain}.{service}")
            continue

        try:
            _LOGGER.info("DomoLink-Mistral: Application du service %s.%s", domain, service)
            await hass.services.async_call(domain, service, data, blocking=True)
            applied += 1
            details.append(f"Service exécuté: {domain}.{service}")
        except Exception as e:
            _LOGGER.error("DomoLink-Mistral: Échec de %s.%s: %s", domain, service, e)
            skipped += 1
            details.append(f"Erreur {domain}.{service}: {e}")

    # ── Rechargement automatique des configurations si des fichiers YAML ont été modifiés ──
    for modified_file in yaml_files_modified:
        try:
            if "automation" in modified_file and hass.services.has_service("automation", "reload"):
                await hass.services.async_call("automation", "reload", {}, blocking=False)
            elif "script" in modified_file and hass.services.has_service("script", "reload"):
                await hass.services.async_call("script", "reload", {}, blocking=False)
            elif "scene" in modified_file and hass.services.has_service("scene", "reload"):
                await hass.services.async_call("scene", "reload", {}, blocking=False)
            elif "configuration.yaml" in modified_file and hass.services.has_service("homeassistant", "reload_core_config"):
                await hass.services.async_call("homeassistant", "reload_core_config", {}, blocking=False)
        except Exception as reload_err:
            _LOGGER.debug("DomoLink-Mistral: Erreur rechargement post-fix: %s", reload_err)

    success = applied > 0 and skipped == 0
    _LOGGER.info("DomoLink-Mistral: Réparation terminée — %s appliqué(s), %s ignoré(s).", applied, skipped)
    return {"success": success, "applied": applied, "skipped": skipped, "details": details}


async def append_automation_to_yaml(hass: HomeAssistant, automation_yaml: str) -> dict:
    """Ajoute une nouvelle automation générée par Mistral dans automations.yaml."""
    def _do_append():
        config_dir = hass.config.config_dir
        target_path = os.path.join(config_dir, "automations.yaml")
        if not os.path.exists(target_path):
            alt_path = os.path.join(config_dir, "automation.yaml")
            if os.path.exists(alt_path):
                target_path = alt_path

        # 1. Backup préalable
        if os.path.exists(target_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{target_path}.{ts}.bak"
            try:
                shutil.copy2(target_path, backup_path)
                _LOGGER.info("DomoLink-Mistral: Backup automations créé -> %s", backup_path)
            except Exception as e:
                return {"success": False, "message": f"Échec sauvegarde automations.yaml: {e}"}

        # 2. Nettoyage du YAML fourni
        cleaned = automation_yaml.strip()
        if cleaned.startswith("```yaml"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # S'assurer que le bloc commence par un tiret si c'est une liste
        lines = cleaned.splitlines()
        if lines and not lines[0].strip().startswith("-"):
            # Ajouter le tiret au premier élément et indenter le reste
            formatted_lines = [f"- {lines[0]}"]
            for l in lines[1:]:
                formatted_lines.append(f"  {l}")
            cleaned = "\n".join(formatted_lines)

        # 3. Lecture du fichier existant
        existing = ""
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
                # Si le fichier ne contient que '[]', le vider pour permettre une liste YAML propre
                if existing == "[]":
                    existing = ""

        combined = (existing + "\n\n" + cleaned + "\n") if existing else (cleaned + "\n")

        # 4. Validation syntaxique
        try:
            import yaml
            class _SafeLoader(yaml.SafeLoader):
                pass
            def _dummy(loader, tag, node):
                return None
            _SafeLoader.add_multi_constructor("!", _dummy)
            yaml.load(combined, Loader=_SafeLoader)
        except Exception as yaml_err:
            _LOGGER.error("DomoLink-Mistral: Erreur syntaxe automation générée: %s", yaml_err)
            return {"success": False, "message": f"YAML invalide : {yaml_err}"}

        # 5. Écriture
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(combined)

        _LOGGER.info("DomoLink-Mistral: Nouvelle automation ajoutée à %s", target_path)
        return {"success": True, "file": os.path.basename(target_path)}

    res = await hass.async_add_executor_job(_do_append)
    if res.get("success"):
        # Recharger les automations
        if hass.services.has_service("automation", "reload"):
            await hass.services.async_call("automation", "reload", {}, blocking=True)
            res["message"] = "Automation injectée et rechargée avec succès dans Home Assistant !"
        else:
            res["message"] = "Automation enregistrée dans automations.yaml."

    return res

