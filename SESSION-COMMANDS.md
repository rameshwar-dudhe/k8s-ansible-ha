# Session log — the exact commands actually run

A faithful record of what was executed on 2026-08-11 to build, break, fix and
verify this repo. Distinct from `COMMANDS.md`, which documents what *can* be run.

Control node: `192.168.56.133` (Ubuntu 26.04) · Target: `192.168.56.134` (`k8s-cp-0`)

---

## 0. Recon — before writing anything

```bash
# Does Kubernetes 1.36 actually exist? (first attempt returned bare 302s — inconclusive)
for v in 1.35 1.36 1.37 1.38; do
  curl -sL -o /dev/null -w "core v${v} -> %{http_code}\n" \
    "https://pkgs.k8s.io/core:/stable:/v${v}/deb/Release"
done
curl -sL "https://pkgs.k8s.io/core:/stable:/v1.36/deb/Packages" \
  | grep -A1 -E "^Package: (kubeadm|kubelet|kubectl)$"

# Component versions — read, not remembered
curl -sL https://api.github.com/repos/kube-vip/kube-vip/releases/latest      | grep -m1 tag_name
curl -sL https://api.github.com/repos/projectcalico/calico/releases/latest   | grep -m1 tag_name
curl -sL https://api.github.com/repos/cilium/cilium/releases/latest          | grep -m1 tag_name
curl -sL https://api.github.com/repos/rajch/weave/releases/latest            | grep -m1 tag_name
curl -sL https://api.github.com/repos/cri-o/cri-o/releases/latest            | grep -m1 tag_name

# kube-vip v1.x env var names — vip_cidr is gone, it is vip_subnet now
curl -sL "https://raw.githubusercontent.com/kube-vip/kube-vip/v1.2.3/pkg/kubevip/config_envvar.go" \
  | grep -E 'vipSubnet|vipAddress|vipArp|cpEnable'

# CRI-O repo: pkgs.k8s.io/addons 403s; isv: namespace works
for u in "https://pkgs.k8s.io/addons:/cri-o:/stable:/v1.34/deb/Release" \
         "https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v1.34/deb/Release"; do
  curl -sL -o /dev/null -w "%{http_code}  $u\n" "$u"
done

# Target node facts
ssh root@192.168.56.134 'hostname; cat /etc/os-release; ip -4 -o addr show'

# Docker publishes a suite for Ubuntu 26.04 (resolute)?
curl -sL https://download.docker.com/linux/ubuntu/dists/ | grep -oE 'href="[a-z]+/"'
```

---

## 1. Control node setup

```bash
apt-get update -qq
apt-get install -y -qq ansible-core        # -> ansible-core 2.20.1
ansible --version
```

---

## 2. Validation before ever touching the cluster

```bash
cd /root/k8s-ansible-ha

# Syntax
for p in preflight init-master add-master add-worker create-cluster destroy-cluster; do
  ansible-playbook --syntax-check playbooks/$p.yml
done

# Inventory resolves as expected
ansible-inventory --graph
ansible-inventory --list
ansible-inventory --host k8s-cp-0
ansible all --list-hosts
ansible k8s_cluster --list-hosts

# Variables resolve on the target
ansible k8s-cp-0 -m debug -a 'msg="vip={{ kubevip_vip }} endpoint={{ control_plane_endpoint }}"'
ansible k8s-cp-0 -m setup -a 'filter=ansible_default_ipv4'

# Read-only preflight
ansible-playbook playbooks/preflight.yml
```

### Jinja template parse check (catches `{{ }}` errors without a build)

```bash
python3 - <<'PY'
import glob
from jinja2 import Environment
env = Environment(extensions=['jinja2.ext.do'])
for f in sorted(glob.glob("roles/**/templates/*.j2", recursive=True)):
    try:    env.parse(open(f).read()); print("OK  ", f)
    except Exception as e: print("FAIL", f, e)
PY
```

---

## 3. Proving the `.133` guard actually works

Three deliberate failure tests, each expected to abort with exit 2.

