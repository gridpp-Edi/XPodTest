#!/bin/env python3

import sys
from XRootD.client import File
from XRootD.client.flags import OpenFlags

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <input_path> <output_path>")
    sys.exit(1)

input_path = sys.argv[1]
output_path = sys.argv[2]
chunk_size = 64 * 1024  # 64 KB

# Open remote file
source = File()
status, _ = source.open(input_path, OpenFlags.READ)
if not status.ok:
    raise RuntimeError(f"Failed to open remote file: {status.message}")

# Get file size via stat
status, stat_info = source.stat()
if not status.ok or stat_info is None:
    raise RuntimeError(f"Failed to stat remote file: {status.message}")

# Stream and write to output
with open(output_path, "wb") as local_file:
    offset = 0
    while offset < stat_info.size:
        read_len = min(chunk_size, stat_info.size - offset)
        status, data = source.read(offset, read_len)
        if not status.ok:
            raise RuntimeError(f"Read failed at offset {offset}: {status.message}")
        local_file.write(data)
        offset += len(data)

source.close()
print(f"File copied successfully to {output_path}")

