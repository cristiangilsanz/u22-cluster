ARG UBUNTU_VERSION=22.04
FROM ubuntu:${UBUNTU_VERSION}

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential cmake gdb valgrind strace git pkg-config \
        mpich libmpich-dev \
        rpcbind libtirpc-dev rpcsvc-proto \
        nfs-kernel-server nfs-common \
        openssh-server openssh-client \
        iproute2 iputils-ping netcat-openbsd net-tools nmap tcpdump \
        python3 vim nano less htop jq curl ca-certificates sudo tzdata \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*

RUN mkdir -p /run/sshd /work /cluster /export \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config \
    && printf 'Host node*\n    StrictHostKeyChecking no\n    UserKnownHostsFile /dev/null\n    LogLevel ERROR\n' \
        > /etc/ssh/ssh_config.d/cluster.conf

COPY entrypoint.sh /usr/local/bin/u22-entrypoint
RUN chmod 755 /usr/local/bin/u22-entrypoint

ENV HYDRA_HOST_FILE=/cluster/hostfile TZ=Etc/UTC
WORKDIR /work
EXPOSE 22
HEALTHCHECK --interval=1s --timeout=3s --start-period=30s --retries=3 \
    CMD test -s /root/.ssh/authorized_keys && pgrep -x sshd >/dev/null
ENTRYPOINT ["/usr/local/bin/u22-entrypoint"]