```bash
S=/tmp/scratch/inv; mkdir -p $S/group_vars
cp inventory/group_vars/all.yml $S/group_vars/

# TEST A — .133 hidden behind a friendly hostname
#   (inventory with  totally-innocent-node: ansible_host: 192.168.56.133)
ansible-playbook -i $S/hosts.yml playbooks/preflight.yml       # -> ABORT, exit 2

# TEST B — .133 as a bare hostname, no ansible_host
ansible-playbook -i $S/hosts-b.yml playbooks/preflight.yml     # -> ABORT, exit 2

# TEST C — fact-based gate, using the SAFE node .134
ansible-playbook playbooks/preflight.yml -e '{"allowed_hosts":["10.99.99.99"]}'
#   -> ABORT at gate 3b, proving it reads the machine's real IPs
```

In A and B the PLAY RECAP shows **only `localhost`** — no fact-gathering, no SSH
to `.133` at all.

---

## 4. Building the cluster

```bash
# Runs 1-6 each failed on a real bug (see §7). Run 7 succeeded.
ansible-playbook playbooks/create-cluster.yml

# Later builds, one clean pass each:
ansible-playbook playbooks/create-cluster.yml -e cri=crio      -e cni=cilium
ansible-playbook playbooks/create-cluster.yml -e cri=containerd -e cni=cilium
```

Watching a background build:

```bash
ansible-playbook playbooks/create-cluster.yml > build.log 2>&1
grep -E "^TASK \[" build.log | tail -1
grep -A6 "PLAY RECAP" build.log
grep -nE "^fatal|\[ERROR\]" build.log
```

---

## 5. Static IP + reboot testing

```bash
ansible-playbook playbooks/set-static-ip.yml -e static_ip_enabled=true

# Reboot without the SSH session killing the command
ssh root@192.168.56.134 \
  'systemd-run --on-active=1 --timer-property=AccuracySec=100ms /usr/sbin/reboot'

# Wait for it to come back
until ssh -o ConnectTimeout=4 root@192.168.56.134 'test -d /run/systemd/system' 2>/dev/null
do sleep 3; done
```

---

## 6. Teardown

```bash
ansible-playbook playbooks/destroy-cluster.yml -e confirm_destroy=yes
```

Every teardown in the session used this. Nothing was reset by hand.

---

## 7. Diagnostics that found the real bugs

Each of these was run to explain a failure, not to work around it.

```bash
# apt broken by a leftover install-media source
ssh root@192.168.56.134 'grep -rn cdrom /etc/apt/sources.list /etc/apt/sources.list.d/'

# kubeadm rejected the config: leading comments became a nil YAML document
ssh root@192.168.56.134 'grep -n "^---" /etc/kubernetes/kubeadm-config.yaml; head -8 /etc/kubernetes/kubeadm-config.yaml'

# "unknown service runtime.v1.RuntimeService" — containerd stub config
ssh root@192.168.56.134 'cat /etc/containerd/config.toml; ctr plugins ls | grep -i cri'

# Calico CRD missing — tigera-operator.yaml no longer ships CRDs
curl -sL .../v3.32.1/manifests/tigera-operator.yaml | grep -c "^kind: CustomResourceDefinition"
curl -sL .../v3.32.1/manifests/operator-crds.yaml   | grep -c "^kind: CustomResourceDefinition"

# NodePort worked on the node IP but not the VIP under nftables
ssh root@192.168.56.134 'nft list set ip kube-proxy nodeport-ips'
#   -> elements = { 192.168.56.134 }   (VIP absent)

# Teardown left interfaces behind — the awk kept the "@ifN" suffix
ssh root@192.168.56.134 'ip -o link show | grep cali'
#   -> calibe7a834de4c@if2   ->  ip link delete got an invalid name

# rmtree EPERM during reset — it was a mount, not a directory
ssh root@192.168.56.134 'grep -E "calico|cilium|kubelet" /proc/mounts'

# "DNS=FAIL" that was actually a broken test, not broken DNS
kubectl run dnsdiag --image=busybox:1.36 --restart=Never --command -- \
  sh -c 'nslookup httpd; echo "exit=$?"'
#   -> resolves correctly, then exits 1 on the trailing NXDOMAIN
```

---

## 8. Verifying a running cluster

