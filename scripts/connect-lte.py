#!/usr/bin/env python3
"""On-demand static IPv4 MBIM connection; preserves Ethernet/USB management.

Not a boot service or reconnect watchdog. NetworkManager must be inactive.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, timeout=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modem", default="0")
    parser.add_argument("--apn", default="telstra.extranet")
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[A-Za-z0-9.-]+", args.apn):
        raise SystemExit("Run as root with a valid APN.")
    if subprocess.run(["systemctl", "is-active", "--quiet", "NetworkManager"]).returncode == 0:
        raise SystemExit("Stop NetworkManager before using this direct ModemManager helper.")
    info = json.loads(run("mmcli", "-m", args.modem, "-J"))["modem"]
    if info["generic"]["state"] != "connected":
        print(run("mmcli", "-m", args.modem,
                  "--simple-connect=apn=" + args.apn + ",ip-type=ipv4"), end="")
        info = json.loads(run("mmcli", "-m", args.modem, "-J"))["modem"]
    candidates = []
    for path in info["generic"].get("bearers", []):
        bearer = json.loads(run("mmcli", "-b", path, "-J"))["bearer"]
        if bearer["status"]["connected"] == "yes" and bearer["properties"]["apn"] == args.apn:
            candidates.append(bearer)
    if len(candidates) != 1:
        raise SystemExit("Expected exactly one connected data bearer for this APN.")
    bearer = candidates[0]
    ipv4 = bearer["ipv4-config"]
    iface = bearer["status"]["interface"]
    if ipv4["method"] != "static" or not re.fullmatch(r"(?:wwu|wwan)[A-Za-z0-9_.-]*", iface):
        raise SystemExit("Expected a WWAN interface with static IPv4 bearer settings.")
    address = str(ipaddress.IPv4Interface(ipv4["address"] + "/" + ipv4["prefix"]))
    gateway = str(ipaddress.IPv4Address(ipv4["gateway"]))
    dns = [str(ipaddress.IPv4Address(value)) for value in ipv4["dns"]]
    mtu = int(ipv4["mtu"]) if ipv4["mtu"].isdigit() else 1500
    if not 576 <= mtu <= 65535:
        raise SystemExit("Invalid bearer MTU.")
    Path("/etc/systemd/network/10-router-wwan.network").write_text(
        "[Match]\nName=wwu* wwan*\n\n[Link]\nUnmanaged=yes\n")
    run("networkctl", "reload")
    run("networkctl", "reconfigure", iface)
    state_path = Path("/run/router-lte-state.json")
    if state_path.exists():
        old = json.loads(state_path.read_text())
        if old["interface"] == iface and old["address"] != address:
            old_address = str(ipaddress.IPv4Interface(old["address"]))
            subprocess.run(["ip", "address", "del", old_address, "dev", iface], check=False)
    run("ip", "link", "set", iface, "mtu", str(mtu), "up")
    run("ip", "address", "replace", address, "dev", iface)
    run("ip", "route", "replace", "default", "via", gateway, "dev", iface, "metric", "700")
    if dns:
        run("resolvectl", "dns", iface, *dns)
        run("resolvectl", "default-route", iface, "yes")
    state_path.write_text(json.dumps({"interface": iface, "address": address}))
    print(f"LTE connected: {iface}, {address}, APN {args.apn}; route metric 700")


if __name__ == "__main__":
    main()
