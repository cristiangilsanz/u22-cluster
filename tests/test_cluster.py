import json
from pathlib import Path

import pytest
from fakes import FakeDocker, container

from u22_cluster.cluster import Cluster, ClusterError


def cluster_with(*containers, **options):
    docker = FakeDocker(list(containers), **options)
    return Cluster(
        "lab", docker, clock=iter(range(1000)).__next__, sleep=lambda seconds: None
    ), docker


def test_nodes_are_sorted_by_number_not_by_docker_order():
    cluster, _ = cluster_with(
        container("lab", "node10", address="10.0.0.10"),
        container("lab", "node2", address="10.0.0.2"),
        container("lab", "node1", address="10.0.0.1"),
    )
    assert [node.name for node in cluster.nodes()] == ["node1", "node2", "node10"]


def test_only_this_projects_containers_are_listed():
    cluster, docker = cluster_with()
    assert cluster.nodes() == []
    assert docker.calls[0][:4] == (
        "ps",
        "--all",
        "--filter",
        "label=com.docker.compose.project=lab",
    )


def test_start_builds_the_image_when_missing_and_sends_the_compose_file(tmp_path):
    cluster, docker = cluster_with(
        container("lab", "node1"), container("lab", "node2"), image=False
    )
    nodes = cluster.start(2, tmp_path)
    assert [node.name for node in nodes] == ["node1", "node2"]
    assert docker.attached[0][0] == "build"
    up = docker.calls.index(("compose", "-f", "-", "up", "--detach", "--remove-orphans"))
    sent = json.loads(docker.stdin[up])
    assert list(sent["services"]) == ["node1", "node2"]


def test_start_reuses_an_existing_image(tmp_path):
    cluster, docker = cluster_with(container("lab", "node1"))
    cluster.start(1, tmp_path)
    assert docker.attached == []


def test_start_waits_until_every_node_is_healthy(tmp_path):
    cluster, _ = cluster_with(container("lab", "node1", health="starting"))
    with pytest.raises(ClusterError, match="did not become ready"):
        cluster.start(1, tmp_path, timeout=5)


def test_start_reports_nodes_that_crash(tmp_path):
    cluster, _ = cluster_with(container("lab", "node1", state="exited", health="unhealthy"))
    with pytest.raises(ClusterError, match="node1"):
        cluster.start(1, tmp_path)


def test_nodes_can_be_chosen_by_number_or_name():
    cluster, _ = cluster_with(container("lab", "node1"), container("lab", "node2"))
    assert [node.name for node in cluster.resolve("2")] == ["node2"]
    assert [node.name for node in cluster.resolve("node1")] == ["node1"]
    assert len(cluster.resolve("all")) == 2


def test_unknown_nodes_are_reported():
    cluster, _ = cluster_with(container("lab", "node1"))
    with pytest.raises(ClusterError, match="choose one of: node1"):
        cluster.resolve("5")


def test_commands_need_a_running_cluster():
    cluster, _ = cluster_with()
    with pytest.raises(ClusterError, match="not running"):
        cluster.resolve("all")


def test_run_prefixes_output_by_node_and_returns_the_worst_code():
    cluster, docker = cluster_with(container("lab", "node1"), container("lab", "node2"))
    docker.outputs = {"lab-node1": (0, "node1\n"), "lab-node2": (3, "oops\n")}
    lines = []
    assert cluster.run("all", ["hostname"], output=lines.append) == 3
    assert lines == ["node1 | node1", "node2 | oops"]


def test_run_on_one_node_prints_plain_output():
    cluster, docker = cluster_with(container("lab", "node1"))
    docker.outputs = {"lab-node1": (0, "hello\n")}
    lines = []
    cluster.run("1", ["echo", "hello world"], output=lines.append)
    assert lines == ["hello"]
    assert docker.calls[-1][-1] == "echo 'hello world'"


def test_mpirun_launches_from_the_first_node():
    cluster, docker = cluster_with(container("lab", "node2"), container("lab", "node1"))
    cluster.mpirun(4, ["./hello"])
    assert docker.attached[0][-5:] == ("lab-node1", "mpiexec", "-n", "4", "./hello")


def test_destroy_only_removes_this_projects_resources():
    cluster, docker = cluster_with()
    cluster.destroy()
    assert docker.calls[1] == (
        "compose",
        "--project-name",
        "lab",
        "down",
        "--volumes",
        "--remove-orphans",
    )
    assert docker.calls[-1] == ("image", "rm", "u22-cluster:22.04", "u22-cluster:24.04")
    assert not any("rm" in call and "-a" in call for call in docker.calls)


def test_stop_removes_the_nodes():
    cluster, docker = cluster_with()
    cluster.stop()
    assert docker.calls[-1] == ("compose", "--project-name", "lab", "down", "--remove-orphans")


def test_stop_unmounts_shares_on_every_node_before_any_server_stops():
    cluster, docker = cluster_with(container("lab", "node1"), container("lab", "node2"))
    cluster.stop()
    scripts = [call[-1] for call in docker.calls if call[0] == "exec"]
    assert [script.split()[0] for script in scripts] == ["umount", "umount", "exportfs", "exportfs"]
    assert docker.calls[-1][3] == "down"


def test_build_passes_the_ubuntu_release():
    cluster, docker = cluster_with()
    cluster.build("24.04")
    build = docker.attached[0]
    assert build[:3] == ("build", "--tag", "u22-cluster:24.04")
    assert "UBUNTU_VERSION=24.04" in build
    assert Path(build[-1], "Dockerfile").exists()
