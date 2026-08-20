# k8s-ansible-ha — command & variable reference

Every playbook, every variable, every useful flag. Run all commands from the
repo root (`/root/k8s-ansible-ha`) so `ansible.cfg` is picked up.

> This repo has **no tags defined**, so `--tags` / `--skip-tags` will not
> select anything. Use `--limit` and separate playbooks instead.

---

## 1. The short version

```bash
ansible-playbook playbooks/preflight.yml                       # read-only check
ansible-playbook playbooks/create-cluster.yml                  # build (calico + containerd)
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
export KUBECONFIG=$PWD/artifacts/admin.conf && kubectl get nodes
```

---

## 2. Playbooks

| Playbook | Targets | Destructive | Required flags |
|---|---|---|---|
| `guard.yml` | localhost | no | — (imported by all others) |
| `preflight.yml` | `k8s_cluster` | **no** | — |
| `create-cluster.yml` | all | yes (builds) | — |
| `init-master.yml` | `master_primary` | yes | — |
| `add-master.yml` | `master_secondary` | yes | — |
| `add-worker.yml` | `workers` | yes | — |
| `set-static-ip.yml` | `k8s_cluster` | **yes (network)** | `-e static_ip_enabled=true` |
| `destroy-cluster.yml` | all | **yes (wipes)** | `-e confirm_destroy=yes` |

---

## 3. All variables

### 3.1 Guard rails — `inventory/group_vars/all.yml`

| Variable | Default | Notes |
|---|---|---|
| `forbidden_hosts` | `["192.168.56.133"]` | Run aborts if any appears. **Do not remove.** |
| `allowed_hosts` | `.134`–`.141` | Permit list. A host must match one, or gate 3b refuses it. |

### 3.2 Kubernetes

| Variable | Default | Values / notes |
|---|---|---|
| `k8s_minor` | `"1.36"` | pkgs.k8s.io stream |
| `k8s_patch` | `""` | `""` = newest in minor (1.36.3); or pin `"1.36.3"` |
| `k8s_deb_revision` | `"1.1"` | deb suffix → `kubeadm=1.36.3-1.1` |
| `cluster_name` | `"k8s-ha"` | |
| `pod_cidr` | `"10.244.0.0/16"` | **not** Calico's `192.168.0.0/16` — would eat the host net |
| `service_cidr` | `"10.96.0.0/12"` | |
| `kube_proxy_mode` | `"nftables"` | `nftables` \| `iptables` \| `ipvs` (deprecated) \| `none` |
| `kube_proxy_nodeport_addresses` | `[]` | `[]` = auto-derive node CIDR (so the VIP serves NodePort) |
| `remove_control_plane_taint` | `false` | `true` lets your workloads run on the control plane |

### 3.3 Container runtime

| Variable | Default | Values / notes |
|---|---|---|
| `cri` | `"containerd"` | `containerd` \| `crio` |
| `crio_minor` | `"1.36"` | keep aligned with `k8s_minor` |
| `pause_image` | `registry.k8s.io/pause:3.10` | |
| `cri_socket` | derived | auto from `cri`; override only if unusual |
| `containerd_docker_suite` | `""` | `""` = distro codename, falls back if Docker lacks it |
| `containerd_docker_suite_fallback` | `"noble"` | used when Docker has no suite for your release |
| `containerd_force_config` | `false` | `true` regenerates `config.toml` unconditionally |

### 3.4 CNI

| Variable | Default | Values / notes |
|---|---|---|
| `cni` | `"calico"` | `calico` \| `cilium` \| `weavenet` |
| `calico_version` | `"v3.32.1"` | |
| `calico_encapsulation` | `"VXLANCrossSubnet"` | `VXLAN` \| `IPIP` \| `VXLANCrossSubnet` \| `None` |
| `cilium_version` | `"1.20.0"` | |
| `cilium_cli_version` | `"v0.19.7"` | keep ≥ the Cilium release it installs |
| `weavenet_version` | `"v2.9.0"` | community fork; **unmaintained upstream** |
| `weavenet_repo` | `"rajch/weave"` | |

