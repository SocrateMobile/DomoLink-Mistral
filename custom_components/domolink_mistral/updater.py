"""Module de mise à jour automatique pour DomoLink-Mistral IA.

Gère :
- La vérification des releases GitHub via l'API officielle
- La comparaison sémantique de versions
- Le téléchargement et l'extraction sécurisée des archives
- La création de sauvegardes locales pré-mise à jour (.bak)
- Le déclenchement du redémarrage de Home Assistant
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

GITHUB_REPO = "SocrateMobile/DomoLink-Mistral"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_semver(v: str) -> tuple[int, ...]:
    """Extrait les composants numériques d'une version pour comparaison."""
    if not v:
        return (0, 0, 0)
    cleaned = v.strip().lstrip("vV")
    numbers = [int(n) for n in re.findall(r"\d+", cleaned)]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])


def is_newer_version(latest: str, current: str) -> bool:
    """Renvoie True si la version latest est strictement plus récente que current."""
    try:
        return parse_semver(latest) > parse_semver(current)
    except Exception:
        return False


class UpdateManager:
    """Gestionnaire de vérification et d'application des mises à jour."""

    def __init__(self, hass: HomeAssistant, entry_id: str):
        """Initialisation."""
        self.hass = hass
        self.entry_id = entry_id
        self.current_version: str = VERSION
        self.latest_version: str = VERSION
        self.has_update: bool = False
        self.release_tag: str = f"v{VERSION}"
        self.release_url: str = f"https://github.com/{GITHUB_REPO}/releases"
        self.changelog: str = ""
        self.zip_url: str | None = None
        self.published_at: str | None = None
        self.last_checked: str | None = None
        self.is_updating: bool = False
        self.update_progress: int = 0
        self.update_status_text: str = "À jour"

    async def async_check(self) -> dict[str, Any]:
        """Vérifie la présence d'une nouvelle version sur GitHub."""
        _LOGGER.debug("DomoLink-Mistral IA: Vérification des mises à jour sur GitHub...")
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "HomeAssistant-DomoLinkMistral",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(GITHUB_API_URL, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        tag_name = data.get("tag_name", "").strip()
                        clean_tag = tag_name.lstrip("vV")

                        self.release_tag = tag_name or f"v{clean_tag}"
                        self.latest_version = clean_tag or self.current_version
                        self.release_url = data.get("html_url", self.release_url)
                        self.changelog = data.get("body", "Aucune note de version.")
                        self.zip_url = data.get("zipball_url")
                        self.published_at = data.get("published_at")
                        self.last_checked = datetime.now().isoformat()

                        self.has_update = is_newer_version(self.latest_version, self.current_version)

                        if self.has_update:
                            self.update_status_text = f"Mise à jour disponible ({self.release_tag})"
                            _LOGGER.info(
                                "DomoLink-Mistral IA: Nouvelle version détectée : %s (actuelle: %s)",
                                self.latest_version,
                                self.current_version,
                            )
                        else:
                            self.update_status_text = "À jour"

                    elif response.status == 403:
                        _LOGGER.warning("DomoLink-Mistral IA: Limite d'API GitHub atteinte (HTTP 403).")
                    else:
                        _LOGGER.debug("DomoLink-Mistral IA: Réponse GitHub HTTP %s", response.status)

        except Exception as err:
            _LOGGER.debug("DomoLink-Mistral IA: Erreur lors de la vérification GitHub: %s", err)

        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        """Exporte l'état actuel sous forme de dictionnaire."""
        return {
            "has_update": self.has_update,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "release_tag": self.release_tag,
            "release_url": self.release_url,
            "changelog": self.changelog,
            "zip_url": self.zip_url,
            "published_at": self.published_at,
            "last_checked": self.last_checked,
            "is_updating": self.is_updating,
            "update_progress": self.update_progress,
            "update_status_text": self.update_status_text,
        }

    async def async_install_update(self, restart_after: bool = True) -> dict[str, Any]:
        """Télécharge, sauvegarde et applique la mise à jour."""
        if self.is_updating:
            return {"success": False, "error": "Une mise à jour est déjà en cours."}

        self.is_updating = True
        self.update_progress = 10
        self.update_status_text = "📦 Téléchargement de la mise à jour..."

        try:
            # S'assurer d'avoir les données de release
            if not self.zip_url:
                await self.async_check()

            if not self.zip_url:
                raise ValueError("URL de téléchargement GitHub introuvable.")

            # Étape 1 : Téléchargement du ZIP
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "HomeAssistant-DomoLinkMistral",
            }
            zip_bytes = None
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.zip_url, headers=headers) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Échec téléchargement release (HTTP {resp.status})")
                    zip_bytes = await resp.read()

            self.update_progress = 40
            self.update_status_text = "🛡️ Création de la sauvegarde locale..."

            # Étape 2 : Sauvegarde et Déploiement dans un thread executor
            def _apply_in_executor():
                custom_components_dir = self.hass.config.path("custom_components")
                target_dir = os.path.join(custom_components_dir, DOMAIN)

                # Créer une sauvegarde horodatée du composant
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = os.path.join(custom_components_dir, f"{DOMAIN}_backup_{timestamp}")

                if os.path.exists(target_dir):
                    shutil.copytree(target_dir, backup_dir)
                    _LOGGER.info("DomoLink-Mistral IA: Sauvegarde créée -> %s", backup_dir)

                # Extraction du ZIP
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                    namelist = z.namelist()
                    prefix = None
                    for name in namelist:
                        if "custom_components/domolink_mistral/" in name:
                            idx = name.find("custom_components/domolink_mistral/")
                            prefix = name[:idx + len("custom_components/domolink_mistral/")]
                            break

                    if not prefix:
                        prefix = namelist[0].split("/")[0] + "/"

                    os.makedirs(target_dir, exist_ok=True)

                    for member in z.infolist():
                        if not member.filename.startswith(prefix) or member.is_dir():
                            continue
                        rel_path = member.filename[len(prefix):]
                        if not rel_path or ".." in rel_path:
                            continue

                        dest_file = os.path.join(target_dir, rel_path)
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        with z.open(member) as src, open(dest_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                return True

            await self.hass.async_add_executor_job(_apply_in_executor)

            self.update_progress = 85
            self.update_status_text = "⚡ Fichiers déployés avec succès !"

            # Étape 3 : Redémarrage automatique si demandé
            if restart_after:
                self.update_progress = 100
                self.update_status_text = "🔄 Redémarrage de Home Assistant..."
                _LOGGER.info("DomoLink-Mistral IA: Mise à jour terminée. Redémarrage de Home Assistant...")

                async def _delayed_restart(_now=None):
                    await self.hass.services.async_call("homeassistant", "restart", {})

                self.hass.loop.call_later(2.0, lambda: asyncio.create_task(_delayed_restart()))

            self.is_updating = False
            return {
                "success": True,
                "message": f"DomoLink-Mistral IA mis à jour vers {self.latest_version} !",
                "restarting": restart_after,
            }

        except Exception as e:
            self.is_updating = False
            self.update_status_text = f"❌ Échec de la mise à jour : {e}"
            _LOGGER.error("DomoLink-Mistral IA: Échec mise à jour automatique: %s", e)
            return {"success": False, "error": str(e)}
