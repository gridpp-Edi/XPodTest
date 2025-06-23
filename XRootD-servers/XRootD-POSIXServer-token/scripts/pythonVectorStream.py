#!/bin/env python3

import sys
import zlib
import subprocess
from XRootD.client import File, flags
from XRootD.client.flags import OpenFlags, QueryCode

def compute_adler32(path):
    checksum = 1
    with open(path, 'rb') as f:
        while True:
            data = f.read(64 * 1024)
            if not data:
                break
            checksum = zlib.adler32(data, checksum)
    return format(checksum & 0xffffffff, '08x')

def get_remote_checksum(xrootd_url):
    from XRootD.client import File, flags
    import subprocess

    try:
        # Try native Python API if supported
        f = File()
        status, _ = f.open(xrootd_url, flags.OpenFlags.READ)
        if hasattr(f, "query"):
            status, result = f.query(flags.QueryCode.CKSUM)
            f.close()
            if not status.ok:
                raise RuntimeError(f"Checksum query failed: {status.message}")
            algo, checksum = result.strip().split()
            return algo, checksum
        f.close()
        raise AttributeError("query not supported by File")
    except Exception:
        # Fallback to xrdfs
        try:
            domain = xrootd_url.split("root://")[1].split("/")[0]
            path = xrootd_url.split(domain, 1)[1]
            cmd = ["xrdfs", domain, "query", "checksum", path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            # Look for line like: "adler32 adler32 ade687aa /data/testFile"
            for line in result.stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] in {"adler32", "md5"}:
                    algo = parts[1]
                    checksum = parts[2]
                    return algo, checksum

            raise RuntimeError(f"Unexpected checksum output:\n{result.stdout}")
        except Exception as e:
            raise RuntimeError(f"Failed to retrieve checksum using xrdfs fallback: {e}")

# Main
if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <input_path> <output_path>")
    sys.exit(1)

input_path = sys.argv[1]
output_path = sys.argv[2]
chunk_size = 64 * 1024
batch_size = 8

source = File()

# Open and stat
status, _ = source.open(input_path, OpenFlags.READ)
if not status.ok:
    raise RuntimeError(f"Failed to open remote file: {status.message}")

status, stat_info = source.stat()
if not status.ok or stat_info is None:
    raise RuntimeError(f"Failed to stat remote file: {status.message}")

# Stream with vector_read
size = stat_info.size
offset = 0
with open(output_path, "wb") as out_file:
    while offset < size:
        requests = []
        for _ in range(batch_size):
            if offset >= size:
                break
            read_len = min(chunk_size, size - offset)
            requests.append((offset, read_len))
            offset += read_len

        status, chunks = source.vector_read(requests)
        if not status.ok:
            raise RuntimeError(f"Vector read failed: {status.message}")
        for chunk in chunks:
            out_file.write(chunk.buffer)

source.close()

# Compare checksums
remote_algo, remote_cksum = get_remote_checksum(input_path)
local_cksum = compute_adler32(output_path)

print(f"Remote checksum ({remote_algo}): {remote_cksum}")
print(f"Local  checksum (adler32):   {local_cksum}")

if remote_cksum.lower() == local_cksum:
    print("✅ Checksums match.")
else:
    print("❌ Checksums do NOT match.")
    sys.exit(2)