### 3.5 kube-vip

| Variable | Default | Values / notes |
|---|---|---|
| `kubevip_enabled` | `true` | `false` → endpoint becomes the primary's node IP |
| `kubevip_version` | `"v1.2.3"` | |
| `kubevip_vip` | `"192.168.56.100"` | must be outside the DHCP pool (`.128`–`.254`) |
| `kubevip_vip_subnet` | `"32"` | v1.x name; was `vip_cidr` in v0.x |
| `kubevip_mode` | `"arp"` | `arp` \| `bgp` |
| `kubevip_interface` | `""` | `""` = auto-detect NIC owning `node_ip` |
| `kubevip_svc_enable` | `false` | `true` = also serve `type: LoadBalancer` Services |
| `kubevip_precheck` | `true` | ping the VIP first to catch an address clash |
| `kubevip_kubeconfig` | `admin.conf` | driven automatically by `control_plane_init` |
| `kubevip_bgp_as` | `65000` | BGP mode only — local AS |
| `kubevip_bgp_peeras` | `65000` | BGP mode only — peer AS |
| `kubevip_bgp_peers` | `""` | e.g. `"192.168.56.1:65000::false"` |
| `control_plane_port` | `6443` | |
| `control_plane_endpoint` | derived | VIP when kube-vip is on |

### 3.6 Host / OS

| Variable | Default | Values / notes |
|---|---|---|
| `firewall_action` | `"open"` | `open` \| `disable` \| `ignore` |
| `apt_disable_cdrom_sources` | `true` | disables the `file:///cdrom` source that breaks apt |
| `enable_ipv6_forwarding` | `true` | not required by upstream; off if the node uses SLAAC |
| `artifacts_dir` | `inventory/../artifacts` | kubeconfig + join commands, mode 0600 |

### 3.7 Static IP (`set-static-ip.yml`)

| Variable | Default | Notes |
|---|---|---|
| `static_ip_enabled` | `false` | **required** `true` to do anything |
| `static_ip_address` | `node_ip` | must be an address the node already holds |
| `static_ip_prefix` | `24` | |
| `static_ip_interface` | `""` | `""` = auto-detect |
| `static_ip_gateway` | `""` | `""` = auto-detect |
| `static_ip_nameservers` | `[]` | `[]` = read real upstream resolvers |
| `static_ip_search` | `[]` | `[]` = auto-detect |
| `static_ip_dhcp6` | `false` | |
| `static_ip_rollback_seconds` | `240` | self-repair timer if contact is lost |
| `static_ip_backup_dir` | `/root/.netplan-backup-k8s-ansible-ha` | |
| `static_ip_netplan_file` | `/etc/netplan/00-installer-config.yaml` | |

### 3.8 CLI-only (no default file entry)

| Variable | Used by | Notes |
|---|---|---|
| `confirm_destroy` | `destroy-cluster.yml` | **required**: `yes` or `true` |
| `reset_purge_packages` | `destroy-cluster.yml` | `true` also removes kubeadm/kubelet/runtime |
| `worker_batch_size` | `add-worker.yml` | `serial:` value, e.g. `1` or `"50%"` (default `100%`) |
| `static_ip_force_move` | `set-static-ip.yml` | `true` allows changing a node's IP (**breaks certs**) |
| `static_ip_dns_probe` | `set-static-ip.yml` | hostname to resolve as a post-change check |

### 3.9 Per-host (inventory)

| Variable | Notes |
|---|---|
| `ansible_host` | the address Ansible connects to |
| `node_ip` | the address Kubernetes uses (`--node-ip`, certSANs, etcd peers) |

---

## 4. Choosing the CNI and the container runtime

### 4.1 Which to pick

