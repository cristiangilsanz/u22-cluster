import json

from u22_cluster.docker import Docker, Result


def container(project, node, state="running", health="healthy", address="172.20.0.2"):
    return {
        "Name": f"/{project}-{node}",
        "Config": {"Hostname": node},
        "State": {"Status": state, "Health": {"Status": health} if health else None},
        "NetworkSettings": {"Networks": {f"{project}_cluster": {"IPAddress": address}}},
    }


class FakeDocker(Docker):
    def __init__(self, containers=None, image=True, outputs=None):
        super().__init__("docker")
        self.calls = []
        self.attached = []
        self.stdin = []
        self.containers = containers or []
        self.image = image
        self.outputs = outputs or {}

    def capture(self, *args, stdin=None):
        self.calls.append(args)
        self.stdin.append(stdin)
        if args[:2] == ("image", "inspect"):
            return Result(0 if self.image else 1, "")
        if args[0] == "ps":
            return Result(0, "\n".join(item["Name"].lstrip("/") for item in self.containers))
        if args[0] == "inspect":
            wanted = set(args[1:])
            chosen = [item for item in self.containers if item["Name"].lstrip("/") in wanted]
            return Result(0, json.dumps(chosen))
        if args[0] == "exec":
            node = args[3]
            code, text = self.outputs.get(node, (0, ""))
            return Result(code, text)
        if args[:3] == ("image", "ls", "u22-cluster"):
            return Result(0, "u22-cluster:22.04\nu22-cluster:24.04\n")
        return Result(0, "")

    def attach(self, *args, stdin=None):
        self.attached.append(args)
        return 0
