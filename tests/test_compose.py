import json
from pathlib import Path

import pytest

from u22_cluster.compose import Layout, container_name, render


def document(**options):
    layout = Layout(project="lab", size=3, work=Path("/home/me/project"), **options)
    return json.loads(render(layout))


def test_nodes_get_stable_names_and_hostnames():
    services = document()["services"]
    assert list(services) == ["node1", "node2", "node3"]
    assert services["node2"]["hostname"] == "node2"
    assert services["node2"]["container_name"] == "lab-node2"


def test_every_node_knows_the_cluster_size():
    services = document()["services"]
    assert {service["environment"]["CLUSTER_SIZE"] for service in services.values()} == {"3"}


def test_the_work_folder_and_shared_volume_are_mounted():
    volumes = document()["services"]["node1"]["volumes"]
    assert {"type": "bind", "source": str(Path("/home/me/project")), "target": "/work"} in volumes
    assert {"type": "volume", "source": "cluster", "target": "/cluster"} in volumes


def test_nodes_are_unprivileged_unless_nfs_is_requested():
    assert "privileged" not in document()["services"]["node1"]
    with_nfs = document(nfs=True)["services"]["node1"]
    assert with_nfs["privileged"] is True
    assert with_nfs["environment"]["U22_NFS"] == "1"
    assert {"type": "volume", "source": "node1-export", "target": "/export"} in with_nfs["volumes"]
    assert "node3-export" in document(nfs=True)["volumes"]
    assert "node1-export" not in document()["volumes"]


def test_the_ubuntu_release_picks_the_image():
    assert document(ubuntu="24.04")["services"]["node1"]["image"] == "u22-cluster:24.04"


def test_the_project_names_the_compose_project():
    assert document()["name"] == "lab"
    assert container_name("lab", "node7") == "lab-node7"


def test_a_cluster_needs_a_node():
    with pytest.raises(ValueError):
        render(Layout(project="lab", size=0, work=Path(".")))
