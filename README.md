# k8s-ansible-ha

Ansible automation for a **highly-available Kubernetes 1.37** cluster with
**kube-vip**, selectable **CNI**, selectable **container runtime**, and support
for **Ubuntu / RHEL / Rocky**.

Requires **ansible-core only** — no Galaxy collections.

---

## Tech stack / versions used

| Layer | What | Version(s) |
|---|---|---|
| Orchestration | Ansible | ansible-core only, no Galaxy collections |
| Kubernetes | kubeadm-built HA cluster | **v1.37** (`k8s_minor`, patch pinnable) |
| Load balancer (control-plane VIP) | **kube-vip** | **v1.2.3**, ARP or BGP mode |
| CNI (selectable) | Calico | **v3.32.1** (tigera-operator) |
| | Cilium | **1.20.1** (CLI v0.20.0) |
| | Weave Net (community fork) | v2.9.0 — archived upstream, use for reference only |
| Container runtime (selectable) | containerd | 2.3.3 |
| | CRI-O | 1.36.3 |
| kube-proxy mode | nftables / iptables / ipvs / none | `none` when Gateway API is on, else `nftables` |
| Gateway API | CRDs + Cilium implementation | **v1.6.1** standard channel (`gateway_api_enabled`, on by default) |
| Metrics | metrics-server (`kubectl top`, HPA) | **v0.9.0** via Helm chart **3.14.0**, 2 replicas + PDB (`metrics_server_enabled`, on by default) |
| OS support | Ubuntu, RHEL, Rocky | auto-detected, no manual switch |
| HA topology | 1–4 control planes + N workers | odd control-plane count enforced |

