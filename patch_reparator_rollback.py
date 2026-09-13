import re

with open("custom_components/domolink_mistral/reparator.py", "r") as f:
    content = f.read()

# Store rollbacks
store_rollback_code = """
        except Exception as e:
            return {"success": False, "reason": f"Échec de la sauvegarde préalable: {e}"}

        # Store backup path in hass for rollback
        if "domolink_mistral_rollbacks" not in hass.data:
            hass.data["domolink_mistral_rollbacks"] = []
        hass.data["domolink_mistral_rollbacks"].append({"file": target_path, "backup": backup_path})
"""
content = content.replace('            return {"success": False, "reason": f"Échec de la sauvegarde préalable: {e}"}', store_rollback_code)

rollback_func = """
async def rollback_latest_fix(hass: HomeAssistant) -> dict:
    \"\"\"Annule la dernière modification YAML.\"\"\"
    rollbacks = hass.data.get("domolink_mistral_rollbacks", [])
    if not rollbacks:
        return {"success": False, "reason": "Aucune sauvegarde de fichier récente en mémoire."}
        
    last_rollback = rollbacks.pop()
    target_path = last_rollback["file"]
    backup_path = last_rollback["backup"]
    
    try:
        def do_rollback():
            import shutil, os
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, target_path)
                return True
            return False
            
        success = await hass.async_add_executor_job(do_rollback)
        if success:
            return {"success": True, "message": f"Fichier {os.path.basename(target_path)} restauré avec succès !"}
        else:
            return {"success": False, "reason": "Le fichier de sauvegarde n'existe plus."}
    except Exception as e:
        return {"success": False, "reason": str(e)}

async def apply_fix(hass: HomeAssistant, fix_payload) -> dict:
"""
content = content.replace("async def apply_fix(hass: HomeAssistant, fix_payload) -> dict:", rollback_func)

with open("custom_components/domolink_mistral/reparator.py", "w") as f:
    f.write(content)
