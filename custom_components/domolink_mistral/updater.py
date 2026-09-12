"""Module de mise à jour automatique pour DomoLink-Mistral IA.

Gère :
- La vérification des releases GitHub via l'API officielle
- La comparaison sémantique de versions
- Le téléchargement et l'extraction sécurisée des archives
- La création de sauvegardes locales pré-mise à jour (.bak)
- Le nettoyage du cache __pycache__
- La mise à jour sur place du dossier actif de l'intégration
- Le déclenchement sécurisé du redémarrage de Home Assistant
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

GITHUB_REPO = "SocrateMobile/DomoLink-Mistral"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Extrait les composants numériques d'une version pour comparaison."""
    if not version_str:
        return (0, 0, 0)
    clean = re.sub(r"^[vV]", "", str(version_str).strip())
    parts = []
    for segment in clean.split("."):
        digits = re.match(r"^\d+", segment)
        parts.append(int(digits.group(0)) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer_version(latest: str, current: str) -> bool:
    """Renvoie True si la version latest est strictement plus récente que current."""
    try:
        return parse_semver(latest) > parse_semver(current)
    except Exception:
        return False


def get_installed_version() -> str:
    """Récupère la version installée depuis le manifest.json local ou const."""
    try:
        manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return str(data.get("version", VERSION))
    except Exception as err:
        _LOGGER.debug("Could not read manifest.json version: %s", err)
    return VERSION


class UpdateManager:
    """Gestionnaire de vérification et d'application des mises à jour."""

    def __init__(self, hass: HomeAssistant, entry_id: str):
        """Initialisation."""
        self.hass = hass
        self.entry_id = entry_id
        self.current_version: str = get_installed_version()
        self.latest_version: str = self.current_version
        self.has_update: bool = False
        self.release_tag: str = f"v{self.current_version}"
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
            session = async_get_clientsession(self.hass)
            timeout = aiohttp.ClientTimeout(total=15)
            async with session.get(GITHUB_API_URL, headers=headers, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    tag_name = data.get("tag_name", "").strip()
                    clean_tag = re.sub(r"^[vV]", "", tag_name)

                    self.current_version = get_installed_version()
                    self.release_tag = tag_name or f"v{clean_tag}"
                    self.latest_version = clean_tag or self.current_version
                    self.release_url = data.get("html_url", self.release_url)
                    self.changelog = data.get("body", "Aucune note de version.")
                    self.zip_url = (
                        f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{self.release_tag}.zip"
                    )
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

    async def async_install_update(
        self, restart_after: bool = True, backup: bool = True
    ) -> dict[str, Any]:
        """Télécharge, sauvegarde et applique la mise à jour."""
        if self.is_updating:
            raise HomeAssistantError("Une mise à jour est déjà en cours d'exécution.")

        self.is_updating = True
        self.update_progress = 10
        self.update_status_text = "📦 [1/4] Téléchargement de la release GitHub..."

        temp_dir = tempfile.mkdtemp(prefix="domolink_mistral_update_")
        zip_path = os.path.join(temp_dir, "release.zip")

        try:
            # 1. Vérifier la dernière version si nécessaire
            if not self.zip_url or not self.latest_version:
                await self.async_check()

            tag = self.release_tag or f"v{self.latest_version}"
            download_url = (
                self.zip_url
                or f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag}.zip"
            )

            _LOGGER.info(
                "DomoLink-Mistral IA: Téléchargement de la mise à jour %s depuis %s",
                self.latest_version,
                download_url,
            )

            session = async_get_clientsession(self.hass)
            headers = {
                "User-Agent": "HomeAssistant-DomoLinkMistral",
            }
            timeout = aiohttp.ClientTimeout(total=90)
            async with session.get(download_url, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Échec du téléchargement de l'archive ({download_url}) : HTTP {resp.status}"
                    )
                with open(zip_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)

            self.update_progress = 40
            self.update_status_text = "🛡️ [2/4] Création de la sauvegarde locale..."

            # 2. Extraction, sauvegarde et copie sécurisée
            def _apply_in_executor() -> str:
                extract_path = os.path.join(temp_dir, "extracted")
                os.makedirs(extract_path, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(extract_path)

                # Localiser le dossier du composant extrait
                source_component_dir = None
                for root, _dirs, _files in os.walk(extract_path):
                    if os.path.exists(os.path.join(root, "__init__.py")) and os.path.exists(
                        os.path.join(root, "manifest.json")
                    ):
                        try:
                            with open(os.path.join(root, "manifest.json"), "r", encoding="utf-8") as mf:
                                mdata = json.load(mf)
                                if mdata.get("domain") == DOMAIN:
                                    source_component_dir = root
                                    break
                        except Exception:
                            if os.path.basename(root) in (DOMAIN, "DomoLink-Mistral", "domolink_mistral"):
                                source_component_dir = root
                                break

                if not source_component_dir:
                    raise RuntimeError(
                        "L'archive GitHub ne contient pas de structure valide pour DomoLink-Mistral"
                    )

                # Répertoire de destination : le répertoire EXACT où tourne actuellement ce fichier
                target_dir = os.path.abspath(os.path.dirname(__file__))

                # Sauvegarde de sécurité
                if backup:
                    backup_dir = os.path.join(tempfile.gettempdir(), f"{DOMAIN}_last_backup")
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir, ignore_errors=True)
                    shutil.copytree(target_dir, backup_dir, dirs_exist_ok=True)
                    _LOGGER.info("DomoLink-Mistral IA: Sauvegarde créée -> %s", backup_dir)

                # Nettoyer le __pycache__ obsolète
                pycache_dir = os.path.join(target_dir, "__pycache__")
                if os.path.exists(pycache_dir):
                    shutil.rmtree(pycache_dir, ignore_errors=True)

                # Écraser les fichiers avec la nouvelle version
                shutil.copytree(source_component_dir, target_dir, dirs_exist_ok=True)
                _LOGGER.info("DomoLink-Mistral IA: Fichiers mis à jour dans %s", target_dir)

                # Si le dossier standard custom_components/domolink_mistral existe sous un autre nom/chemin, le synchroniser
                try:
                    standard_dir = self.hass.config.path("custom_components", DOMAIN)
                    if os.path.exists(standard_dir) and os.path.abspath(standard_dir) != target_dir:
                        shutil.copytree(source_component_dir, standard_dir, dirs_exist_ok=True)
                except Exception:
                    pass

                # Vérifier la version écrite dans manifest.json
                new_ver = get_installed_version()
                return new_ver

            new_installed_ver = await self.hass.async_add_executor_job(_apply_in_executor)

            self.update_progress = 85
            self.update_status_text = "⚡ [3/4] Fichiers déployés avec succès !"
            self.current_version = new_installed_ver or self.latest_version
            self.has_update = False

            # Étape 3 : Redémarrage de Home Assistant si demandé
            if restart_after:
                self.update_progress = 100
                self.update_status_text = "🔄 [4/4] Redémarrage de Home Assistant..."
                _LOGGER.info("DomoLink-Mistral IA: Mise à jour réussie. Redémarrage de Home Assistant...")

                async def _delayed_restart(_now=None):
                    await asyncio.sleep(1.5)
                    await self.hass.services.async_call("homeassistant", "restart", {})

                self.hass.async_create_task(_delayed_restart())

            self.is_updating = False
            return {
                "success": True,
                "version": self.current_version,
                "message": f"DomoLink-Mistral IA mis à jour vers {self.current_version} !",
                "restarting": restart_after,
            }

        except Exception as e:
            self.is_updating = False
            self.update_status_text = f"❌ Échec de la mise à jour : {e}"
            _LOGGER.error("DomoLink-Mistral IA: Échec de la mise à jour automatique: %s", e, exc_info=True)
            raise HomeAssistantError(f"Échec de la mise à jour : {e}") from e
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
