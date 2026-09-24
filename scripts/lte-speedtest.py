#!/usr/bin/env python3
"""Short, interface-bound HTTPS throughput test (~66 MB payload by default)."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--interface", default="wwu1u1i8")
parser.add_argument("--output", default="/tmp/lte-speedtest.json")
args = parser.parse_args()
base = ["curl", "-4", "--interface", args.interface, "--noproxy", "*",
        "--connect-timeout", "10", "--max-time", "60", "--silent", "--show-error",
        "--output", "/dev/null", "--write-out", "%{json}"]
report = {"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "interface": args.interface, "method": "sequential single-stream HTTPS",
          "server": "speed.cloudflare.com", "measurements": []}
ping = subprocess.run(["ping", "-I", args.interface, "-c", "5", "-W", "3", "1.1.1.1"],
                      capture_output=True, text=True, timeout=25)
report["ping"] = ping.stdout + ping.stderr
print(report["ping"], flush=True)
with tempfile.NamedTemporaryFile(prefix="lte-speedtest-") as payload:
    payload.write(b"\0" * 8_000_000)
    payload.flush()
    for direction, size in [("download", 25_000_000), ("download", 25_000_000),
                            ("upload", 8_000_000), ("upload", 8_000_000)]:
        extra = ([f"https://speed.cloudflare.com/__down?bytes={size}"]
                 if direction == "download" else
                 ["--header", "Content-Type: application/octet-stream",
                  "--data-binary", "@" + payload.name, "https://speed.cloudflare.com/__up"])
        result = subprocess.run(base + extra, capture_output=True, text=True, timeout=70)
        data = json.loads(result.stdout)
        key = "size_download" if direction == "download" else "size_upload"
        valid = result.returncode == 0 and data["http_code"] == 200 and int(data[key]) == size
        measurement = {"direction": direction, "valid": valid, "curl": data,
                       "error": result.stderr, "mbps": size * 8 / data["time_total"] / 1_000_000
                       if valid and data["time_total"] > 0 else None}
        report["measurements"].append(measurement)
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(json.dumps({"direction": direction, "valid": valid,
                          "mbps": measurement["mbps"], "http": data["http_code"],
                          "local_ip": data["local_ip"], "seconds": data["time_total"]}), flush=True)
        if not valid:
            raise SystemExit("Transfer failed; partial results saved, remaining tests stopped.")
for direction in ("download", "upload"):
    rows = [m for m in report["measurements"] if m["direction"] == direction]
    key = "size_download" if direction == "download" else "size_upload"
    rate = sum(m["curl"][key] for m in rows) * 8 / sum(m["curl"]["time_total"] for m in rows) / 1e6
    report[direction + "_mbps"] = rate
Path(args.output).write_text(json.dumps(report, indent=2))
print(json.dumps({k: report[k] for k in ("download_mbps", "upload_mbps")}), flush=True)