Everything above is a variable in `inventory/group_vars/all.yml` — swap CNI,
runtime, or kube-proxy mode with a single `-e` flag, no code changes. See
[Options](#options) and [Tested combinations](#tested-combinations) below for
what's actually been built and verified, not just supported on paper.

---

## Safety: 192.168.56.133 is never touched

This repo is hard-wired to refuse to operate on `192.168.56.133`.

Three independent gates enforce it:

| Gate | Where it runs | Catches |
|---|---|---|
| **1** | `playbooks/guard.yml`, localhost, **before any SSH** | a forbidden IP or hostname written anywhere in the inventory |
| **2** | per play, after facts | a forbidden IP among the hosts of that specific play |
| **3 / 3b** | per host, after facts | a machine that *actually owns* a forbidden IP, or that is absent from `allowed_hosts` — catches a "safe" name pointing at the wrong box via DNS or a changed DHCP lease |

Gate 1 runs as the first play of every playbook, on localhost, with no remote
connection — so a forbidden host aborts the run **before Ansible SSHes anywhere,
including before fact-gathering**.

Verified behaviour:

```
$ ansible-playbook playbooks/preflight.yml     # inventory contains .133
TASK [safety : Gate 1 | Scan the whole inventory for forbidden addresses]
fatal: [localhost]: FAILED!
  ================== ABORTED BY SAFETY GUARD ==================
  Forbidden host in inventory: 192.168.56.133
  No connection has been made and nothing has been changed.
PLAY RECAP
localhost : ok=1  failed=1        # <- note: .133 never appears
```

The forbidden list lives in `inventory/group_vars/all.yml` as `forbidden_hosts`.

---

## Layout

```
ansible.cfg
ansible-navigator.yml       # navigator settings: pinned EE image, stdout mode, artifacts
requirements-dev.txt        # control-node tooling (ansible-navigator) for .venv
inventory/
  hosts.yml                 # ONLY 192.168.56.134
  group_vars/all.yml        # every tunable
playbooks/
  guard.yml                 # safety gate 1 — imported first by everything
  preflight.yml             # read-only; changes nothing
  create-cluster.yml        # umbrella: preflight → init → masters → workers → metrics-server
  init-master.yml           # kubeadm init on master_primary + Gateway API + CNI
  add-master.yml            # join extra control planes
  add-worker.yml            # join workers
  deploy-gateway-api.yml    # retrofit Gateway API onto a running kube-proxy cluster
  metrics-server.yml        # turn metrics-server on/off on a running cluster
  set-static-ip.yml         # convert nodes from a DHCP lease to a static address
  destroy-cluster.yml       # drain → reset → wipe
roles/
  safety/  common/  container_runtime/  kube_packages/
  kubevip/  control_plane_init/  gateway_api/  cni/
  join_control_plane/  join_worker/  metrics_server/  reset/
artifacts/                  # admin.conf + join commands (mode 0600), created at run time
navigator-artifacts/        # navigator log + playbook replay files (git-ignored, secret)
```

---

## Verified build

Built and re-run successfully on 2026-08-11 against `192.168.56.134`:

```
NAME       STATUS   ROLES           VERSION   CONTAINER-RUNTIME
k8s-cp-0   Ready    control-plane   v1.36.3   containerd://2.3.3

15/15 pods Running   VIP 192.168.56.100 held by k8s-cp-0   tigerastatus all Available
```

Environment: Ubuntu 26.04 LTS, VMware NAT network, containerd + Calico v3.32.1 +
kube-vip v1.2.3 (ARP). Re-running `create-cluster.yml` is safe and converges;
the only tasks that still report *changed* on a no-op run are the join-token and
certificate-key generators (they mint fresh short-lived credentials by design)
and the apt hold/unhold pair.

**Reboot-tested** (nftables build, with a live workload):

| | pre-reboot | post-reboot |
|---|---|---|
| node / pods | Ready, 17/17 | Ready, **17/17** |
| static IP | `192.168.56.134/24`, `proto static` | unchanged, 0 DHCP lease events |
| kube-vip VIP | bound | **reclaimed** |
| proxyMode | nftables | nftables |
| `nodeport-ips` | `{ .100, .134 }` | **`{ .100, .134 }`** |
| nft chains | 24 | **24** |
| forwarding sysctls | all `1` | all `1` |
| ClusterIP / NodePort / NodePort-via-VIP / API | 200 / 200 / 200 / ok | **200 / 200 / 200 / ok** |

Fully converged **40 s** after SSH returned, with no intervention.

Container restart counts rise during the boot window (kubelet retries static
pods while containerd and the network come up) — this is expected. To tell that
apart from a crashloop, sample the total twice: it held steady at 36 across 45 s,
and every container's `startedAt` was 18 s after boot.

End-to-end smoke test on the recovered cluster — a pod with a control-plane
toleration got `10.244.183.141` from the pod CIDR and resolved
`kubernetes.default.svc.cluster.local` successfully, confirming CNI IPAM and
cluster DNS both work, not merely that pods reach `Running`.

## Quick start

```bash
cd /root/k8s-ansible-ha

ansible-playbook playbooks/preflight.yml            # read-only sanity check
ansible-playbook playbooks/create-cluster.yml       # build it

export KUBECONFIG=$PWD/artifacts/admin.conf
kubectl get nodes -o wide
```

### Task numbers in the output

Every task banner carries a running number, so you can tell exactly where a
manual run is and quote a task by number:

```
TASK 93 [control_plane_init : init | Run kubeadm init] ***********************
changed: [k8s-cp-0]
...
RUNNING HANDLER 12 [container_runtime : restart crio] ************************
```

This comes from `callback_plugins/numbered.py`, enabled in `ansible.cfg` as
`stdout_callback = numbered`. It is the built-in `default` callback with a
counter added, so the output is otherwise unchanged.

- Numbers count only banners that are actually printed. With
  `display_skipped_hosts = False`, a task skipped on every host shows no banner
  and takes no number, so the sequence has no gaps.
- `include_tasks` counts once, then each included task gets its own number.
  A loop is one number, however many items it has.
- A task that runs on several hosts at once is still one number.
- To see the full plan up front: `ansible-playbook --list-tasks playbooks/create-cluster.yml`.
- To turn numbering off for one run: `ANSIBLE_STDOUT_CALLBACK=default ansible-playbook ...`.
  To turn it off for good, set `stdout_callback = default` in `ansible.cfg`.
- Under `ansible-navigator run`, ansible-runner replaces the stdout callback with
  its own `awx_display`, so navigator output has no task numbers. Navigator still
  works normally.

---

## Running with ansible-navigator

Every playbook can also run through
[ansible-navigator](https://ansible.readthedocs.io/projects/navigator/). By
default it runs inside a pinned **execution environment** (EE) container, so
ansible-core and collection versions are fixed by the image, not by whatever is
installed on the control node. `ansible-navigator.yml` in the repo root is
picked up automatically.

**One-time setup** (system pip is PEP 668-locked on Ubuntu, so use a venv):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # ansible-navigator 26.8.0
sudo systemctl enable --now docker                # the EE container engine
```

**Run** — the same playbooks, `ansible-navigator run` instead of `ansible-playbook`:

```bash
.venv/bin/ansible-navigator run playbooks/preflight.yml
.venv/bin/ansible-navigator run playbooks/create-cluster.yml
.venv/bin/ansible-navigator run playbooks/metrics-server.yml -e metrics_server_enabled=false
.venv/bin/ansible-navigator run playbooks/destroy-cluster.yml -e confirm_destroy=yes

.venv/bin/ansible-navigator exec -- ansible k8s_cluster -m ping    # ad-hoc, inside the EE
.venv/bin/ansible-navigator run playbooks/preflight.yml -m interactive   # TUI
```

What `ansible-navigator.yml` sets:

| Setting | Value | Why |
|---|---|---|
| `execution-environment.image` | `ghcr.io/ansible/community-ansible-dev-tools:v26.8.0` | pinned tag, never `:latest` |
| `execution-environment.container-engine` | `docker` | only Docker is installed here |
| `execution-environment.container-options` | `--net=host` | nodes and the VIP are reached exactly as from the host, no bridge NAT |
| `ansible.config.path` | `./ansible.cfg` | same inventory, roles, forks and SSH options as `ansible-playbook` |
| `mode` | `stdout` | plain playbook output; `-m interactive` for the TUI |
| `playbook-artifact.save-as` | `navigator-artifacts/<playbook>-<status>-<time>.json` | replay with `ansible-navigator replay <file>` |

No volume mounts are needed. Navigator mounts the project directory at the same
path, so `artifacts/admin.conf` written by `delegate_to: localhost` tasks lands
in the real repo. ansible-runner mounts `$HOME/.ssh/` into the container, so the
node SSH key works.

**`navigator-artifacts/` is secret.** A replay file records every task's
output, including kubeadm join tokens and certificate keys. It is git-ignored
like `artifacts/`.

**Without the container:** add `--ee false`. Navigator then runs the host's
`/usr/bin/ansible-playbook` (ansible-core 2.20.1 from the `ansible` apt
package, with `ansible.utils` for the Calico `ipaddr` filter), **not** the
ansible-core that pip pulled into `.venv`.

Verified on 2026-09-14 against the live .137/.138 cluster:

| Run | Result |
|---|---|
| `ansible-navigator exec -- ansible k8s_cluster -m ping` (EE) | both nodes `pong` |
| `ansible-navigator run playbooks/metrics-server.yml` (EE: ansible-core 2.21.3) | `changed=0 failed=0`, `kubectl top nodes` data |
| `ansible-navigator run playbooks/preflight.yml --ee false` (host ansible-core 2.20.1) | `failed=0` on both nodes |

The EE image is ~2 GB. On this network the first `docker pull` took 21 minutes;
after that `pull.policy: missing` reuses the local copy.

---

## Options

All set in `inventory/group_vars/all.yml`, overridable with `-e`.

| Variable | Values | Default |
|---|---|---|
| `k8s_minor` | `1.37` | `1.37` |
| `k8s_patch` | `""` = newest in minor, or e.g. `1.37.0` | `""` |
| `cri` | `containerd`, `crio` | `containerd` |
| `cni` | `calico`, `cilium`, `weavenet` | `calico` |
| `kube_proxy_mode` | `nftables`, `iptables`, `ipvs`, `none` | derived: `none` if `gateway_api_enabled` else `nftables` |
| `gateway_api_enabled` | `true`, `false` | `true` |
| `gateway_api_version` | any `kubernetes-sigs/gateway-api` tag | `v1.6.1` |
| `gateway_api_channel` | `standard`, `experimental` | `standard` |
| `gateway_api_expose` | `hostNetwork`, `loadbalancer` | `hostNetwork` |
| `metrics_server_enabled` | `true`, `false` | `true` |
| `metrics_server_install_method` | `helm`, `manifest` | `helm` |
| `metrics_server_version` | any `kubernetes-sigs/metrics-server` tag | `v0.9.0` |
| `metrics_server_helm_chart_version` | any `metrics-server` chart version | `3.14.0` |
| `metrics_server_replicas` | `1` or more (`helm` only) | `2` |
| `helm_version` | any helm release tag | `v3.21.3` |
| `metrics_server_kubelet_insecure_tls` | `true`, `false` | `true` |
| `k8s_ready_timeout` | any kubectl duration, e.g. `600s`, `20m` | `900s`; caps node-Ready-after-join and metrics-server rollout waits (slow image pulls) |
| `kubevip_enabled` | `true`, `false` | `true` |
| `kubevip_vip` | any free IP | `192.168.56.140` |
| `kubevip_mode` | `arp`, `bgp` | `arp` |
| `firewall_action` | `open`, `disable`, `ignore` | `open` |
| `remove_control_plane_taint` | `true`, `false` | `false` |
| `reset_purge_packages` | `true`, `false` | `false` |

Examples:

```bash
ansible-playbook playbooks/create-cluster.yml -e cni=cilium -e cri=crio
ansible-playbook playbooks/create-cluster.yml -e cni=cilium -e kube_proxy_mode=none
ansible-playbook playbooks/create-cluster.yml -e kubevip_vip=192.168.56.200
```

**OS is auto-detected** from `ansible_facts.os_family` (Ubuntu → Debian family,
RHEL/Rocky → RedHat family). There is no manual OS switch, because a manual
setting that disagrees with the real machine is only ever a footgun.

---

## Gateway API

`gateway_api_enabled: true` (the default) installs the Kubernetes **Gateway API**
CRDs (`kubernetes-sigs/gateway-api` **v1.6.1**, standard channel) and wires
**Cilium** up as the implementation.

**On a from-scratch build there is nothing extra to do** — `create-cluster.yml`
applies the CRDs (the `gateway_api` role, which runs *before* the CNI so Cilium's
controller never starts against missing types) and Cilium comes up with
`gatewayAPI.enabled=true`.

```bash
kubectl get gatewayclass          # -> cilium   Accepted
kubectl apply -f examples/httpd-gateway.yaml
curl -H 'Host: httpd.k8s-ha.lab' http://192.168.56.100/
```

**Why `kube_proxy_mode` becomes `none`.** Cilium's Gateway API controller only
runs with the kube-proxy replacement. So `kube_proxy_mode` is *derived*:
`none` when `gateway_api_enabled`, `nftables` otherwise. Cilium then does what
kube-proxy did (`kubeProxyReplacement=true`, `k8sServiceHost` = the VIP). Force
`-e kube_proxy_mode=nftables` and the `gateway_api` role hard-aborts the
mismatch rather than building a broken cluster.

**Exposure — `gateway_api_expose: hostNetwork`.** Each Gateway's listeners bind
directly on host ports on every node, so the kube-vip VIP fronts them with no
LoadBalancer provider. The roles also grant `cilium-envoy` `NET_BIND_SERVICE`
so a listener on **80/443** works — without it Envoy NACKs the privileged-port
listener in a tight xDS loop that starves the agent and stalls CNI `ADD` for
every new pod (learned the hard way; see the note in
`roles/gateway_api/defaults/main.yml`). Set it to `loadbalancer` only if you
also set `kubevip_svc_enable=true`.

### Retrofitting a cluster that already has kube-proxy

Flipping `gateway_api_enabled` on for an *existing* kube-proxy cluster needs the
kube-proxy → Cilium migration, which `create-cluster.yml` will **not** do
in-place. Use the dedicated playbook:

```bash
ansible-playbook playbooks/deploy-gateway-api.yml
```

It (1) applies the CRDs, (2) `cilium upgrade`s to `kubeProxyReplacement=true` +
`gatewayAPI.enabled=true`, (3) deletes the kube-proxy DaemonSet/ConfigMap, and
(4) flushes the stale `kube-proxy` nftables tables (and any iptables `KUBE-`
chains) on every node before bouncing Cilium. Steps 2–4 cause a **brief
(seconds) dataplane blip**. Safe to re-run — an already-migrated cluster
short-circuits.

Turn the whole thing off with `-e gateway_api_enabled=false` (keeps kube-proxy;
installs nothing Gateway-API-related).

### Tradeoff: NodePort on the kube-vip VIP

With kube-proxy gone, **NodePort Services answer on the node IPs but not on the
kube-vip VIP**. kube-vip adds the VIP to the NIC with the `deprecated` flag (so
the node never source-selects it for outbound), and Cilium's kube-proxy
replacement skips `deprecated` addresses when it programs NodePort frontends.
There is no clean knob to change this.

This is not a real loss: the Gateway API *is* the VIP-fronted ingress path now
(`http://<VIP>:80` → Gateway → Service). NodePort-on-the-VIP was only ever the
workaround this repo used before it had a Gateway. NodePort on the node IPs,
ClusterIP, and cluster DNS all keep working. Verified after migration:

```
ClusterIP / DNS / NodePort(node IP) / Gateway-via-VIP  =  ok / ok / 200 / 200
NodePort via VIP                                        =  000  (expected)
```

---

## Metrics Server

`metrics_server_enabled: true` (the default) installs **metrics-server v0.9.0**,
which serves the `metrics.k8s.io` API behind `kubectl top`, the CPU/MEM columns
in k9s, and HorizontalPodAutoscalers. `create-cluster.yml` runs it as its last
stage, after the workers join, and doesn't finish until `kubectl top nodes`
returns data.

It's one switch that works both ways. Flip it on a running cluster, no rebuild:

```bash
ansible-playbook playbooks/metrics-server.yml                               # install / upgrade
ansible-playbook playbooks/metrics-server.yml -e metrics_server_enabled=false   # remove
```

With `false`, metrics-server is removed (the Helm release is uninstalled, or the
manifest objects are deleted), and a fresh build simply skips it.

**Install method: `metrics_server_install_method`.**

| Method | How | Replicas |
|---|---|---|
| `helm` (default) | Official chart `metrics-server` **3.14.0** from `kubernetes-sigs.github.io/metrics-server`. The role installs a pinned, checksum-verified `helm` **v3.21.3** on the primary control plane and runs it there, so it works under both `ansible-playbook` and `ansible-navigator`. | `metrics_server_replicas`, default **2** |
| `manifest` | Upstream `components.yaml` plus a kustomize patch (`roles/metrics_server/templates/kustomization.yaml.j2`) | 1 only |

With more than one replica, the Helm values also add:

- **A PodDisruptionBudget** (`minAvailable: 1`), so `kubectl top` keeps working
  through a node drain.
- **A preferred pod anti-affinity on hostname**, so the pods spread across nodes.
  The control plane counts as a node here, thanks to the toleration below. It's
  "preferred" rather than "required", so a single-node cluster still runs every
  replica instead of leaving one Pending.

The role runs `helm upgrade` only when the deployed chart version or values
differ from what's configured, so a converged re-run reports `changed=0`.

Switching method on a running cluster is safe:

```bash
ansible-playbook playbooks/metrics-server.yml -e metrics_server_install_method=manifest -e metrics_server_replicas=1
ansible-playbook playbooks/metrics-server.yml     # back to helm (the default)
```

Both methods create objects with the same names, and the Deployment selectors
differ, which can't be patched in place. So the role removes the other method's
install before it installs the new one.

Both methods add the same two things on top of upstream:

- **`--kubelet-insecure-tls`.** kubeadm's kubelets serve port 10250 with a
  self-signed cert that has no IP SANs, so without the flag every scrape fails
  with `x509: cannot validate certificate`. Traffic is still encrypted; only
  the kubelet's identity goes unverified. Controlled by
  `metrics_server_kubelet_insecure_tls`.
- **A control-plane toleration.** This keeps it schedulable on a cluster with
  no workers.

---

## Growing the cluster

Add the node to the right group in `inventory/hosts.yml`, add its IP to
`allowed_hosts`, then:

```bash
ansible-playbook playbooks/add-worker.yml --limit k8s-w-0
ansible-playbook playbooks/add-master.yml --limit k8s-cp-1
```

Tokens and certificate keys are **minted fresh from the primary on every run**
(tokens live 24 h, certificate keys 2 h), so stale `artifacts/` content is never
relied on.

Keep the control-plane count **odd** — etcd quorum is `(n/2)+1`, so two control
planes tolerate exactly as many failures as one (zero) while doubling the ways
to break. `add-master.yml` warns when the count goes even.

---

## Pinning node addresses

A node's IP is written into the API server certificate SANs, the etcd peer URLs
and `kubelet --node-ip` when the cluster is built. On a DHCP lease, a changed
address breaks the cluster in a way that is tedious to repair.

```bash
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true --limit k8s-cp-0
```

Pins the address the node **already holds** — it refuses to *move* a node
(guard overridable with `static_ip_force_move=true`, but moving a live control
plane invalidates its certificates; rebuild instead). Gateway, resolvers and
search domain are auto-detected; the resolver detection deliberately reads
`/run/systemd/resolve/resolv.conf` rather than the `127.0.0.53` stub.

**Rollback safety.** Before applying, a `systemd-run` timer is armed on the node
to restore the previous netplan config and re-apply it after
`static_ip_rollback_seconds` (default 240). It is cancelled only once Ansible
has proven it can still reach the node — so a bad config makes the node repair
itself instead of needing console access. The playbook runs `serial: 1`, so a
mistake can strand at most one node. The previous config is kept at
`/root/.netplan-backup-k8s-ansible-ha`.

> **Still do this on the hypervisor.** Pinning the address inside the guest does
> not tell the DHCP server about it. If the node's address sits inside the DHCP
> pool, the server can still lease it to another VM. The durable fix is a DHCP
> reservation, or shrinking the pool so it excludes your node addresses.

## Teardown

```bash
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes -e reset_purge_packages=true
```

Refuses to run without `confirm_destroy`. Order is workers → secondary control
planes → primary, because draining is impossible once the API server is gone.

---

## Tested combinations

| CNI | Runtime | kube-proxy | Result |
|---|---|---|---|
| Calico v3.32.1 | containerd 2.3.3 | ipvs | built, reboot-tested |
| Calico v3.32.1 | containerd 2.3.3 | nftables | built, reboot-tested, workload-tested |
| Cilium 1.20.0 | CRI-O 1.36.3 | nftables | built, workload-tested |
| Cilium 1.20.0 | containerd 2.3.3 | nftables | built, workload-tested |
| Cilium 1.20.1 | CRI-O 1.36.5 | none (kube-proxy replacement) | 2026-09-14: upgraded in place from 1.20.0 with the `cni` role. Gateway API returns 200 for the right Host and 404 for others; metrics-server via Helm runs 2/2 across both nodes; the xDS livelock did not recur; re-running `init-master.yml` changes nothing |

Switching runtime stops and disables the one no longer in use, so only a single
CRI daemon ever runs — unless Docker is active, in which case containerd is left
alone (Docker depends on it) and the role says so.

`destroy-cluster.yml` detects the runtime the cluster was actually built with
from `/var/lib/kubelet/kubeadm-flags.env` rather than trusting `cri`, so tearing
down a CRI-O cluster with the default `cri=containerd` still passes the correct
`--cri-socket` to `kubeadm reset`.

> **Testing trap: busybox `nslookup` exit codes.** `nslookup <service>` resolves
> correctly and *then* walks the remaining search domains, gets NXDOMAIN on
> those, and exits **1**. A test written as
> `nslookup httpd && echo OK || echo FAIL` reports FAIL on a perfectly healthy
> cluster. Check the output, or query the FQDN, which exits 0.

## Conformance with upstream documentation

Audited against the official docs. Where this repo deviates, it is deliberate
and the reason is recorded here.

**Matches upstream exactly**

- kubeadm install: `pkgs.k8s.io/core:/stable:/v1.37/{deb,rpm}` repo URLs, keyring
  handling, `apt-mark hold` / dnf `exclude`, cgroup driver `systemd`.
- containerd: upstream explicitly warns that a packaged install may leave `cri`
  in `disabled_plugins` and says to reset with
  `containerd config default > /etc/containerd/config.toml` — exactly what the
  role does.
- CRI-O: upstream packaging moved off `pkgs.k8s.io/addons:/cri-o` to
  `download.opensuse.org/repositories/isv:/cri-o` ("to work independently from
  the pkgs.k8s.io CDN"). This repo uses the `isv:` namespace. The old URL now
  returns HTTP 403.
- kube-vip: env vars (`vip_arp`, `address`, `vip_subnet`, `cp_enable`,
  `vip_leaderelection`), the `ghcr.io/kube-vip/kube-vip` image, the
  `NET_ADMIN`/`NET_RAW`/`SYS_TIME` capabilities, and the documented
  `super-admin.conf` → `admin.conf` switch for Kubernetes 1.29+.
- Swap disabled; `overlay` + `br_netfilter`; `net.ipv4.ip_forward=1`.

**Packet forwarding (IPv4 and IPv6)**

Upstream's *"Enable IPv4 packet forwarding"* section requires exactly one
setting for Kubernetes itself:

```bash
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system
sysctl net.ipv4.ip_forward      # verify
```

What this repo writes to `/etc/sysctl.d/99-kubernetes.conf`:

| Setting | Why |
|---|---|
| `net.ipv4.ip_forward=1` | required by Kubernetes (upstream) |
| `net.bridge.bridge-nf-call-iptables=1` / `-ip6tables=1` | **not** in the upstream section any more — these are a CNI/bridge requirement, still documented by Calico. Need the `br_netfilter` module. |
| `net.ipv6.conf.all.forwarding=1` / `default.forwarding=1` | **optional.** Upstream does not require IPv6 forwarding, and the dual-stack page does not list it for IPv4-only clusters. Enabled so nodes are dual-stack ready; disable with `enable_ipv6_forwarding=false`. |
| `fs.inotify.max_user_*` | headroom for kubelet/CNI watches |

The `99-` prefix is deliberate: files in `/etc/sysctl.d/` are applied in lexical
order, and upstream's `k8s.conf` example sorts early enough that a distro file
could override it.

> **IPv6 caveat.** With `forwarding=1` the kernel stops honouring router
> advertisements on those interfaces unless `accept_ra=2`. A node that gets its
> IPv6 address via SLAAC can lose it. Harmless on IPv4-only nodes like this one.

Upstream tells you to *verify* after applying, so the role does that as a real
assertion rather than a comment — every forwarding sysctl must read back `1` or
the run fails there, instead of surfacing later as pods that cannot route.

**Deliberate deviations**

| Deviation | Why |
|---|---|
| Pod CIDR `10.244.0.0/16`, not Calico's documented `192.168.0.0/16` | the documented default would swallow the `192.168.56.0/24` host network and the kube-vip VIP |
| `kubectl apply --server-side` instead of the quickstart's `kubectl create -f` | `create` fails on re-run, breaking idempotency; and Calico's CRDs exceed the 262 kB annotation limit that client-side apply writes |
| `kube_proxy_mode: nftables`, not upstream's `iptables` default | upstream keeps `iptables` as default only for backward compatibility while recommending nftables for Linux; ipvs is deprecated in v1.35 and removed in v1.43 |
| `nodePortAddresses` set to the node network | see below |

**nftables mode and the VIP.** In nftables mode kube-proxy populates a
`nodeport-ips` set with each node's *primary IP only*, so NodePort Services do
not answer on the kube-vip VIP — under the old ipvs mode they did, because IPVS
created a virtual service per local address. Verified directly:

```
# before: nodeport-ips = { 192.168.56.134 }      VIP:30080 -> 000
# after : nodeport-ips = { 192.168.56.100,
#                          192.168.56.134 }      VIP:30080 -> 200
```

`kube_proxy_nodeport_addresses` therefore defaults to the node network CIDR
(auto-derived from facts) whenever kube-vip is enabled.

**Load balancing differs by mode.** nftables selects a backend with
`numgen random` per connection, so traffic is randomly distributed — measured
**54/46 over 100 requests** across two replicas. ipvs `rr` gives strict
round-robin instead. Neither is wrong; do not read an uneven split under
nftables as a fault.

Note that a sample taken immediately after a rollout can look badly skewed
(20/20 to one pod was observed) simply because kube-proxy has not yet programmed
the second endpoint into its verdict map. Check the map before concluding
anything: `nft list table ip kube-proxy | grep -A2 'chain service-.*<svc>'` —
the `numgen random mod N` tells you how many backends are actually live.

## Notes on the tricky parts

**Cilium 1.20.0 xDS livelock: why the pin is 1.20.1.** On 1.20.0, cilium-agent
and cilium-envoy can get stuck in an endless request/response loop over the
`cilium.NetworkPolicy` xDS resource. It starts after some pod churn, not at
install time, and there don't need to be any policies at all. This cluster hit
it on 2026-09-14, while metrics-server pods were being replaced. Symptoms, on
every node:

- cilium-agent sits at 70–80% CPU and cilium-envoy at ~40%.
- The agent logs thousands of `OnStreamRequest`/`OnStreamResponse` lines for
  `xdsTypeURL=type.googleapis.com/cilium.NetworkPolicy`.
- Envoy logs `Ignoring unwatched type URL` every few milliseconds.
- Container logs rotate every 10–20 seconds.
- `cilium-dbg status` still reports OK.

Upstream this is [cilium/cilium#47624](https://github.com/cilium/cilium/issues/47624),
fixed in **1.20.1** by a cilium-envoy image bump (cilium/cilium#47899).

- **Workaround on 1.20.0:** run `kubectl -n kube-system rollout restart daemonset/cilium-envoy`.
  Verified here: the agent drops from ~75% to ~3% CPU within a minute, and the
  agent itself doesn't need a restart.
- **Fix:** keep `cilium_version` at 1.20.1 or later. Changing it on a running
  cluster upgrades Cilium in place. The `cni` role compares both the `cilium`
  DaemonSet's `helm.sh/chart` label and its agent image tag against
  `cilium_version`. On a mismatch it runs
  `cilium upgrade --reset-then-reuse-values`, then waits for each rollout,
  bounded by `k8s_ready_timeout`.
- **Don't use `--reuse-values` for version upgrades.** It reuses the previous
  release's computed values, including the old chart's default image tags. The
  chart moves to the new version, but the pods keep running the old images.
  That happened here on the first upgrade attempt: the chart label said
  `cilium-1.20.1` while the agent was still on `v1.20.0`. A dry run confirmed
  it. With `--reuse-values` the images were `cilium:v1.20.0`, envoy
  `…1782911245` and `operator-generic:v1.20.0`. With
  `--reset-then-reuse-values` they were `cilium:v1.20.1`, envoy `…1786810558`
  and `operator-generic:v1.20.1`.

**kube-vip and the `super-admin.conf` dance.** The VIP is the
`controlPlaneEndpoint`, so it must answer on `:6443` *before* `kubeadm init`
completes — but kube-vip needs a kubeconfig that does not exist until init is
underway. Since Kubernetes 1.29 `kubeadm` writes both `admin.conf` (limited
RBAC) and `super-admin.conf` (cluster-admin), and the limited identity cannot
perform the leases calls kube-vip needs for leader election. So the manifest is
rendered **twice**: against `super-admin.conf` before init, then rewritten
against `admin.conf` afterwards, which makes kubelet restart the static pod.
Getting this wrong is the usual reason a kube-vip `kubeadm init` hangs forever.

**Pod CIDR is `10.244.0.0/16`, not Calico's documented `192.168.0.0/16`.** The
documented default would swallow the `192.168.56.0/24` host network and the VIP
with it.

**kube-vip v1.x renamed `vip_cidr` to `vip_subnet`.** Manifests copied from
v0.x-era blog posts silently misconfigure the VIP netmask. Verified against
`kube-vip v1.2.3` `pkg/kubevip/config_envvar.go`.

**CRI-O's repo moved.** The widely-quoted
`pkgs.k8s.io/addons:/cri-o:/stable:/vX.Y/` now returns HTTP 403; stable builds
are served from the openSUSE Build Service `isv:` namespace instead.

**Calico ≥3.32 split its CRDs out of `tigera-operator.yaml`.** That manifest now
contains only the operator Namespace/RBAC/Deployment; the 32 CRDs live in
`operator-crds.yaml` and must be applied first. Following the older two-step
guides gives you an operator with no `Installation` CRD to reconcile and the
error `customresourcedefinitions "installations.operator.tigera.io" not found`.

**Docker's `containerd.io` package ships CRI disabled.** Its
`/etc/containerd/config.toml` is a stub whose meaningful content is
`disabled_plugins = ["cri"]`. Any role that skips config generation merely
because the file exists leaves that stub in place, and kubeadm then fails with
`unknown service runtime.v1.RuntimeService` — which reads like a socket problem
but is a config problem. The role detects the stub (and a missing
`SystemdCgroup` key) and regenerates from `containerd config default`.

**Ubuntu leaves a `file:///cdrom` apt source behind.** Once the install ISO is
detached that repo has no `Release` file, and apt treats it as a hard error that
breaks *every* `apt update` on the box. The `common` role disables it by
renaming, controlled by `apt_disable_cdrom_sources`.

**Weave Net is archived.** Weaveworks ceased trading and
`weaveworks/weave` has had no release since 2024. `cni=weavenet` installs the
community fork `rajch/weave v2.9.0`, whose newest manifest still targets the
"k8s-1.11" schema. It is **not** validated against Kubernetes 1.37 and the role
warns loudly. Use `calico` or `cilium` for anything real.

**The control-plane taint does not block system add-ons.** CoreDNS, Calico and
kube-vip all carry `node-role.kubernetes.io/control-plane:NoSchedule`
tolerations and schedule fine on a lone tainted control plane — verified on this
build, where CoreDNS came up `2/2 Running`. What the taint *does* block is your
own workloads, which stay `Pending` until a worker joins or you set
`remove_control_plane_taint=true`.

**`resolvConf` is detected, not hardcoded.** On systemd-resolved hosts
`/etc/resolv.conf` is a stub pointing at `127.0.0.53`; handing that to CoreDNS
creates a resolution loop and a crash-loop.
