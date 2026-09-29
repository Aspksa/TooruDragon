from __future__ import annotations

import os

from .auth import AuthService
from .config import (
    core_address,
    core_display_name,
    core_version,
    cores_config,
    system_config,
)
from .database import Database
from .event_client import EventBusClient
from .logging import get_logger
from .registry_client import RegistryClient
from .server import Request, Route, run_server


class CoreRuntime:
    def __init__(
        self,
        name: str,
        role: str,
        capabilities: list[str] | None = None,
    ):
        self.name = name
        self.role = role
        self.capabilities = list(capabilities or [])
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

        main_entry = self.cores.get("main", {})
        main_port = int(
            main_entry.get("port", 8700)
            if isinstance(main_entry, dict)
            else main_entry
        )
        main_url = f"http://{self.config_host}:{main_port}"

        self.events = EventBusClient(
            base_url=main_url,
            token=str(auth_config.get("token", "")),
            logger=self.logger,
        )

        registry_config = self.config.get("service_registry", {})
        self.registry_client = RegistryClient(
            base_url=main_url,
            service={
                "name": self.name,
                "display_name": self.display_name,
                "version": self.version,
                "host": self.host,
                "port": self.port,
                "role": self.role,
                "capabilities": self.capabilities,
            },
            token=str(auth_config.get("token", "")),
            logger=self.logger,
            heartbeat_seconds=int(registry_config.get("heartbeat_seconds", 10)),
        )

    def health(self, _request: Request):
        return 200, {
            "service": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "status": "ok",
            "role": self.role,
            "capabilities": self.capabilities,
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
            "capabilities": self.capabilities,
        }

    def run(self, routes: dict[str, Route] | None = None) -> None:
        self.db.initialize(self.version)

        effective_routes = {
            "/health": Route(self.health, protected=False),
            "/system": Route(self.system_info, protected=True),
        }
        if routes:
            effective_routes.update(routes)

        if self.name != "main" and os.getenv("TOORUDRAGON_DISABLE_REGISTRY") != "1":
            self.registry_client.start()

        run_server(
            self.name,
            self.host,
            self.port,
            self.version,
            effective_routes,
            self.auth,
            self.logger,
        )