```bash
ssh root@192.168.56.134 'export KUBECONFIG=/etc/kubernetes/admin.conf
  kubectl get nodes -o wide
  kubectl get pods -A -o wide
  kubectl get tigerastatus                    # calico
  cilium status                               # cilium
'

# kube-proxy / networking
ssh root@192.168.56.134 '
  curl -s http://127.0.0.1:10249/proxyMode
  nft list set ip kube-proxy nodeport-ips
  nft list table ip kube-proxy | grep -A2 "chain service-.*httpd"
  ipvsadm -Ln
  crictl version
'

# kube-vip
ssh root@192.168.56.134 '
  ip -4 -o addr show | grep 192.168.56.100
  kubectl --kubeconfig /etc/kubernetes/admin.conf -n kube-system \
    get lease plndr-cp-lock -o jsonpath="{.spec.holderIdentity}"
'
curl -sk https://192.168.56.100:6443/healthz

# forwarding sysctls
ssh root@192.168.56.134 'sysctl -n net.ipv4.ip_forward net.ipv6.conf.all.forwarding \
  net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables'
```

---

## 9. Workload testing

```bash
scp examples/httpd.yaml root@192.168.56.134:/tmp/
ssh root@192.168.56.134 'export KUBECONFIG=/etc/kubernetes/admin.conf
  kubectl apply -f /tmp/httpd.yaml
  kubectl rollout status deployment/httpd --timeout=180s
'

# Traffic paths
CIP=$(ssh root@192.168.56.134 'kubectl --kubeconfig /etc/kubernetes/admin.conf get svc httpd -o jsonpath="{.spec.clusterIP}"')
ssh root@192.168.56.134 "curl -s -o /dev/null -w '%{http_code}\n' http://$CIP/"
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.56.134:30080/    # NodePort
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.56.100:30080/    # via VIP

# Load balancing — use >=50 requests, nftables picks randomly
ssh root@192.168.56.134 "for i in \$(seq 1 100); do
  curl -s http://$CIP/ | grep -oE 'httpd-[a-z0-9]+-[a-z0-9]+'; done | sort | uniq -c"
```

---

## 10. Network / environment forensics

```bash
# Who is on the subnet, and what are they?
for i in $(seq 1 254); do (ping -c1 -W1 192.168.56.$i >/dev/null 2>&1 \
  && echo "192.168.56.$i ALIVE") & done; wait
ip neigh show dev ens33 | sort -t. -k4 -n
#   00:50:56 = VMware infrastructure, 00:0c:29 = VMware guest
#   -> .1 host adapter, .2 NAT gateway, .254 DHCP server  => VMware NAT, not VirtualBox
#   -> DHCP pool .128-.254, so .140 was a BAD VIP choice; .100 is safe

# Is .134 on a DHCP lease?
journalctl -u NetworkManager | grep -i "dhcp4.*lease"
nmcli -g ipv4.method connection show netplan-ens33
```

---

## 11. Repo self-checks

```bash
# Every declared variable documented in COMMANDS.md?
#   NOTE: regex MUST allow digits, or vars like enable_ipv6_forwarding are missed
for f in inventory/group_vars/all.yml roles/*/defaults/main.yml; do
  grep -E "^[a-z][a-z0-9_]*:" "$f" | sed 's/:.*//'
done | sort -u | while read v; do
  grep -q "\b$v\b" COMMANDS.md || echo "MISSING: $v"
done

# Does .133 appear as a target anywhere?
ansible-inventory --list | python3 -c '
import json,sys
hv=json.load(sys.stdin)["_meta"]["hostvars"]
print([h for h,v in hv.items() if "192.168.56.133" in (v.get("ansible_host"), v.get("node_ip"))])'

# All playbooks parse
for p in playbooks/*.yml; do ansible-playbook --syntax-check "$p" >/dev/null \
  && echo "OK $p" || echo "FAIL $p"; done
```

---

## 12. Summary of what was run

| Playbook | Times run | Outcome |
|---|---|---|
| `preflight.yml` | ~6 | always read-only |
| `create-cluster.yml` | 10 | first 6 exposed real bugs; later ones clean, ~2.5 min |
| `destroy-cluster.yml` | 6 | first 2 exposed teardown bugs; rest clean |
| `set-static-ip.yml` | 1 | clean, with rollback timer armed and cancelled |
| `add-worker.yml` / `add-master.yml` | 0 | no second VM available to join |

Everything destructive went through a playbook. The only manual mutations were:
`apt-get install ansible-core` on the control node, one `ip link delete tunl0`
and one `kubectl patch` of the kube-proxy ConfigMap — both purely to diagnose or
verify a fix before committing it to a role.