**CNI (`cni`)**

| Value | Pick it when | Watch out for |
|---|---|---|
| `calico` | default; most conservative, best-tested here | pod CIDR must not be Calico's documented `192.168.0.0/16` on this network |
| `cilium` | you want eBPF, Hubble, or `kube_proxy_mode=none` | needs `net.ipv4.conf.all.rp_filter=0` (the role sets it); CLI is downloaded at install time |
| `weavenet` | only if you specifically need it | **upstream archived**; community fork, not validated on 1.36, may not converge |

**Runtime (`cri`)**

| Value | Pick it when | Watch out for |
|---|---|---|
| `containerd` | default; broadest support | Docker's package ships CRI **disabled**; the role detects and regenerates the config |
| `crio` | Kubernetes-native runtime, common on RHEL/Rocky | its repo is the openSUSE `isv:` namespace, not `pkgs.k8s.io/addons` |

### 4.2 How to select

```bash
# per-run (does not persist)
ansible-playbook playbooks/create-cluster.yml -e cni=cilium -e cri=crio

# permanent — inventory/group_vars/all.yml
cni: "cilium"
cri: "crio"
```

The runtime version follows the stream vars: `crio_minor` for CRI-O (keep it
equal to `k8s_minor`), and containerd comes from the Docker repo.

### 4.3 Rules the playbooks enforce

The `common` role asserts these before touching anything:

- `cri` ∈ `containerd`, `crio`
- `cni` ∈ `calico`, `cilium`, `weavenet`
- `kube_proxy_mode` ∈ `nftables`, `iptables`, `ipvs`, `none`
- **`kube_proxy_mode=none` is only valid with `cni=cilium`** — nothing else can
  replace kube-proxy

An invalid combination fails immediately with a clear message rather than
half-building a cluster.

### 4.4 What the choice actually changes

| Choice | Effect |
|---|---|
| any `cni` | firewall ports opened (Calico 179/4789/5473, Cilium 8472/4240/4244, Weave 6783/6784) |
| `cni=cilium` | adds `net.ipv4.conf.all.rp_filter=0` |
| `kube_proxy_mode=ipvs` | installs `ipvsadm` + `ipset`, loads `ip_vs*` modules |
| `kube_proxy_mode=nftables` | installs `nftables` |
| any `cri` | sets `criSocket` in the kubeadm config and `/etc/crictl.yaml` |
| switching `cri` | the **other** runtime is stopped and disabled (unless Docker is active and needs containerd) |

### 4.5 Changing it on an existing cluster

| Change | Possible in place? | What to do |
|---|---|---|
| `cni` | **No** | destroy + rebuild. Two CNIs cannot coexist; migration means re-IPing every pod. |
| `cri` | Per node, not in place | drain → `destroy-cluster.yml --limit <node>` → rejoin with the new `-e cri=` |
| `kube_proxy_mode` | **No** (set at `kubeadm init`) | destroy + rebuild, or hand-patch the `kube-proxy` ConfigMap and restart the DaemonSet |

```bash
# switch CNI (or kube-proxy mode) — full rebuild
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
ansible-playbook playbooks/create-cluster.yml -e cni=cilium -e cri=containerd

# switch runtime on ONE worker
kubectl drain k8s-w-0 --ignore-daemonsets --delete-emptydir-data
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes --limit k8s-w-0
kubectl delete node k8s-w-0
ansible-playbook playbooks/add-worker.yml -e cni=cilium -e cri=crio --limit k8s-w-0
```

> **Joining a node? Pass the same `-e cri=` / `-e cni=` the cluster was BUILT
> with.** `group_vars` defaults to `calico`; joining a Cilium cluster without
> `-e cni=cilium` configures the new node's sysctls and firewall for the wrong CNI.

### 4.6 Verify what is actually running

