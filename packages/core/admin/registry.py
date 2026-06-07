from __future__ import annotations

from pathlib import Path

from apps.worker.jobs.init_client import init_client
from packages.core.control_plane.models import CreateClientResult, RotateWidgetKeyResult
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.tenant.paths import client_config_dir, safe_client_id


class ClientNotFoundError(ValueError):
    pass


class ClientAlreadyExistsError(ValueError):
    pass


class ClientRegistryService:
    def __init__(
        self,
        *,
        clients_root: Path,
        registry_store: ClientRegistryStore,
    ) -> None:
        self._clients_root = clients_root.resolve()
        self._store = registry_store

    def reload_auth(self) -> None:
        from apps.api.dependencies import stack as stack_module

        stack = stack_module.get_stack()
        if hasattr(stack.auth_provider, "reload"):
            stack.auth_provider.reload()

    def list_clients(self) -> list[dict]:
        return self._store.list_clients()

    def get_client(self, client_id: str) -> dict:
        try:
            return self._store.get_client(client_id)
        except ValueError as exc:
            raise ClientNotFoundError(str(exc)) from exc

    def get_client_config_dir(self, client_id: str) -> Path:
        return client_config_dir(self._clients_root, client_id)

    def list_widget_keys(self, client_id: str) -> list[dict]:
        return self._store.list_widget_keys(client_id)

    def rotate_widget_key(
        self,
        client_id: str,
        *,
        allowed_origins: list[str] | None = None,
        revoke_key_id: str | None = None,
    ) -> RotateWidgetKeyResult:
        result = self._store.rotate_widget_key(
            client_id,
            allowed_origins=allowed_origins,
            revoke_key_id=revoke_key_id,
        )
        self.reload_auth()
        return result

    def revoke_widget_key(self, client_id: str, key_id: str) -> None:
        self._store.revoke_widget_key(client_id, key_id)
        self.reload_auth()

    def create_client(
        self,
        *,
        client_id: str,
        display_name: str | None = None,
        domain_pack: str = "generic",
        allowed_origins: list[str] | None = None,
        reveal_widget_key: bool = False,
    ) -> dict:
        cid = safe_client_id(client_id)
        if self._store.client_exists(cid):
            raise ClientAlreadyExistsError(f"Client already exists: {cid}")

        config_dir = self.get_client_config_dir(cid)
        if config_dir.is_dir():
            raise ClientAlreadyExistsError(f"Client config already exists: {cid}")

        init_client(
            cid,
            domain_pack=domain_pack,
            display_name=display_name,
            clients_root=self._clients_root,
        )

        result: CreateClientResult = self._store.create_client_record(
            client_id=cid,
            display_name=display_name or cid.replace("_", " ").title(),
            domain_pack=domain_pack,
            allowed_origins=allowed_origins,
            reveal_widget_key=reveal_widget_key,
        )
        self.reload_auth()

        response: dict = {
            "client_id": result.client_id,
            "display_name": result.display_name,
            "domain_pack": result.domain_pack,
            "widget_key_prefix": result.widget_key_prefix,
            "allowed_origins": list(result.allowed_origins),
        }
        if result.widget_key:
            response["widget_key"] = result.widget_key
        return response
