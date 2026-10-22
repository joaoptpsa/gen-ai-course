"""Shared plumbing for the simulated MCP servers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP

from meridian.tools import MeridianTools

logging.getLogger("fastmcp").setLevel(logging.CRITICAL)


@dataclass
class ServerSettings:
    """How one server looks in a scenario: version, publisher, descriptions and granted scopes."""

    name: str
    version: str
    publisher: str
    instructions: str
    scopes: list[str]
    description_overrides: dict[str, str] = field(default_factory=dict)


def settings_for(tools: MeridianTools, name: str, defaults: dict[str, Any]) -> ServerSettings:
    """Merge the server defaults with the scenario's `mcp` section."""
    mcp = tools.sim.scenario.mcp
    server = mcp.get("servers", {}).get(name, {})
    credentials = mcp.get("credentials", {}).get(name, {})
    return ServerSettings(
        name=name,
        version=str(server.get("version", defaults["version"])),
        publisher=server.get("publisher", defaults["publisher"]),
        instructions=server.get("instructions", defaults["instructions"]),
        scopes=list(credentials.get("scopes", defaults["scopes"])),
        description_overrides=dict(server.get("descriptions", {})),
    )


def granted_scopes(settings: ServerSettings) -> list[str]:
    """Scopes of the caller: the bearer token over HTTP, otherwise the scenario credentials."""
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:  # noqa: BLE001 - no HTTP request in progress
        token = None
    if token is not None:
        return list(token.scopes)
    return settings.scopes


def scope_error(settings: ServerSettings, required: str) -> dict[str, Any] | None:
    scopes = granted_scopes(settings)
    if required in scopes:
        return None
    return {
        "error": "insufficient_scope",
        "message": f"The credentials used for the {settings.name} server do not grant {required}.",
        "required_scope": required,
        "granted_scopes": scopes,
    }


class ServerBuilder:
    """Registers tools on a FastMCP server, traced through MeridianTools."""

    def __init__(self, tools: MeridianTools, settings: ServerSettings, auth: Any = None) -> None:
        self.tools = tools
        self.settings = settings
        self.server = FastMCP(settings.name, instructions=settings.instructions, version=settings.version, auth=auth)
        self.descriptions: dict[str, str] = {}

    def add(self, fn: Callable[..., Any], description: str, scope: str | None = None) -> None:
        name = fn.__name__
        text = self.settings.description_overrides.get(name, description)
        self.descriptions[name] = text
        tools, settings, server_name = self.tools, self.settings, self.settings.name

        def traced(*args: Any, **kwargs: Any) -> Any:
            def run() -> Any:
                if scope is not None:
                    denied = scope_error(settings, scope)
                    if denied is not None:
                        return denied
                return fn(*args, **kwargs)

            return tools._run(f"{server_name}.{name}", dict(kwargs), run)

        traced.__name__ = name
        traced.__signature__ = __import__("inspect").signature(fn)  # type: ignore[attr-defined]
        traced.__annotations__ = fn.__annotations__
        self.server.tool(traced, name=name, description=text, run_in_thread=False)
