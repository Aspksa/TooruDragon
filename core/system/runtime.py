from __future__ import annotations

from .auth import AuthService
from .config import (
    core_address,
    core_display_name,
    core_version,
    cores_config,
    system_config,
)
from .database import Database
from .logging import get_logger
from .server import Request, Route, run_server


class CoreRuntime:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.version = core_version(name)
        self.display_name = core_display_name(name)
        self.host, self.port = core_address(name)
        self.config = system_config()

        registry = cores_config()
        self.config_host = registry.get("host", "127.0.0.1")
        self.cores = dict(registry.get("cores", {}))

        self.logger = get_logger(name)
        self.db = Database()

        auth_config = self.config.get("auth", {})
        self.auth = AuthService(
            required=bool(auth_config.get("required", False)),
            token=str(auth_config.get("token", "")),
        )

    def health(self, _request: Request):
        return 200, {
            "service": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "status": "ok",
            "role": self.role,
        }

    def system_info(self, _request: Request):
        return 200, {
            "service": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "host": self.host,
            "port": self.port,
            "database": str(self.db.path),
            "auth_required": self.auth.required,
        }

    def run(self, routes: dict[str, Route] | None = None) -> None:
        self.db.initialize(self.version)

        effective_routes = {
            "/health": Route(self.health, protected=False),
            "/system": Route(self.system_info, protected=True),
        }
        if routes:
            effective_routes.update(routes)

        run_server(
            self.name,
            self.host,
            self.port,
            self.version,
            effective_routes,
            self.auth,
            self.logger,
        )