```bash
kubectl get nodes -o wide          # CONTAINER-RUNTIME column: containerd:// or cri-o://
kubectl get pods -A                # calico-system/* vs cilium-* pods
crictl version                     # RuntimeName: containerd | cri-o
systemctl is-active containerd crio
cilium status                      # cilium only
kubectl get tigerastatus           # calico only
```

### 4.7 Tested combinations

| CNI | Runtime | kube-proxy | Status |
|---|---|---|---|
| Calico v3.32.1 | containerd 2.3.3 | ipvs | built, reboot-tested |
| Calico v3.32.1 | containerd 2.3.3 | nftables | built, reboot-tested, workload-tested |
| Cilium 1.20.0 | CRI-O 1.36.3 | nftables | built, workload-tested |
| Cilium 1.20.0 | containerd 2.3.3 | nftables | built, workload-tested |
| Weave Net | any | any | **untested — expected to fail on 1.36** |

---

## 5. Choosing the kube-vip VIP

### 5.1 Rules for this network

It is a VMware NAT network, which constrains the choice:

| Address | Status |
|---|---|
| `192.168.56.1` | VMware host adapter — **never use** |
| `192.168.56.2` | NAT gateway + DNS — **never use** |
| `192.168.56.254` | VMware DHCP server — **never use** |
| `192.168.56.128`–`.254` | **DHCP pool** — never put a VIP here; a lease could steal it |
| `192.168.56.3`–`.127` | **safe static range — pick from here** |
| `192.168.56.100` | current VIP |
| `192.168.56.133` | forbidden host |
| `192.168.56.134`+ | nodes |

