from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


def manifest_hash(system_manifest: dict[str, Any]) -> str:
    # Stable hash for caching inferred semantics. Assumes dict is JSON-serializable.
    raw = json.dumps(system_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CommandRef:
    node_name: str
    node_id: str
    token: str
    spec: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.node_id}:{self.token.upper()}"


def iter_commands(system_manifest: dict[str, Any]) -> Iterable[CommandRef]:
    nodes = system_manifest.get("nodes")
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name") or "").strip() or "node"
        node_id = str(node.get("node_id") or node_name).strip() or node_name
        commands = node.get("commands") if isinstance(node.get("commands"), list) else []
        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            token = str(cmd.get("token") or "").strip()
            if not token:
                continue
            yield CommandRef(node_name=node_name, node_id=node_id, token=token, spec=cmd)


def get_command_spec(system_manifest: dict[str, Any], target: str, token: str) -> dict[str, Any] | None:
    token_u = token.upper()
    nodes = system_manifest.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "")
        node_id = str(node.get("node_id") or "")
        if target not in {name, node_id}:
            continue
        for cmd in node.get("commands", []):
            if not isinstance(cmd, dict):
                continue
            if str(cmd.get("token") or "").upper() == token_u:
                return cmd
    return None

