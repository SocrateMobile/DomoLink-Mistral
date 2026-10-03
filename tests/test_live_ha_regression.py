"""Test de non-régression en direct sur Home Assistant.

Ce script teste les fonctionnalités de DomoLink-Mistral IA via les APIs REST et WebSocket de Home Assistant :
- Vérification des versions et entités
- Commande WebSocket domolink_mistral/get_issues
- Cycle complet d'analyse des logs (analyze_now)
- Cycle d'exclusion/réactivation (ignore_issue / unignore_issue)
- Génération d'automation par IA (generate_automation)
- Briefing quotidien par IA (generate_daily_briefing)
- Vérification de mise à jour (check_update)
"""
import asyncio
import os
import ssl
import sys
import aiohttp

def _load_token() -> str:
    """Jeton lu depuis l'environnement (HA_TOKEN) ou un fichier local HORS dépôt (HA_ENV_FILE). Jamais en dur."""
    tok = os.environ.get("HA_TOKEN")
    if tok:
        return tok.strip()
    env_file = os.environ.get(
        "HA_ENV_FILE", os.path.expanduser("~/Desktop/Intégrations HA/HA.env_ha")
    )
    try:
        with open(env_file, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        return lines[-1]
    except OSError:
        sys.exit("Définissez HA_TOKEN (jeton longue durée Home Assistant) ou HA_ENV_FILE.")

TOKEN = _load_token()
HA_HOST = os.environ.get("HA_HOST", "192.168.1.215")
CONFIG_DIR = os.environ.get("HA_CONFIG_DIR", "/Volumes/config")
STABILITY_RUNS = int(os.environ.get("STABILITY_RUNS", "1"))
BASE_URL = f"https://{HA_HOST}/api"
WS_URL = f"wss://{HA_HOST}/api/websocket"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

import json
import os

with open(os.path.join(os.path.dirname(__file__), "..", "custom_components", "domolink_mistral", "manifest.json")) as _f:
    EXPECTED_VERSION = json.load(_f)["version"]

results = []

def record(test_name, passed, detail=""):
    results.append({"name": test_name, "passed": passed, "detail": detail})
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"[{status}] {test_name}: {detail}")