Also: the VIP must be **in the same subnet as the nodes** (ARP mode announces on
the node's L2 segment), and must be genuinely free — the role pings it first and
warns if something answers.

Find what is free:

```bash
for i in $(seq 3 127); do
  (ping -c1 -W1 192.168.56.$i >/dev/null 2>&1 && echo "OCCUPIED: 192.168.56.$i") &
done; wait
```

### 5.2 How to set it

```bash
# per-run
ansible-playbook playbooks/create-cluster.yml -e kubevip_vip=192.168.56.50

# permanent — inventory/group_vars/all.yml
kubevip_vip: "192.168.56.50"

# no VIP at all (endpoint becomes the primary's node IP — loses HA failover)
ansible-playbook playbooks/create-cluster.yml -e kubevip_enabled=false
```

### 5.3 Changing the VIP on a running cluster

**Not possible in place.** The VIP is baked in at `kubeadm init` in three places:

- `controlPlaneEndpoint` in the kubeadm config
- the API server certificate **SANs**
- the server URL in every `kubelet.conf` / `admin.conf`

Re-running with a new value moves the floating address, but the API server's
certificate is not valid for it and every kubeconfig still points at the old one
— TLS errors, not a working cluster. Rebuild instead:

```bash
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
ansible-playbook playbooks/create-cluster.yml -e cni=cilium -e kubevip_vip=192.168.56.50
```

### 5.4 ARP vs BGP

```bash
ansible-playbook playbooks/create-cluster.yml -e kubevip_mode=arp     # default, no infra needed
ansible-playbook playbooks/create-cluster.yml -e kubevip_mode=bgp \
    -e kubevip_bgp_as=65000 -e kubevip_bgp_peeras=65000 \
    -e kubevip_bgp_peers="192.168.56.1:65000::false"
```

ARP works on any flat L2 network. BGP needs a router that will peer with you —
there is none on this VMware NAT network, so ARP is the right choice here.

### 5.5 Verify the VIP

```bash
ip -4 -o addr show | grep 192.168.56.100                 # bound to an interface?
kubectl -n kube-system get lease plndr-cp-lock \
  -o jsonpath='{.spec.holderIdentity}'                   # which node holds it
curl -sk https://192.168.56.100:6443/healthz             # API answering on it
kubectl -n kube-system logs kube-vip-k8s-cp-0            # kube-vip's own log
nft list set ip kube-proxy nodeport-ips                  # does NodePort serve on it too?
```

The VIP shows as `scope global deprecated` — that is correct. kube-vip marks it
so the host does not use it as a source address for outbound connections.

---

## 6. Build recipes

```bash
# Defaults: calico + containerd + nftables
ansible-playbook playbooks/create-cluster.yml

# ---- CNI × runtime combinations ----
ansible-playbook playbooks/create-cluster.yml -e cni=calico   -e cri=containerd
ansible-playbook playbooks/create-cluster.yml -e cni=calico   -e cri=crio
ansible-playbook playbooks/create-cluster.yml -e cni=cilium   -e cri=containerd
ansible-playbook playbooks/create-cluster.yml -e cni=cilium   -e cri=crio
ansible-playbook playbooks/create-cluster.yml -e cni=weavenet -e cri=containerd   # unmaintained

# ---- kube-proxy modes ----
ansible-playbook playbooks/create-cluster.yml -e kube_proxy_mode=nftables
ansible-playbook playbooks/create-cluster.yml -e kube_proxy_mode=iptables
ansible-playbook playbooks/create-cluster.yml -e kube_proxy_mode=ipvs        # deprecated
ansible-playbook playbooks/create-cluster.yml -e kube_proxy_mode=none -e cni=cilium

# ---- kube-vip ----
ansible-playbook playbooks/create-cluster.yml -e kubevip_vip=192.168.56.110
ansible-playbook playbooks/create-cluster.yml -e kubevip_mode=bgp \
    -e kubevip_bgp_as=65000 -e kubevip_bgp_peers="192.168.56.1:65000::false"
ansible-playbook playbooks/create-cluster.yml -e kubevip_svc_enable=true
ansible-playbook playbooks/create-cluster.yml -e kubevip_enabled=false   # no HA endpoint

# ---- versions ----
ansible-playbook playbooks/create-cluster.yml -e k8s_minor=1.35
ansible-playbook playbooks/create-cluster.yml -e k8s_patch=1.36.3
ansible-playbook playbooks/create-cluster.yml -e calico_version=v3.32.1
ansible-playbook playbooks/create-cluster.yml -e cilium_version=1.20.0

# ---- networking / host ----
ansible-playbook playbooks/create-cluster.yml -e pod_cidr=10.245.0.0/16
ansible-playbook playbooks/create-cluster.yml -e firewall_action=disable
ansible-playbook playbooks/create-cluster.yml -e enable_ipv6_forwarding=false
ansible-playbook playbooks/create-cluster.yml -e remove_control_plane_taint=true

# ---- list/dict values need JSON ----
ansible-playbook playbooks/create-cluster.yml \
    -e '{"kube_proxy_nodeport_addresses":["192.168.56.0/24","10.0.0.0/8"]}'

# ---- many at once ----
ansible-playbook playbooks/create-cluster.yml \
    -e cni=cilium -e cri=crio -e kube_proxy_mode=none \
    -e kubevip_vip=192.168.56.110 -e remove_control_plane_taint=true
```

---

## 7. Growing / shrinking

```bash
# Uncomment the host in inventory/hosts.yml first, then:
ansible-playbook playbooks/add-worker.yml -e cni=cilium
ansible-playbook playbooks/add-worker.yml -e cni=cilium --limit k8s-w-0
ansible-playbook playbooks/add-worker.yml -e cni=cilium -e worker_batch_size=1

ansible-playbook playbooks/add-master.yml -e cni=cilium --limit k8s-cp-1

# Remove a node (drain + delete on the master, then reset the node)
kubectl drain k8s-w-0 --ignore-daemonsets --delete-emptydir-data
kubectl delete node k8s-w-0
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes --limit k8s-w-0
```

Keep the control-plane count **odd** — etcd quorum is `(n/2)+1`, so 2 masters
tolerate no failures at all and 4 are no better than 3.

---

## 8. Static IP

```bash
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true --limit k8s-cp-0
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true \
    -e static_ip_gateway=192.168.56.2 \
    -e '{"static_ip_nameservers":["192.168.56.2","8.8.8.8"]}'
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true \
    -e static_ip_rollback_seconds=600        # longer self-repair window
```

Recover manually if it ever strands a node:

```bash
cp -a /root/.netplan-backup-k8s-ansible-ha/. /etc/netplan/ && netplan apply
```

---

## 9. Teardown

```bash
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes -e reset_purge_packages=true
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes --limit k8s-w-0
```

The reset detects the runtime the cluster was actually built with, so tearing
down a CRI-O cluster without `-e cri=crio` still works.

---

## 10. Useful Ansible flags

```bash
--limit k8s-cp-0            # one host
--limit workers             # one group
--limit '!k8s-w-0'          # everything except
--check                     # dry run (unreliable here: many command/shell tasks)
--diff                      # show file changes
--list-hosts                # what would be targeted
--list-tasks                # task order without running
--syntax-check              # parse only
--start-at-task "name"      # resume mid-play
--step                      # confirm each task
-v / -vvv / -vvvv           # verbosity (-vvvv includes connection debug)
-f 20                       # parallel forks
-e @vars.yml                # load variables from a file
-i other-inventory.yml      # alternate inventory (guard still applies)
```

Handy checks:

```bash
ansible-inventory --graph
ansible-inventory --host k8s-cp-0
ansible all -m ping
ansible k8s-cp-0 -m setup -a 'filter=ansible_default_ipv4'
ansible k8s-cp-0 -m debug -a 'var=hostvars[inventory_hostname]'
for p in playbooks/*.yml; do ansible-playbook --syntax-check "$p" >/dev/null && echo "OK $p"; done
```

---

## 11. Verify a running cluster

```bash
export KUBECONFIG=$PWD/artifacts/admin.conf
kubectl get nodes -o wide
kubectl get pods -A
```

On the node:

```bash
curl -s http://127.0.0.1:10249/proxyMode                      # nftables / iptables / ipvs
nft list set ip kube-proxy nodeport-ips                       # which IPs serve NodePort
nft list table ip kube-proxy | grep -A2 'chain service-.*httpd'   # backends: numgen mod N
ipvsadm -Ln                                                   # ipvs mode only
crictl ps                                                     # containers via the CRI
kubectl -n kube-system get lease plndr-cp-lock \
  -o jsonpath='{.spec.holderIdentity}'                        # who holds the VIP
ip -4 -o addr show | grep 192.168.56.100                      # VIP bound?
curl -sk https://192.168.56.100:6443/healthz                  # API via VIP
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
journalctl -u kubelet -n 80 --no-pager
```

Demo workload:

```bash
kubectl apply -f examples/httpd.yaml
kubectl delete -f examples/httpd.yaml
```

---

## 12. Traps worth remembering

- **`--check` is unreliable here.** Much of the work is `command`/`shell`, which
  cannot be simulated. Use `preflight.yml` for a genuine no-op check.
- **`group_vars` must live next to the inventory** (`inventory/group_vars/`). A
  repo-root `group_vars/` is silently never loaded.
- **List/dict values need JSON** with `-e`: a bare `-e foo=[a,b]` becomes a string.
- **`cni`, `kube_proxy_mode` and `kubevip_vip` cannot be changed in place** —
  they are baked in at `kubeadm init`. Destroy and rebuild.
- **busybox `nslookup` exits 1** after resolving, once it hits NXDOMAIN on the
  remaining search domains. Do not use its exit code as a DNS health test.
- **Post-reboot restart counts are never 0.** Sample the total twice to tell a
  settled cluster from a crashloop.
- **Sample load balancing at ≥50 requests.** nftables picks backends randomly,
  and right after a rollout kube-proxy may still have only one endpoint programmed.
