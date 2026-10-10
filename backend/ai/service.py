from __future__ import annotations

import json
import sqlite3
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable, Mapping, Sequence

from backend.ai.crypto import EncryptedProviderKey, ProviderKeyCipher
from backend.ai.provider import ProviderConfig, ProviderFailure, PinnedChatCompletionsTransport, _resolve_public, validate_base_url
from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database


class AIModelError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__(code)


class AIProviderService:
    def __init__(self, *, database_path: Path, busy_timeout_ms: int, keyring: CredentialKeyring,
                 service_default: Mapping[str, object] | None = None, transport=None,
                 clock: Callable[[], int] | None = None, resolver: Callable[[str], list[str]] = _resolve_public,
                 destination_validator: Callable[[str], None] | None = None):
        self.database_path, self.busy_timeout_ms, self.keyring = Path(database_path), busy_timeout_ms, keyring
        self.cipher = ProviderKeyCipher(keyring)
        self.transport = transport or PinnedChatCompletionsTransport()
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.resolver = resolver
        self.destination_validator = destination_validator or self._production_validate_destination
        self.service_default = self._service_config(service_default)

    @staticmethod
    def _service_config(raw: Mapping[str, object] | None) -> ProviderConfig | None:
        if not isinstance(raw, Mapping):
            return None
        base, model, auth_mode, protocol = (raw.get(k) for k in ("base_url", "model", "auth_mode", "protocol"))
        key = raw.get("api_key")
        if not all(isinstance(v, str) and v for v in (base, model, auth_mode, protocol)) or protocol != "openai-chat-completions":
            return None
        if auth_mode not in {"bearer", "none"} or (auth_mode == "bearer" and (not isinstance(key, str) or not key)):
            return None
        try:
            base = validate_base_url(base)
        except ProviderFailure:
            return None
        return ProviderConfig("service_default", "Service default", base, model, auth_mode,
                              key if auth_mode == "bearer" else None, 1, "service")

    def _db(self):
        return connect_database(self.database_path, self.busy_timeout_ms)

    @staticmethod
    def _validate_fields(name, base_url, model, auth_mode, api_key=None, *, require_api_key=True):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128 or any(unicodedata.category(c) in {"Cc", "Cs"} for c in name):
            raise AIModelError("invalid_provider_config", 400)
        if not isinstance(model, str) or not model.strip() or len(model.strip()) > 256 or any(unicodedata.category(c) in {"Cc", "Cs"} for c in model):
            raise AIModelError("invalid_provider_config", 400)
        try:
            normalized_url = validate_base_url(base_url)
        except ProviderFailure as exc:
            raise AIModelError(exc.code, exc.status) from None
        if not isinstance(auth_mode, str) or auth_mode not in {"bearer", "none"}:
            raise AIModelError("invalid_provider_config", 400)
        if auth_mode == "none" and api_key is not None:
            raise AIModelError("invalid_provider_config", 400)
        if api_key is not None:
            try:
                api_key_bytes = api_key.encode("utf-8") if isinstance(api_key, str) else b""
            except UnicodeEncodeError:
                raise AIModelError("invalid_provider_config", 400) from None
            if not isinstance(api_key, str) or not api_key or len(api_key_bytes) > 8192 or any(ord(c) < 32 for c in api_key):
                raise AIModelError("invalid_provider_config", 400)
        if require_api_key and auth_mode == "bearer" and api_key is None:
            raise AIModelError("provider_api_key_required", 400)
        return name.strip(), normalized_url, model.strip(), auth_mode

    def _production_validate_destination(self, base_url: str) -> None:
        from urllib.parse import urlsplit
        try:
            self.resolver(urlsplit(base_url).hostname or "")
        except ProviderFailure as exc:
            raise AIModelError(exc.code, exc.status) from None

    def _validate_destination(self, base_url: str) -> None:
        self.destination_validator(base_url)

    @staticmethod
    def _dto(row, has_key=None):
        return {"id": row["model_id"], "name": row["name"], "base_url": row["base_url"],
                "model": row["model"], "auth_mode": row["auth_mode"],
                "has_api_key": bool(row["api_key_ciphertext"] is not None) if has_key is None else has_key,
                "version": row["version"], "source": "user"}

    def list_models(self, user_id: str) -> dict:
        db = self._db()
        try:
            rows = db.execute("SELECT * FROM ai_models WHERE user_id=? ORDER BY created_at_utc_ms,model_id", (user_id,)).fetchall()
            prefs = db.execute("SELECT selected_model_id,default_model_id FROM ai_model_preferences WHERE user_id=?", (user_id,)).fetchone()
            models = [self._dto(row) for row in rows]
            selected = prefs["selected_model_id"] if prefs else None
            default = prefs["default_model_id"] if prefs else None
            selected_exists = selected == "service_default" or any(row["model_id"] == selected for row in rows)
            default_exists = default == "service_default" or any(row["model_id"] == default for row in rows)
            effective = selected if selected_exists else (default if default_exists else ("service_default" if self.service_default else None))
            return {"models": models, "service_default": self.service_default.public() if self.service_default else None,
                    "selected_model_id": selected, "default_model_id": default,
                    "effective_model_id": effective}
        finally:
            db.close()

    def create(self, user_id, name, base_url, model, auth_mode, api_key=None):
        name, base_url, model, auth_mode = self._validate_fields(name, base_url, model, auth_mode, api_key)
        self._validate_destination(base_url)
        model_id, revision, now = str(uuid.uuid4()), str(uuid.uuid4()), self.clock()
        envelope = self.cipher.encrypt(api_key.encode(), user_id=user_id, model_id=model_id, revision=revision,
                                        key_id=self.keyring.active_key_id) if api_key is not None else None
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO ai_models(model_id,user_id,name,base_url,model,auth_mode,api_key_ciphertext,
                api_key_nonce,api_key_tag,encryption_key_id,key_revision,version,created_at_utc_ms,updated_at_utc_ms)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (model_id,user_id,name,base_url,model,auth_mode,
                envelope.ciphertext if envelope else None,envelope.nonce if envelope else None,envelope.tag if envelope else None,
                envelope.key_id if envelope else None,revision,1,now,now))
            db.execute("COMMIT")
            return {"id": model_id, "name": name, "base_url": base_url, "model": model, "auth_mode": auth_mode,
                    "has_api_key": envelope is not None, "version": 1, "source": "user"}
        except sqlite3.Error:
            if db.in_transaction: db.execute("ROLLBACK")
            raise AIModelError("provider_storage_unavailable", 503) from None
        finally:
            db.close()

    def update(self, user_id, model_id, body: Mapping[str, object]):
        if "api_key" in body and (not isinstance(body["api_key"], str) or not body["api_key"]):
            raise AIModelError("invalid_provider_config", 400)
        name, base, model, auth = self._validate_fields(body.get("name"), body.get("base_url"), body.get("model"), body.get("auth_mode"), body.get("api_key"), require_api_key=False)
        self._validate_destination(base)
        delete_key = body.get("delete_api_key", False)
        if type(delete_key) is not bool or (delete_key and "api_key" in body):
            raise AIModelError("invalid_request", 400)
        revision, now = str(uuid.uuid4()), self.clock()
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ai_models WHERE user_id=? AND model_id=?", (user_id,model_id)).fetchone()
            if row is None: raise AIModelError("provider_not_found", 404)
            if type(body.get("base_version")) is not int or body["base_version"] != row["version"]:
                raise AIModelError("provider_version_conflict", 409)
            key_present = row["api_key_ciphertext"] is not None
            replacing = "api_key" in body
            if base != row["base_url"] and key_present and not (replacing or delete_key):
                raise AIModelError("provider_key_action_required", 409)
            if auth == "none" and key_present and not delete_key:
                raise AIModelError("provider_key_action_required", 409)
            envelope = None
            if replacing:
                envelope = self.cipher.encrypt(body["api_key"].encode(), user_id=user_id, model_id=model_id,
                                               revision=revision, key_id=self.keyring.active_key_id)
            elif key_present and not delete_key:
                # Re-encrypt to bind ciphertext to each new key revision.
                previous = EncryptedProviderKey(bytes(row["api_key_ciphertext"]), bytes(row["api_key_nonce"]),
                                                bytes(row["api_key_tag"]), row["encryption_key_id"])
                secret = self.cipher.decrypt(previous, user_id=user_id, model_id=model_id, revision=row["key_revision"])
                envelope = self.cipher.encrypt(secret, user_id=user_id, model_id=model_id, revision=revision,
                                               key_id=self.keyring.active_key_id)
            db.execute("""UPDATE ai_models SET name=?,base_url=?,model=?,auth_mode=?,api_key_ciphertext=?,api_key_nonce=?,
                api_key_tag=?,encryption_key_id=?,key_revision=?,version=version+1,updated_at_utc_ms=?
                WHERE user_id=? AND model_id=? AND version=?""", (name,base,model,auth,
                envelope.ciphertext if envelope else None,envelope.nonce if envelope else None,envelope.tag if envelope else None,
                envelope.key_id if envelope else None,revision,now,user_id,model_id,body["base_version"]))
            db.execute("COMMIT")
            return {"id":model_id,"name":name,"base_url":base,"model":model,"auth_mode":auth,
                    "has_api_key": envelope is not None,"version":row["version"]+1,"source":"user"}
        except AIModelError:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        except (sqlite3.Error, ValueError):
            if db.in_transaction: db.execute("ROLLBACK")
            raise AIModelError("provider_storage_unavailable", 503) from None
        finally: db.close()

    def delete(self, user_id, model_id, base_version):
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM ai_models WHERE user_id=? AND model_id=?", (user_id,model_id)).fetchone()
            if row is None: raise AIModelError("provider_not_found",404)
            if type(base_version) is not int or row["version"] != base_version: raise AIModelError("provider_version_conflict",409)
            db.execute("""UPDATE ai_model_preferences
                SET selected_model_id=CASE WHEN selected_model_id=? THEN NULL ELSE selected_model_id END,
                    default_model_id=CASE WHEN default_model_id=? THEN NULL ELSE default_model_id END
                WHERE user_id=?""", (model_id,model_id,user_id))
            db.execute("DELETE FROM ai_models WHERE user_id=? AND model_id=? AND version=?", (user_id,model_id,base_version))
            db.execute("COMMIT")
        except AIModelError:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        except sqlite3.Error:
            if db.in_transaction: db.execute("ROLLBACK")
            raise AIModelError("provider_storage_unavailable",503) from None
        finally: db.close()

    def set_preferences(self, user_id, selected, default):
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            for model_id in (selected,default):
                if model_id is not None and not isinstance(model_id, str):
                    raise AIModelError("invalid_request",400)
                if model_id == "service_default" and self.service_default is None:
                    raise AIModelError("provider_not_found",404)
                if model_id is not None and model_id != "service_default":
                    if db.execute("SELECT 1 FROM ai_models WHERE user_id=? AND model_id=?",(user_id,model_id)).fetchone() is None:
                        raise AIModelError("provider_not_found",404)
            db.execute("""INSERT INTO ai_model_preferences(user_id,selected_model_id,default_model_id,updated_at_utc_ms) VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET selected_model_id=excluded.selected_model_id,
                default_model_id=excluded.default_model_id,updated_at_utc_ms=excluded.updated_at_utc_ms""",
                (user_id,selected,default,self.clock()))
            db.execute("COMMIT")
        except AIModelError:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        except sqlite3.Error:
            if db.in_transaction: db.execute("ROLLBACK")
            raise AIModelError("provider_storage_unavailable",503) from None
        finally: db.close()

    def _config(self, row):
        key = None
        if row["api_key_ciphertext"] is not None:
            env = EncryptedProviderKey(bytes(row["api_key_ciphertext"]),bytes(row["api_key_nonce"]),bytes(row["api_key_tag"]),row["encryption_key_id"])
            try: key = self.cipher.decrypt(env,user_id=row["user_id"],model_id=row["model_id"],revision=row["key_revision"]).decode("utf-8")
            except (ValueError,UnicodeDecodeError): raise AIModelError("provider_secret_unavailable",503) from None
        if row["auth_mode"] == "bearer" and key is None:
            raise AIModelError("provider_api_key_required",409)
        return ProviderConfig(row["model_id"],row["name"],row["base_url"],row["model"],row["auth_mode"],key,row["version"],"user")

    def resolve(self, user_id: str) -> tuple[ProviderConfig, dict] | None:
        db = self._db()
        try:
            pref = db.execute("SELECT selected_model_id,default_model_id FROM ai_model_preferences WHERE user_id=?", (user_id,)).fetchone()
            selected = pref["selected_model_id"] if pref else None
            default = pref["default_model_id"] if pref else None
            chosen = selected or default
            if chosen == "service_default": config = self.service_default
            elif chosen:
                row = db.execute("SELECT * FROM ai_models WHERE user_id=? AND model_id=?",(user_id,chosen)).fetchone()
                config = self._config(row) if row else None
            else:
                config = self.service_default
            return (config,config.public()) if config else None
        finally: db.close()

    @staticmethod
    def _messages(messages):
        if not isinstance(messages, (list,tuple)) or not messages or len(messages)>64: raise AIModelError("invalid_messages",400)
        cleaned=[]
        for item in messages:
            if not isinstance(item,Mapping) or set(item)!={"role","content"} or item["role"] not in {"system","user","assistant"} or not isinstance(item["content"],str):
                raise AIModelError("invalid_messages",400)
            try: content_size=len(item["content"].encode("utf-8"))
            except UnicodeEncodeError: raise AIModelError("invalid_messages",400) from None
            if content_size > 32768: raise AIModelError("invalid_messages",400)
            cleaned.append({"role":item["role"],"content":item["content"]})
        return cleaned

    def chat(self, user_id, messages, *, model_id=None):
        resolved = self.resolve(user_id) if model_id is None else None
        if model_id is not None:
            config = self.explicit_config(user_id, model_id)
            resolved = (config, config.public())
        if not resolved: raise AIModelError("provider_not_configured",409)
        config,public=resolved
        try:
            content = self.transport.chat(config,self._messages(messages))
            if type(content) is not str or (config.api_key and config.api_key in content):
                raise ProviderFailure("provider_response_invalid")
            return content,public
        except ProviderFailure as exc: raise AIModelError(exc.code,exc.status) from None

    def explicit_config(self, user_id, model_id):
        db=self._db()
        try:
            if model_id == "service_default": config=self.service_default
            else:
                row=db.execute("SELECT * FROM ai_models WHERE user_id=? AND model_id=?",(user_id,model_id)).fetchone()
                config=self._config(row) if row else None
            if not config: raise AIModelError("provider_not_found",404)
        finally: db.close()
        return config

    def test(self, user_id, model_id):
        config = self.explicit_config(user_id, model_id)
        try:
            self.transport.test(config)
            return {"ok":True,"message":"连接成功。"}
        except ProviderFailure as exc:
            return {"ok":False,"error":exc.code,"status":exc.status}