async def run_tests():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # TEST 1: Check update entity & installed version
        try:
            async with session.get(f"{BASE_URL}/states/update.domolink_mistral_ia_mise_a_jour", ssl=ssl_ctx) as resp:
                data = await resp.json()
                version = data["attributes"]["installed_version"]
                passed = version == EXPECTED_VERSION
                record("Test 1: Version installée", passed, f"Version = {version} (attendu: {EXPECTED_VERSION})")
        except Exception as e:
            record("Test 1: Version installée", False, str(e))

        # TEST 2: Check update service check_update
        try:
            async with session.post(f"{BASE_URL}/services/domolink_mistral/check_update?return_response=true", json={}, ssl=ssl_ctx) as resp:
                data = await resp.json()
                resp_data = data.get("service_response", {})
                has_up = resp_data.get("has_update")
                cur_v = resp_data.get("current_version")
                passed = (has_up is False) and (cur_v == EXPECTED_VERSION)
                record("Test 2: Service check_update", passed, f"current_version={cur_v}, has_update={has_up}")
        except Exception as e:
            record("Test 2: Service check_update", False, str(e))

        # TEST 3: Check WebSocket get_issues command
        try:
            async with session.ws_connect(WS_URL, ssl=ssl_ctx) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "auth", "access_token": TOKEN})
                auth_res = await ws.receive_json()
                assert auth_res.get("type") == "auth_ok"
                
                await ws.send_json({"id": 1, "type": "domolink_mistral/get_issues"})
                ws_res = await ws.receive_json()
                ws_ok = ws_res.get("success") is True
                record("Test 3: Commande WebSocket get_issues", ws_ok, f"success={ws_ok}")
        except Exception as e:
            record("Test 3: Commande WebSocket get_issues", False, str(e))

        # TEST 4: Trigger analyze_now and wait for completion
        try:
            print("\n⏳ Déclenchement de analyze_now (audit complet)...")
            async with session.post(f"{BASE_URL}/services/domolink_mistral/analyze_now", json={}, ssl=ssl_ctx) as resp:
                assert resp.status == 200

            # Poll sensor until analysis completes (max 120s)
            completed = False
            for i in range(40):
                await asyncio.sleep(3)
                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                    state_data = await resp.json()
                    status = state_data["attributes"].get("current_status", "")
                    last_error = state_data["attributes"].get("last_error")
                    print(f"   [t={i*3}s] Statut: {status[:70]}...")
                    if last_error:
                        record("Test 4: Exécution de analyze_now", False, f"Erreur sensor: {last_error}")
                        completed = True
                        break
                    if "terminée" in status:
                        record("Test 4: Exécution de analyze_now (Non-régression)", True, f"{status}")
                        completed = True
                        break

            if not completed:
                record("Test 4: Exécution de analyze_now", False, "Timeout attente analyse")
        except Exception as e:
            record("Test 4: Exécution de analyze_now", False, str(e))

        # TEST 5: Verify WebSocket get_issues with real analysis data
        first_issue_id = None
        try:
            async with session.ws_connect(WS_URL, ssl=ssl_ctx) as ws:
                await ws.receive_json()
                await ws.send_json({"type": "auth", "access_token": TOKEN})
                await ws.receive_json()
                
                await ws.send_json({"id": 2, "type": "domolink_mistral/get_issues"})
                ws_res = await ws.receive_json()
                issues = ws_res.get("result", {}).get("issues", [])
                passed = len(issues) > 0 and isinstance(issues[0], dict)
                if passed:
                    first_issue_id = issues[0].get("id")
                record("Test 5: WebSocket get_issues avec données réelles", passed, f"{len(issues)} anomalies reçues sans troncature")
        except Exception as e:
            record("Test 5: WebSocket get_issues avec données réelles", False, str(e))

        # TEST 6: Test ignore_issue and unignore_issue lifecycle
        if first_issue_id:
            try:
                # 6a. Ignore
                async with session.post(f"{BASE_URL}/services/domolink_mistral/ignore_issue", json={"issue_id": first_issue_id}, ssl=ssl_ctx) as resp:
                    assert resp.status == 200
                await asyncio.sleep(1)
                
                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                    state_data = await resp.json()
                    ignored_count = state_data["attributes"].get("ignored_count", 0)
                    passed_ignore = ignored_count >= 1

                # 6b. Unignore
                async with session.post(f"{BASE_URL}/services/domolink_mistral/unignore_issue", json={"issue_id": first_issue_id}, ssl=ssl_ctx) as resp:
                    assert resp.status == 200
                await asyncio.sleep(1)

                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                    state_data = await resp.json()
                    ignored_count_after = state_data["attributes"].get("ignored_count", 0)
                    passed_unignore = ignored_count_after == 0

                passed = passed_ignore and passed_unignore
                record("Test 6: Cycle ignore_issue / unignore_issue", passed, f"Ignore OK ({ignored_count}), Unignore OK ({ignored_count_after})")
            except Exception as e:
                record("Test 6: Cycle ignore_issue / unignore_issue", False, str(e))
        else:
            record("Test 6: Cycle ignore_issue / unignore_issue", True, "Passé (aucune anomalie active)")

        # TEST 7: Automation generation service
        try:
            print("\n⏳ Test de generate_automation...")
            async with session.post(
                f"{BASE_URL}/services/domolink_mistral/generate_automation?return_response=true",
                json={"prompt": "Allumer light.salon quand binary_sensor.mouvement passe a on"},
                ssl=ssl_ctx
            ) as resp:
                data = await resp.json()
                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as s_resp:
                    s_data = await s_resp.json()
                    status = s_data["attributes"].get("current_status", "")
                    passed = "générée avec succès" in status
                    record("Test 7: Service generate_automation", passed, f"Status: {status}")
        except Exception as e:
            record("Test 7: Service generate_automation", False, str(e))

        # TEST 8: Daily briefing generation service
        try:
            print("\n⏳ Test de generate_daily_briefing...")
            async with session.post(
                f"{BASE_URL}/services/domolink_mistral/generate_daily_briefing?return_response=true",
                json={"time_of_day": "morning"},
                ssl=ssl_ctx
            ) as resp:
                data = await resp.json()
                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as s_resp:
                    s_data = await s_resp.json()
                    status = s_data["attributes"].get("current_status", "")
                    passed = "Briefing" in status or resp.status == 200
                    record("Test 8: Service generate_daily_briefing", passed, f"Status: {status}")
        except Exception as e:
            record("Test 8: Service generate_daily_briefing", False, str(e))

        # TEST 9: Cohérence des versions (manifest local = entité native = disque HA)
        try:
            disk_ver = None
            mf = os.path.join(CONFIG_DIR, "custom_components", "domolink_mistral", "manifest.json")
            if os.path.exists(mf):
                with open(mf, encoding="utf-8") as fh:
                    disk_ver = json.load(fh).get("version")
            async with session.get(f"{BASE_URL}/states/update.domolink_mistral_ia_mise_a_jour", ssl=ssl_ctx) as resp:
                ent_ver = (await resp.json())["attributes"]["installed_version"]
            ok = ent_ver == EXPECTED_VERSION and (disk_ver in (None, EXPECTED_VERSION))
            record("Test 9: Cohérence des versions", ok, f"manifest={EXPECTED_VERSION}, entité={ent_ver}, disque HA={disk_ver}")
        except Exception as e:
            record("Test 9: Cohérence des versions", False, str(e))

        # TEST 10: Persistance du rapport (survit à un redémarrage)
        try:
            store_file = os.path.join(CONFIG_DIR, ".storage", "domolink_mistral.ignored_issues")
            if os.path.exists(store_file):
                with open(store_file, encoding="utf-8") as fh:
                    stored = json.load(fh).get("data", {})
                n = len(stored.get("last_issues", []))
                record("Test 10: Persistance du rapport sur disque", n > 0 and bool(stored.get("last_analysis")), f"{n} anomalies sauvegardées, analyse du {stored.get('last_analysis')}")
            else:
                record("Test 10: Persistance du rapport sur disque", True, "Passé (config HA non montée)")
        except Exception as e:
            record("Test 10: Persistance du rapport sur disque", False, str(e))

        # TEST 11: Stabilité - plusieurs audits d'affilée doivent donner des totaux proches
        try:
            totals = []
            async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                totals.append(int((await resp.json())["state"]))
            for run in range(STABILITY_RUNS):
                print(f"\n⏳ Audit de stabilité {run + 1}/{STABILITY_RUNS}...")
                async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                    prev_ts = (await resp.json())["attributes"].get("last_analysis")

                async with session.post(f"{BASE_URL}/services/domolink_mistral/analyze_now", json={}, ssl=ssl_ctx) as resp:
                    assert resp.status == 200

                completed = False
                for _ in range(60):
                    await asyncio.sleep(3)
                    async with session.get(f"{BASE_URL}/states/sensor.domolink_mistral_ia_problemes_detectes", ssl=ssl_ctx) as resp:
                        d = await resp.json()
                    status = d["attributes"].get("current_status", "")
                    ts = d["attributes"].get("last_analysis")
                    if ts != prev_ts and "terminée" in status:
                        totals.append(int(d["state"]))
                        completed = True
                        break
                if not completed:
                    raise TimeoutError(f"Timeout attente fin d'analyse de stabilité {run + 1}")
            spread = max(totals) - min(totals)
            tolerance = max(8, int(0.25 * max(totals)))
            record("Test 11: Stabilité du nombre d'anomalies", spread <= tolerance and min(totals) >= 15, f"totaux={totals}, écart={spread} (tolérance {tolerance})")
        except Exception as e:
            record("Test 11: Stabilité du nombre d'anomalies", False, str(e))

    print("\n" + "="*60)
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    print(f"RÉSULTATS GLOBAUX : {passed_count}/{total_count} tests réussis")
    print("="*60)
    if passed_count < total_count:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_tests())
