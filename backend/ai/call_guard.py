"""Local user-level model call protection shared by Flask workers, without a migration."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import time

from backend.ai.service import AIModelError
from backend.ai.provider import model_call_budget
from backend.auth.rate_limit import RateLimitBucket


class AICallGuard:
    def __init__(self, database_path, rate_limits):
        self.directory = Path(database_path).resolve().parent / '.ai-call-locks'
        self.namespace = hashlib.sha256(str(Path(database_path).resolve()).encode()).hexdigest()
        self.rate_limits = rate_limits

    @contextmanager
    def hold(self, user_id, *, budget_seconds=65):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AIModelError('provider_unavailable', 503)
        key = hashlib.sha256((self.namespace + ':' + user_id).encode()).hexdigest()
        fd = os.open(self.directory / key, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        slot_fd = None
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AIModelError('ai_call_in_progress', 429) from None
            # Two slow model calls leave request threads for ordinary page reads.
            for slot in range(2):
                candidate = os.open(self.directory / f'capacity-{self.namespace}-{slot}', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(candidate)
                except BaseException:
                    os.close(candidate)
                    raise
                else:
                    slot_fd = candidate
                    break
            if slot_fd is None:
                error = AIModelError('ai_service_busy', 503)
                error.retry_after_seconds = 2
                raise error
            decision = self.rate_limits.check_and_record('ai_call', [
                RateLimitBucket('ai_call', 'user', user_id, 12, 60),
                RateLimitBucket('ai_call', 'user_hour', user_id, 120, 3600),
            ], time.time_ns() // 1_000_000)
            if not decision.allowed:
                error = AIModelError('ai_call_rate_limited', 429)
                error.retry_after_seconds = decision.retry_after_seconds
                raise error
            with model_call_budget(budget_seconds):
                yield
        finally:
            # Closing the descriptor also releases the lock after failures or worker exit.
            os.close(fd)
            if slot_fd is not None:
                os.close(slot_fd)
