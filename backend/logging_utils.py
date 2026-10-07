from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, tzinfo
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .time_utils import APP_TZ


class AppTimezoneFormatter(logging.Formatter):
    def __init__(self, fmt: str | None = None, datefmt: str | None = None, tz: tzinfo | None = None) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.tz = tz or APP_TZ

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="milliseconds")


class AppTimezoneTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(
        self,
        filename: str | Path,
        tz: tzinfo | None = None,
        backupCount: int = 14,
        encoding: str | None = "utf-8",
    ) -> None:
        self.app_tz = tz or APP_TZ
        super().__init__(
            filename,
            when="midnight",
            backupCount=backupCount,
            encoding=encoding,
            utc=False,
        )

    def computeRollover(self, currentTime: int) -> int:
        current_dt = datetime.fromtimestamp(currentTime, self.app_tz)
        next_midnight = (current_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(next_midnight.timestamp())

    def doRollover(self) -> None:
        currentTime = int(self.rolloverAt)
        interval_start = datetime.fromtimestamp(currentTime, self.app_tz) - timedelta(seconds=self.interval)
        dfn = self.rotation_filename(f"{self.baseFilename}.{interval_start.strftime(self.suffix)}")

        if self.stream:
            self.stream.close()
            self.stream = None

        if not os.path.exists(dfn):
            try:
                self.rotate(self.baseFilename, dfn)
            except PermissionError:
                pass
            else:
                if self.backupCount > 0:
                    for stale_path in self.getFilesToDelete():
                        try:
                            os.remove(stale_path)
                        except OSError:
                            pass

        if not self.delay:
            self.stream = self._open()
        self.rolloverAt = self.computeRollover(int(datetime.now(self.app_tz).timestamp()))


_app_root = os.environ.get("APP_ROOT_DIR", "").strip()
LOGS_DIR = Path(_app_root) / "backend" / "logs" if _app_root else Path(__file__).resolve().parents[1] / "backend" / "logs"


def setup_logging(log_name: str = "run_flow", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(log_name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_path = LOGS_DIR / f"{log_name}.log"
    formatter = AppTimezoneFormatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = AppTimezoneTimedRotatingFileHandler(
        log_path,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def get_http_logger() -> logging.Logger:
    """HTTP 请求/响应日志 → backend/logs/http_client.log"""
    return setup_logging("http_client", logging.DEBUG)


def get_api_logger() -> logging.Logger:
    """Flask API 请求日志 → backend/logs/api_server.log"""
    return setup_logging("api_server", logging.INFO)


def get_frontend_logger() -> logging.Logger:
    """前端推送日志 → backend/logs/frontend.log"""
    return setup_logging("frontend", logging.INFO)
