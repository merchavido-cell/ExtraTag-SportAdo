import os
import json
import logging
import base64
import hashlib
import threading
import time
import uuid
from pathlib import Path
import ssl
from urllib.request import Request, urlopen
import sys
import tempfile

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.append(str(PROJECT_DIR))

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform
from kivy.clock import Clock

from android.storage import app_storage_path  # type: ignore
from jnius import autoclass, PythonJavaClass, java_method  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)


def get_app_root() -> str:
    android_arg = os.environ.get('ANDROID_ARGUMENT')
    if android_arg:
        return android_arg
    return os.path.join(app_storage_path(), "app")


def find_files_dir() -> str:
    root = get_app_root()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(root, "Extratag_SportAdo", "Files"),
        os.path.join(script_dir, "Files"),
        os.path.join(root, "Files"),
    ]

    for c in candidates:
        if os.path.isdir(c):
            return c

    return candidates[0]


# ============================================================
#                      CONSTANTS & TOKEN
# ============================================================

GITHUB_RAW_URL = "https://raw.githubusercontent.com/merchavido-cell/ExtraTag---Data/main/global_history.json"
GITHUB_API_URL = "https://api.github.com/repos/merchavido-cell/ExtraTag---Data/contents/global_history.json"


def load_github_token() -> str:
    root = get_app_root()
    possible_paths = [
        os.path.join(root, "Extratag_SportAdo", "Secret", "LegendSecret093.txt"),
        os.path.join(root, "Secret", "LegendSecret093.txt"),
        os.path.join(os.environ.get('ANDROID_PRIVATE', ''), "Extratag_SportAdo", "Secret", "LegendSecret093.txt"),
        os.path.join(os.environ.get('ANDROID_PRIVATE', ''), "Secret", "LegendSecret093.txt"),
    ]

    for token_path in possible_paths:
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    token = f.read().strip()
                    logging.info(f"[Init] GitHub Token loaded from {token_path}")
                    return token
            except Exception as e:
                logging.error(f"[Init] Error reading GitHub Token from {token_path}: {e}")

    logging.warning("[Init] LegendSecret093.txt not found in expected paths.")
    return ""


# ============================================================
#                    BACKEND (SportAdo)
# ============================================================

