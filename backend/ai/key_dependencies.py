from __future__ import annotations

from pathlib import Path

from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database


class AIProviderKeyDependencyError(RuntimeError):
    """A configured encryption key is missing a key needed by a saved AI provider."""


def check_ai_provider_key_dependencies(database_path: Path, busy_timeout_ms: int,
                                       encryption_keyring: CredentialKeyring) -> None:
    db = connect_database(database_path, busy_timeout_ms)
    try:
        referenced = {row[0] for row in db.execute(
            "SELECT DISTINCT encryption_key_id FROM ai_models WHERE api_key_ciphertext IS NOT NULL"
        ).fetchall()}
    except Exception as exc:
        raise AIProviderKeyDependencyError("AI provider key dependencies cannot be read") from exc
    finally:
        db.close()
    if referenced - set(encryption_keyring.keys):
        raise AIProviderKeyDependencyError("configured encryption keys are missing a key used by an AI provider")
