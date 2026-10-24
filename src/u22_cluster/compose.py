from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_UBUNTU = "22.04"
NETWORK = "cluster"
VOLUME = "cluster"


@dataclass(frozen=True)
class Layout:
    project: str
    size: int
    work: Path
    ubuntu: str = DEFAULT_UBUNTU
    nfs: bool = False

    @property
    def image(self) -> str:
        return image_name(self.ubuntu)

    def node_names(self) -> list[str]:
        return [node_name(index) for index in range(1, self.size + 1)]


def image_name(ubuntu: str) -> str:
    return f"u22-cluster:{ubuntu}"


def node_name(index: int) -> str:
    return f"node{index}"


def container_name(project: str, node: str) -> str:
    return f"{project}-{node}"


def service(layout: Layout, node: str) -> dict:
    definition: dict = {
        "image": layout.image,
        "container_name": container_name(layout.project, node),
        "hostname": node,
        "environment": {"CLUSTER_SIZE": str(layout.size), "U22_NFS": "1" if layout.nfs else "0"},
        "volumes": [
            {"type": "bind", "source": str(layout.work), "target": "/work"},
            {"type": "volume", "source": VOLUME, "target": "/cluster"},
        ],
        "networks": [NETWORK],
    }
    if layout.nfs:
        definition["privileged"] = True
        export = {"type": "volume", "source": export_volume(node), "target": "/export"}
        definition["volumes"].append(export)
    return definition


def export_volume(node: str) -> str:
    return f"{node}-export"


def render(layout: Layout) -> str:
    if layout.size < 1:
        raise ValueError("a cluster needs at least one node")
    document = {
        "name": layout.project,
        "services": {node: service(layout, node) for node in layout.node_names()},
        "networks": {NETWORK: {"driver": "bridge"}},
        "volumes": {
            VOLUME: {},
            **({export_volume(node): {} for node in layout.node_names()} if layout.nfs else {}),
        },
    }
    return json.dumps(document, indent=2)