class SportAdoBackend:

    GLOBAL_EXCLUDED_FIELDS = ("is_logged_in", "is_selected")

    @classmethod
    def _strip_local_only_fields(cls, profiles_data: list) -> list:
        cleaned = []
        for p in profiles_data:
            if not isinstance(p, dict):
                continue
            p_clean = {k: v for k, v in p.items() if k not in cls.GLOBAL_EXCLUDED_FIELDS}
            cleaned.append(p_clean)
        return cleaned

    def __init__(self, github_token: str = None):
        self.base_dir = get_app_root()

        self.global_db_path = os.path.join(self.base_dir, "global_history.json")
        self.local_db_path = os.path.join(self.base_dir, "local_history.json")

        self.files_dir = find_files_dir()

        self.github_token = github_token or load_github_token()
        self.last_github_error = None
        self._last_pushed_hash = None
        self._github_push_lock = threading.Lock()

        self._ensure_db_exists()

        self._initial_sync_done = threading.Event()
        threading.Thread(target=self.sync_github_to_local_bg, daemon=True).start()

    # ---------------- File helpers ----------------
    def _ensure_db_exists(self):
        try:
            parent_dir = os.path.dirname(self.global_db_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            if not os.path.exists(self.global_db_path):
                with open(self.global_db_path, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False, indent=4)

            if not os.path.exists(self.local_db_path):
                with open(self.local_db_path, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"[Backend] DB init error: {e}")

    def _load(self, path):
        try:
            if not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except Exception as e:
            logging.error(f"[Backend] Load error from {path}: {e}")
            return []

    def _save(self, path, data):
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass
            raise

    def _parse_input(self, data):
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception:
                return {}
        if isinstance(data, dict):
            return data
        return {}

    def _load_template(self) -> str:
        try:
            template_path = os.path.join(self.files_dir, "template_extgsp.html")
            if not os.path.exists(template_path):
                logging.error(f"[upload_activity] template not found: {template_path}")
                return ""
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logging.error(f"[upload_activity] template load error: {e}")
            return ""

    # ---------------- Load / Save ----------------
    def load_global_history(self) -> list:
        return self._load(self.global_db_path)

    def load_local_history(self) -> list:
        return self._load(self.local_db_path)

    def save_global_history(self, profiles_data: list, push_to_github: bool = True) -> bool:
        try:
            clean_data = self._strip_local_only_fields(profiles_data)
            with open(self.global_db_path, "w", encoding="utf-8") as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=4)
            if push_to_github:
                self.push_global_history_to_github_bg()
            return True
        except Exception as e:
            logging.error(f"[Backend] Save error to global_history.json: {e}")
            return False

    def save_local_history(self, profiles_data: list) -> bool:
        try:
            with open(self.local_db_path, "w", encoding="utf-8") as f:
                json.dump(profiles_data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            logging.error(f"[Backend] Save error to local_history.json: {e}")
            return False

    def _get_fresh_global_profiles(self) -> list:
        fresh = self.fetch_github_profiles()
        if fresh and isinstance(fresh, list):
            return fresh
        return self.load_global_history()

    # ---------------- GitHub ----------------
    def fetch_github_profiles(self) -> list:
        urls_to_try = [("RAW URL", GITHUB_RAW_URL), ("API URL", GITHUB_API_URL)]
        errors = []
        for label, target_url in urls_to_try:
            try:
                req = Request(target_url)
                req.add_header("User-Agent", "Mozilla/5.0 (Windows NT) ExtraTag-SportAdo")
                req.add_header("Accept", "application/vnd.github.v3+json")
                if label == "API URL" and self.github_token and len(self.github_token.strip()) > 5:
                    req.add_header("Authorization", f"token {self.github_token}")

                ctx = ssl._create_unverified_context()
                with urlopen(req, timeout=10, context=ctx) as response:
                    content_text = response.read().decode("utf-8")
                    parsed_json = json.loads(content_text)

                    if isinstance(parsed_json, dict) and "content" in parsed_json and parsed_json.get("encoding") == "base64":
                        file_content = base64.b64decode(parsed_json["content"]).decode("utf-8")
                        parsed_json = json.loads(file_content)

                    if isinstance(parsed_json, list):
                        return parsed_json
            except Exception as e:
                errors.append(f"{label}: {e}")
        self.last_github_error = " | ".join(errors)
        return []

    def _github_get_file_sha(self) -> str:
        try:
            req = Request(GITHUB_API_URL)
            req.add_header("User-Agent", "Mozilla/5.0 ExtraTag-SportAdo")
            req.add_header("Accept", "application/vnd.github.v3+json")
            if self.github_token and len(self.github_token.strip()) > 5:
                req.add_header("Authorization", f"token {self.github_token}")

            ctx = ssl._create_unverified_context()
            with urlopen(req, timeout=10, context=ctx) as response:
                current = json.loads(response.read().decode("utf-8"))
                return current.get("sha")
        except Exception as e:
            logging.info(f"[GitHub Push] Could not fetch current sha: {e}")
            return None

    def _github_put_file(self, content_str: str, commit_message: str) -> dict:
        if not self.github_token or len(self.github_token.strip()) <= 5:
            msg = "Missing/invalid GitHub token - cannot push update."
            logging.error(f"[GitHub Push] {msg}")
            self.last_github_error = msg
            return {"success": False, "error": msg}

        try:
            sha = self._github_get_file_sha()
            encoded_content = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
            payload = {"message": commit_message, "content": encoded_content}
            if sha:
                payload["sha"] = sha

            body_bytes = json.dumps(payload).encode("utf-8")

            req = Request(GITHUB_API_URL, data=body_bytes, method="PUT")
            req.add_header("User-Agent", "Mozilla/5.0 ExtraTag-SportAdo")
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("Authorization", f"token {self.github_token}")
            req.add_header("Content-Type", "application/json")

            ctx = ssl._create_unverified_context()
            with urlopen(req, timeout=15, context=ctx) as response:
                result = json.loads(response.read().decode("utf-8"))
                logging.info("[GitHub Push] global_history.json updated successfully.")
                return {"success": True, "result": result}
        except Exception as e:
            err = str(e)
            logging.error(f"[GitHub Push] Failed: {err}")
            self.last_github_error = err
            return {"success": False, "error": err}

    def push_global_history_to_github(self, commit_message: str = "SportAdo: add activity") -> dict:
        with self._github_push_lock:
            profiles = self.load_global_history()
            content_str = json.dumps(profiles, ensure_ascii=False, indent=4)

            content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
            if content_hash == self._last_pushed_hash:
                logging.info("[GitHub Push] No changes since last push - skipping.")
                return {"success": True, "skipped": True}

            result = self._github_put_file(content_str, commit_message)
            if result.get("success"):
                self._last_pushed_hash = content_hash
            return result

    def push_global_history_to_github_bg(self, commit_message: str = "SportAdo: update"):
        def worker():
            self.push_global_history_to_github(commit_message)
        threading.Thread(target=worker, daemon=True).start()

    def sync_github_to_local_bg(self):
        try:
            github_profiles = self.fetch_github_profiles()
            if github_profiles and isinstance(github_profiles, list):
                self.save_global_history(github_profiles, push_to_github=False)
                self._update_local_profiles_from_github(github_profiles)
        except Exception as e:
            logging.error(f"[Sync Error] {e}")
        finally:
            self._initial_sync_done.set()

    def _update_local_profiles_from_github(self, github_profiles: list) -> bool:
        LOCAL_ONLY_FIELDS = ("is_logged_in", "is_selected")
        try:
            local_profiles = self.load_local_history()
            if not local_profiles:
                return False
            local_by_id = {str(p.get("id")): p for p in local_profiles if p.get("id") is not None}
            updated_any = False

            for gp in github_profiles:
                gid = gp.get("id")
                if gid is None:
                    continue
                lp = local_by_id.get(str(gid))
                if lp is None:
                    continue
                for key, val in gp.items():
                    if key in LOCAL_ONLY_FIELDS:
                        continue
                    if lp.get(key) != val:
                        lp[key] = val
                        updated_any = True

            if updated_any:
                return self.save_local_history(local_profiles)
            return False
        except Exception:
            return False

    # ============================================================
    #                  LOGIN / LOGOUT
    # ============================================================
    @staticmethod
    def _is_logged_in(profile: dict) -> bool:
        value = profile.get("is_logged_in", False)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return False

    def get_logged_in_user(self) -> dict:
        try:
            for profile in self.load_local_history():
                if self._is_logged_in(profile):
                    safe_profile = {
                        k: v for k, v in profile.items()
                        if k not in ("password", "confirmPassword", "expass", "files", "sent_emails", "class_history")
                    }
                    return {"success": True, "profile": safe_profile}
            return {"success": False, "error": "No logged in user found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_logged_in_user(self, matched_profile: dict) -> dict:
        try:
            local_profiles = self.load_local_history()
            matched_id = str(matched_profile.get("id"))
            found = False

            for profile in local_profiles:
                if str(profile.get("id")) == matched_id:
                    profile["is_logged_in"] = True
                    found = True
                else:
                    profile["is_logged_in"] = False

            if not found:
                new_profile = matched_profile.copy()
                new_profile["is_logged_in"] = True
                local_profiles.append(new_profile)

            if not self.save_local_history(local_profiles):
                return {"success": False, "error": "Failed to save local history."}

            saved_profiles = self.load_local_history()
            logged_in_profiles = [p for p in saved_profiles if self._is_logged_in(p)]

            if len(logged_in_profiles) != 1:
                return {"success": False, "error": "Could not establish unique logged-in user."}

            matched = logged_in_profiles[0]
            safe_profile = {
                k: v for k, v in matched.items()
                if k not in ("password", "confirmPassword", "expass")
            }
            return {"success": True, "profile": safe_profile}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def login_from_local(self, email_input: str, password_input: str) -> dict:
        try:
            email_clean = str(email_input or "").strip().lower()
            password_clean = str(password_input or "").strip()
            local_profiles = self.load_local_history()

            if not local_profiles and not self._initial_sync_done.is_set():
                self._initial_sync_done.wait(timeout=8)
                local_profiles = self.load_local_history()

            if not local_profiles:
                github_profiles = self.fetch_github_profiles()
                if github_profiles:
                    self.save_global_history(github_profiles, push_to_github=False)
                    local_profiles = github_profiles
                else:
                    return {"success": False, "error": "GitHub connection failed."}

            matched_user = None
            for profile in local_profiles:
                if (email_clean == str(profile.get("email") or "").strip().lower() or
                    email_clean == str(profile.get("exmail") or "").strip().lower()) and \
                   (password_clean == str(profile.get("password") or "").strip() or
                    password_clean == str(profile.get("expass") or "").strip()):
                    matched_user = profile
                    break

            if not matched_user:
                return {"success": False, "error": "Invalid email or password."}

            return self.set_logged_in_user(matched_user)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def login_from_github(self, email_input: str, password_input: str) -> dict:
        return self.login_from_local(email_input, password_input)

    def logout(self) -> dict:
        try:
            local_profiles = self.load_local_history()
            for profile in local_profiles:
                profile["is_logged_in"] = False
            self.save_local_history(local_profiles)
            return {"success": True, "message": "Logged out."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================
    #                  ACTIVITY → files
    # ============================================================
    def upload_activity(self, activity_payload) -> dict:
        try:
            activity = self._parse_input(activity_payload)
            if not isinstance(activity, dict):
                return {"success": False, "error": "Invalid activity data"}

            sport = str(activity.get("sport", "")).strip().lower()
            if sport not in ("run", "bike", "walk", "duathlon", "navigate", "strength"):
                return {"success": False, "error": f"Unknown sport: {sport}"}

            # ---- זיהוי הפרופיל המחובר ----
            local_profiles = self.load_local_history()
            active_local = None
            for p in local_profiles:
                if self._is_logged_in(p):
                    active_local = p
                    break

            if not active_local:
                return {"success": False, "error": "No logged-in user"}

            active_email = str(active_local.get("email", "")).strip().lower()
            active_id = str(active_local.get("id", "")).strip()

            # ---- בניית שם קובץ ----
            file_name = str(activity.get("file_name") or "").strip()
            if not file_name:
                ts = time.strftime("%Y-%m-%d_%H-%M")
                file_name = f"{sport}_{ts}_{uuid.uuid4().hex[:6]}.extgsp.html"

            if not file_name.endswith(".extgsp.html"):
                base = file_name
                for suffix in (".extgsp", ".html"):
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                file_name = base + ".extgsp.html"

            # ---- טעינת התבנית ----
            template = self._load_template()
            if not template:
                return {"success": False, "error": "Template not found"}

            # ---- בניית נתוני הפעילות ----
            activity_data = {
                "version": "1.0",
                "sport": sport,
                "title": activity.get("title") or f"{sport.capitalize()} activity",
                "started_at": activity.get("started_at"),
                "ended_at": activity.get("ended_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                "duration_seconds": int(activity.get("duration_seconds", 0)),
                "distance_meters": float(activity.get("distance_meters", 0)),
                "avg_speed_kmh": float(activity.get("avg_speed_kmh", 0)),
                "max_speed_kmh": float(activity.get("max_speed_kmh", 0)),
                "calories": int(activity.get("calories", 0)),
                "elevation_gain_m": float(activity.get("elevation_gain_m", 0)),
                "route": activity.get("route", []) or [],
                "route_compact": activity.get("route_compact", "") or "",
                "notes": str(activity.get("notes", ""))[:500],
            }

            # ---- הכנת ערכים לתבנית ----
            title = activity_data["title"]
            date_str = ""
            time_str = ""
            try:
                if activity_data.get("started_at"):
                    dt = time.strptime(activity_data["started_at"][:19], "%Y-%m-%dT%H:%M:%S")
                    date_str = time.strftime("%d/%m/%Y", dt)
                    time_str = time.strftime("%H:%M", dt)
            except Exception:
                pass

            sport_names = {
                "run": "Run", "bike": "Bike", "walk": "Walk",
                "duathlon": "Duathlon", "navigate": "Navigate", "strength": "Strength"
            }
            sport_label = sport_names.get(sport, sport.capitalize())

            # ---- החלפת placeholders ----
            html_content = template
            html_content = html_content.replace("{{TITLE}}", str(title))
            html_content = html_content.replace("{{SPORT}}", sport)
            html_content = html_content.replace("{{SPORT_LABEL}}", sport_label)
            html_content = html_content.replace("{{DATE}}", date_str)
            html_content = html_content.replace("{{TIME}}", time_str)
            html_content = html_content.replace(
                "{{ACTIVITY_JSON}}",
                json.dumps(activity_data, ensure_ascii=False)
            )

            # ---- קידוד base64 ----
            html_bytes = html_content.encode("utf-8")
            b64 = base64.b64encode(html_bytes).decode("ascii")
            data_url = f"data:text/html;base64,{b64}"

            new_file_entry = {
                "file_name": file_name,
                "file_size": len(html_bytes),
                "file_data": data_url
            }

            # ---- הוספה ל-local_history.json ----
            for p in local_profiles:
                if str(p.get("id", "")) == active_id or str(p.get("email", "")).strip().lower() == active_email:
                    files = p.get("files", [])
                    if not isinstance(files, list):
                        files = []
                    files.append(new_file_entry)
                    p["files"] = files
                    break
            self.save_local_history(local_profiles)

            # ---- הוספה ל-global_history.json ----
            global_profiles = self._get_fresh_global_profiles()
            updated = False
            for gp in global_profiles:
                gp_id = str(gp.get("id", "")).strip()
                gp_email = str(gp.get("email", "")).strip().lower()
                if gp_id == active_id or (active_email and gp_email == active_email):
                    files = gp.get("files", [])
                    if not isinstance(files, list):
                        files = []
                    files.append(new_file_entry)
                    gp["files"] = files
                    updated = True
                    break

            if not updated:
                prof_copy = active_local.copy()
                files = prof_copy.get("files", [])
                if not isinstance(files, list):
                    files = []
                files.append(new_file_entry)
                prof_copy["files"] = files
                global_profiles.append(prof_copy)

            self.save_global_history(global_profiles, push_to_github=True)

            return {
                "success": True,
                "file_name": file_name,
                "file_size": len(html_bytes)
            }

        except Exception as e:
            logging.error(f"[upload_activity] Error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    # ============================================================
    #                  HISTORY / OPEN / DELETE
    # ============================================================
    def get_app_activities(self) -> dict:
        try:
            active = None
            for p in self.load_local_history():
                if self._is_logged_in(p):
                    active = p
                    break
            if not active:
                return {"success": False, "error": "No logged-in user", "activities": []}

            files = active.get("files", []) or []
            activities = [f for f in files
                          if isinstance(f, dict) and str(f.get("file_name", "")).endswith(".extgsp.html")]

            activities = list(reversed(activities))

            summaries = []
            for f in activities:
                summaries.append({
                    "file_name": f.get("file_name"),
                    "file_size": f.get("file_size", 0)
                })

            return {"success": True, "activities": summaries}
        except Exception as e:
            logging.error(f"[get_app_activities] Error: {e}")
            return {"success": False, "error": str(e), "activities": []}

    def open_activity_file(self, file_name: str) -> dict:
        try:
            active = None
            for p in self.load_local_history():
                if self._is_logged_in(p):
                    active = p
                    break
            if not active:
                return {"success": False, "error": "No logged-in user"}

            for f in (active.get("files") or []):
                if not isinstance(f, dict):
                    continue
                if f.get("file_name") == file_name:
                    data_url = str(f.get("file_data", ""))
                    if not data_url.startswith("data:"):
                        return {"success": False, "error": "Invalid file data"}
                    header, b64 = data_url.split(",", 1)
                    html = base64.b64decode(b64).decode("utf-8")
                    return {"success": True, "html": html}
            return {"success": False, "error": "File not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_activity_file(self, file_name: str) -> dict:
        try:
            local_profiles = self.load_local_history()
            active = None
            for p in local_profiles:
                if self._is_logged_in(p):
                    active = p
                    break
            if not active:
                return {"success": False, "error": "No logged-in user"}

            active_id = str(active.get("id", "")).strip()
            active_email = str(active.get("email", "")).strip().lower()

            for p in local_profiles:
                if str(p.get("id", "")) == active_id:
                    p["files"] = [f for f in (p.get("files") or [])
                                  if not (isinstance(f, dict) and f.get("file_name") == file_name)]
                    break
            self.save_local_history(local_profiles)

            global_profiles = self._get_fresh_global_profiles()
            for gp in global_profiles:
                gp_id = str(gp.get("id", "")).strip()
                gp_email = str(gp.get("email", "")).strip().lower()
                if gp_id == active_id or (active_email and gp_email == active_email):
                    gp["files"] = [f for f in (gp.get("files") or [])
                                   if not (isinstance(f, dict) and f.get("file_name") == file_name)]
                    break

            self.save_global_history(global_profiles, push_to_github=True)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================
    #                  NAVIGATION (called from JS)
    # ============================================================
    def navigate_to(self, filename: str, title: str = None) -> dict:
        try:
            app = App.get_running_app()
            if app and hasattr(app, "navigate_to_file"):
                app.navigate_to_file(filename, title)
                return {"success": True}
            return {"success": False, "error": "App not available"}
        except Exception as e:
            logging.error(f"[navigate_to] Error: {e}")
            return {"success": False, "error": str(e)}

    # ============================================================
    #                  WAKE LOCK (keep screen on during activity)
    # ============================================================
    def keep_screen_on(self) -> dict:
        """
        לא נותן למסך להיכבות בזמן הקלטת פעילות.
        נקרא מ-JS כשהמשתמש לוחץ Start.
        """
        if platform != 'android':
            return {"success": False, "error": "Not Android"}

        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity

            def _add_flag(dt=None):
                try:
                    # WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON = 0x00000080
                    activity.getWindow().addFlags(0x00000080)
                    logging.info("[WakeLock] FLAG_KEEP_SCREEN_ON added")
                except Exception as e:
                    logging.error(f"[WakeLock] add flag error: {e}")

            activity.runOnUiThread(_add_flag)
            return {"success": True}
        except Exception as e:
            logging.error(f"[keep_screen_on] Error: {e}")
            return {"success": False, "error": str(e)}

    def release_screen_on(self) -> dict:
        """
        מאפשר למסך להיכבות שוב. נקרא מ-JS כשלוחצים Stop/Save.
        """
        if platform != 'android':
            return {"success": False, "error": "Not Android"}

        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity

            def _clear_flag(dt=None):
                try:
                    activity.getWindow().clearFlags(0x00000080)
                    logging.info("[WakeLock] FLAG_KEEP_SCREEN_ON cleared")
                except Exception as e:
                    logging.error(f"[WakeLock] clear flag error: {e}")

            activity.runOnUiThread(_clear_flag)
            return {"success": True}
        except Exception as e:
            logging.error(f"[release_screen_on] Error: {e}")
            return {"success": False, "error": str(e)}


# ============================================================
#                    ANDROID UI HELPER
# ============================================================

class _UiThreadRunnable(PythonJavaClass):
    __javainterfaces__ = ['java/lang/Runnable']
    __javacontext__ = 'app'

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    @java_method('()V')
    def run(self):
        try:
            self.callback()
        except Exception as e:
            logging.error(f"[UiThreadRunnable Error] {e}")


# ============================================================
#                        APP
# ============================================================

class SportAdoApp(App):

    def build(self):
        self.backend = SportAdoBackend()
        self.webview = None
        self.is_processing_bridge = False
        self.ui_handler = None
        self._bridge_runnable = None
        self._bridge_running = False
        return BoxLayout()

    def on_start(self):
        Clock.schedule_once(lambda dt: self._request_location_permissions(), 0.3)
        Clock.schedule_once(lambda dt: self._request_notification_permission(), 0.6)
        Clock.schedule_once(lambda dt: self.load_webview_android(), 1.0)

    # ---------------- Permissions ----------------
    def _request_location_permissions(self):
        if platform != 'android':
            return
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ContextCompat = autoclass('androidx.core.content.ContextCompat')
            ActivityCompat = autoclass('androidx.core.app.ActivityCompat')
            PackageManager = autoclass('android.content.pm.PackageManager')

            activity = PythonActivity.mActivity
            perms = [
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.ACCESS_COARSE_LOCATION",
            ]
            missing = [p for p in perms
                       if ContextCompat.checkSelfPermission(activity, p) != PackageManager.PERMISSION_GRANTED]
            if missing:
                ActivityCompat.requestPermissions(activity, missing, 1003)
                logging.info(f"[Permissions] Requested location: {missing}")
        except Exception as e:
            logging.error(f"[Permissions] Location error: {e}")

    def _request_notification_permission(self):
        if platform != 'android':
            return
        try:
            Build = autoclass('android.os.Build')
            if Build.VERSION.SDK_INT < 33:
                return
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            ContextCompat = autoclass('androidx.core.content.ContextCompat')
            ActivityCompat = autoclass('androidx.core.app.ActivityCompat')
            PackageManager = autoclass('android.content.pm.PackageManager')

            activity = PythonActivity.mActivity
            perm = "android.permission.POST_NOTIFICATIONS"
            if ContextCompat.checkSelfPermission(activity, perm) != PackageManager.PERMISSION_GRANTED:
                ActivityCompat.requestPermissions(activity, [perm], 1001)
        except Exception as e:
            logging.error(f"[Permissions] Notifications error: {e}")

    # ---------------- Bridge ----------------
    def check_js_bridge_messages(self):
        if not self.webview or self.is_processing_bridge or not self._bridge_running:
            return
        try:
            title = str(self.webview.getTitle() or "")
            if title.startswith("PY_BRIDGE:"):
                self.is_processing_bridge = True
                payload = title.replace("PY_BRIDGE:", "", 1)
                self.webview.evaluateJavascript("document.title = '';", None)

                def worker():
                    try:
                        data = json.loads(payload)
                        action = data.get("action")
                        args = data.get("args", [])
                        callback = data.get("callback")

                        func = getattr(self.backend, action, None)
                        if callable(func):
                            res = func(*args)
                        else:
                            res = {"success": False, "error": f"Method {action} not found"}

                        js_code = f"window['{callback}']({json.dumps(res, ensure_ascii=False)});"

                        def return_to_js():
                            try:
                                if self.webview:
                                    self.webview.evaluateJavascript(js_code, None)
                            finally:
                                self.is_processing_bridge = False

                        self._post_to_ui_thread(return_to_js)
                    except Exception as err:
                        logging.error(f"[Bridge Worker Error] {err}")
                        self.is_processing_bridge = False

                threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            logging.error(f"[Bridge Polling Error] {e}")
            self.is_processing_bridge = False

    def _post_to_ui_thread(self, cb):
        if not self.ui_handler:
            return
        self.ui_handler.post(_UiThreadRunnable(cb))

    def _start_bridge_polling(self, interval_ms: int = 50):
        Handler = autoclass('android.os.Handler')
        Looper = autoclass('android.os.Looper')
        if self.ui_handler is None:
            self.ui_handler = Handler(Looper.getMainLooper())
        self._bridge_running = True

        def tick():
            if not self._bridge_running:
                return
            self.check_js_bridge_messages()
            if self._bridge_running and self.ui_handler:
                self._bridge_runnable = _UiThreadRunnable(tick)
                self.ui_handler.postDelayed(self._bridge_runnable, interval_ms)

        self._bridge_runnable = _UiThreadRunnable(tick)
        self.ui_handler.post(self._bridge_runnable)

    def stop_bridge_polling(self):
        self._bridge_running = False

    # ---------------- Navigation ----------------
    def navigate_to_file(self, filename: str, title: str = None):
        if platform != 'android' or not self.webview:
            return
        try:
            files_dir = find_files_dir()
            html_path = os.path.join(files_dir, filename)
            if not os.path.exists(html_path):
                logging.error(f"[Navigate] File not found: {html_path}")
                return

            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity

            def do_nav(dt=None):
                try:
                    if self.webview:
                        self.webview.loadUrl(f"file://{html_path}")
                        logging.info(f"[Navigate] Loaded: {html_path}")
                except Exception as e:
                    logging.error(f"[Navigate] Load error: {e}")

            activity.runOnUiThread(do_nav)
        except Exception as e:
            logging.error(f"[Navigate Error] {e}")

    # ---------------- WebView ----------------
    def load_webview_android(self):
        if platform != 'android':
            logging.info("[UI] Not on Android - WebView skipped.")
            return

        try:
            WebView = autoclass('android.webkit.WebView')
            WebViewClient = autoclass('android.webkit.WebViewClient')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity

            files_dir = find_files_dir()
            html_path = os.path.join(files_dir, "index.html")

            if not os.path.exists(html_path):
                logging.error(f"[UI] index.html not found in {files_dir}")
                return

            logging.info(f"[UI] FOUND HTML at: {html_path}")

            def setup_webview(dt=None):
                try:
                    self.webview = WebView(activity)
                    settings = self.webview.getSettings()
                    settings.setJavaScriptEnabled(True)
                    settings.setAllowFileAccess(True)
                    settings.setAllowFileAccessFromFileURLs(True)
                    settings.setAllowUniversalAccessFromFileURLs(True)
                    settings.setDomStorageEnabled(True)
                    settings.setGeolocationEnabled(True)
                    settings.setMediaPlaybackRequiresUserGesture(False)

                    try:
                        JavaWebChromeClient = autoclass('org.extratag.extratagvcall.CustomWebChromeClient')
                        self.webview.setWebChromeClient(JavaWebChromeClient(activity))
                        logging.info("[UI] Custom Java WebChromeClient attached.")
                    except Exception as e:
                        logging.error(f"[UI] WebChromeClient setup error: {e}")

                    self.webview.setWebViewClient(WebViewClient())
                    self.webview.loadUrl(f"file://{html_path}")
                    activity.setContentView(self.webview)

                    self._start_bridge_polling(50)
                    logging.info(f"[UI] WebView loaded: {html_path}")
                except Exception as inner_e:
                    logging.error(f"[UI] setup_webview error: {inner_e}")

            activity.runOnUiThread(setup_webview)

        except Exception as e:
            logging.error(f"[UI] load_webview_android error: {e}")

    def on_stop(self):
        self.stop_bridge_polling()


if __name__ == '__main__':
    SportAdoApp().run()