from __future__ import annotations

from .auth import AuthService
from .config import core_address, system_config, version
from .database import Database
from .logging import get_logger
from .server import Request, Route, run_server


class CoreRuntime:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.version = version()
        self.host, self.port = core_address(name)
        self.config = system_config()
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
            "version": self.version,
            "status": "ok",
            "role": self.role,
        }

    def system_info(self, _request: Request):
        return 200, {
            "service": self.name,
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
