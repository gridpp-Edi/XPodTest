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

# Stream using readchunks()
with open(output_path, "wb") as out_file:
    for chunk in source.readchunks(chunk_size):
        out_file.write(chunk)

source.close()
print(f"File streamed successfully to {output_path}")

