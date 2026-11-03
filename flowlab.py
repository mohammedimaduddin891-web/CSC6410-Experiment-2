#!/usr/bin/env python3
"""CSC 6410 Experiment 2: observe how one Open vSwitch chooses flow rules.

This script creates three isolated Mininet hosts attached to switch s1, without a
controller. It applies match/action rules and prints observations for comparison
with the earlier manual experiment. Run in the course lab container, not on a
production switch. Review and adapt this script before submitting it.
"""

import os
import subprocess
from datetime import datetime, timezone

from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch


def shell(*args):
    """Run an Open vSwitch command and show its real stdout or error."""
    print("\n$ " + " ".join(args), flush=True)
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(args)}")
    return result.stdout


def add_rule(spec):
    shell("ovs-ofctl", "add-flow", "s1", spec)


def show_rules(title):
    print("\n=== " + title + " ===", flush=True)
    shell("ovs-ofctl", "dump-flows", "s1")


def ping_all(net, title):
    print("\n=== " + title + " ===", flush=True)
    loss = net.pingAll()
    print(f"Observed overall packet loss: {loss:.1f}%", flush=True)


def ping_host(host, destination, title):
    print("\n=== " + title + " ===", flush=True)
    print(f"{host.name}$ ping -c 3 -W 1 {destination.IP()}", flush=True)
    print(host.cmd(f"ping -c 3 -W 1 {destination.IP()}").rstrip(), flush=True)


def main():
    setLogLevel("info")
    chosen = os.environ.get("MN_SWITCH", "ovsk")
    if chosen == "ovsk":
        datapath = "kernel"
    elif chosen == "ovs,datapath=user":
        datapath = "user"
    else:
        raise ValueError(f"Unexpected MN_SWITCH={chosen!r}; use the lab check's value")

    print("CSC 6410 — Experiment 2, automated flow-table observations", flush=True)
    print("Run time (UTC):", datetime.now(timezone.utc).isoformat(), flush=True)
    print(f"MN_SWITCH={chosen}; Open vSwitch datapath={datapath}", flush=True)
    shell("ovs-vsctl", "--version")

    net = Mininet(controller=None, autoSetMacs=True, build=False)
    h1 = net.addHost("h1", ip="10.0.0.1/8")
    h2 = net.addHost("h2", ip="10.0.0.2/8")
    h3 = net.addHost("h3", ip="10.0.0.3/8")
    s1 = net.addSwitch("s1", cls=OVSSwitch, datapath=datapath, failMode="secure")
    for host in (h1, h2, h3):
        net.addLink(host, s1)

    try:
        net.build()
        net.start()
        shell("ovs-vsctl", "set-fail-mode", "s1", "secure")
        shell("ovs-ofctl", "del-flows", "s1")
        show_rules("A: empty table in secure mode")
        ping_all(net, "A: ping without rules")

        # Three IPv4 destination rules; ARP has not been allowed yet.
        for number in (1, 2, 3):
            add_rule(f"priority=100,ip,nw_dst=10.0.0.{number},actions=output:{number}")
        ping_all(net, "B: only IPv4 destination rules")
        show_rules("B: IPv4 rule counters")

        # ARP flood enables the hosts to learn each other's MAC addresses.
        add_rule("priority=100,arp,actions=flood")
        ping_all(net, "C: IPv4 rules plus ARP")
        show_rules("C: successful-forwarding counters")

        # More specific drop at priority 200 wins over output priority 100.
        add_rule("priority=200,ip,nw_src=10.0.0.3,nw_dst=10.0.0.1,actions=drop")
        ping_host(h3, h1, "D: h3 -> h1, drop priority 200")
        ping_host(h2, h1, "D: h2 -> h1, unaffected by drop")
        show_rules("D: priority-200 drop counter")
        shell("ovs-appctl", "ofproto/trace", "s1",
              "in_port=3,ip,nw_src=10.0.0.3,nw_dst=10.0.0.1")

        # Reinstall same drop at priority 50; output priority 100 should win.
        shell("ovs-ofctl", "--strict", "del-flows", "s1",
              "priority=200,ip,nw_src=10.0.0.3,nw_dst=10.0.0.1")
        add_rule("priority=50,ip,nw_src=10.0.0.3,nw_dst=10.0.0.1,actions=drop")
        ping_host(h3, h1, "E: h3 -> h1, drop priority 50")
        show_rules("E: priority-50 drop counter")

        # Make ARP queries reach a visible catch-all drop rule.
        shell("ovs-ofctl", "del-flows", "s1", "arp")
        for host in (h1, h2, h3):
            print(f"\n{host.name}$ ip neigh flush all", flush=True)
            print(host.cmd("ip neigh flush all").rstrip(), flush=True)
        add_rule("priority=0,actions=drop")
        show_rules("F: table-miss counter before ping")
        ping_all(net, "F: table miss, no ARP rule")
        show_rules("F: table-miss counter after ping")

        # Switch to standalone to observe whether NORMAL forwarding appears.
        shell("ovs-ofctl", "del-flows", "s1")
        shell("ovs-vsctl", "set-fail-mode", "s1", "standalone")
        shell("ovs-vsctl", "get-fail-mode", "s1")
        show_rules("G: standalone table before ping")
        ping_all(net, "G: standalone ping")
        show_rules("G: standalone table after ping")
    finally:
        print("\nCleaning up the emulated network...", flush=True)
        net.stop()


if __name__ == "__main__":
    main()
