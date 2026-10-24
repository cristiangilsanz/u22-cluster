#!/usr/bin/env bash
set -euo pipefail

readonly CLUSTER_DIR=/cluster
readonly KEY="$CLUSTER_DIR/id_ed25519"

share_ssh_key() {
    exec 9>"$CLUSTER_DIR/.lock"
    flock 9
    if [[ ! -f "$KEY" ]]; then
        ssh-keygen -q -t ed25519 -N "" -C u22-cluster -f "$KEY"
    fi
    flock -u 9
    install -d -m 700 /root/.ssh
    install -m 600 "$KEY" /root/.ssh/id_ed25519
    install -m 644 "$KEY.pub" /root/.ssh/id_ed25519.pub
    install -m 600 "$KEY.pub" /root/.ssh/authorized_keys
}

write_hostfile() {
    local draft
    draft="$(mktemp "$CLUSTER_DIR/hostfile.XXXXXX")"
    for index in $(seq 1 "${CLUSTER_SIZE:-1}"); do
        echo "node$index"
    done > "$draft"
    chmod 644 "$draft"
    mv "$draft" "$CLUSTER_DIR/hostfile"
}

start_rpc() {
    rpcbind -w || echo "rpcbind did not start" >&2
}

start_nfs() {
    echo "/export *(rw,sync,no_root_squash,no_subtree_check)" > /etc/exports
    if ! service nfs-kernel-server start >/dev/null; then
        echo "the NFS server did not start" >&2
    fi
}

ssh-keygen -A >/dev/null
share_ssh_key
write_hostfile
start_rpc
if [[ "${U22_NFS:-0}" == "1" ]]; then
    start_nfs
fi
exec /usr/sbin/sshd -D -e
