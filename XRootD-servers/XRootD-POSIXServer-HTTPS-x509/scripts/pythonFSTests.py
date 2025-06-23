#!/bin/env python3

from XRootD import client
from XRootD.client.flags import DirListFlags, OpenFlags, MkDirFlags, QueryCode
import tempfile
import os
import sys

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <server> <filename>")
    sys.exit(1)

server = sys.argv[1]
target_path = sys.argv[2]
print(f"Connecting to {server}")

xrd = client.FileSystem(server)

# 1. List /data and check for testFile
print("Listing /data...")
status, listing = xrd.dirlist('/data', DirListFlags.STAT)
assert status.ok, f"Directory listing failed: {status.message}"

file_names = [entry.name for entry in listing]
assert 'testFile' in file_names, "'testFile' not found in /data"

# 2. Stat the file
print("Checking file size...")
test_file_entry = next((e for e in listing if e.name == 'testFile'), None)
assert test_file_entry is not None, "testFile not found in dir listing"
assert test_file_entry.statinfo.size > 0, "testFile exists but is empty"

# 3. Open and read first 1024 bytes
print("Reading file header...")
f = client.File()
status, _ = f.open(f'{server}//data/testFile', OpenFlags.READ)
assert status.ok, f"Failed to open testFile: {status.message}"

status, data = f.read(0, 1024)
assert status.ok, f"Read failed: {status.message}"
assert len(data) > 0, "No data returned from read"
f.close()

# 4. Query SPACE info
print("Querying server space info...")
status, response = xrd.query(QueryCode.SPACE, '/data')
assert status.ok, f"Query for space info failed: {status.message}"
assert 'oss.space' in response.decode(), "Missing 'oss.space' in query response"

# 5. Locate file
print("Locating file on server...")
status, locations = xrd.locate('/data/testFile', OpenFlags.REFRESH)
assert status.ok, f"Locate failed: {status.message}"
assert any(loc.is_server for loc in locations.locations), "No server found for file"

# 6. mkdir + rmdir
print("Creating and removing test directory...")
test_dir = f"/data/xrdtest-{os.getpid()}"
status, _ = xrd.mkdir(test_dir, MkDirFlags.MAKEPATH)
assert status.ok, f"mkdir failed: {status.message}"

status, _ = xrd.rmdir(test_dir)
assert status.ok, f"rmdir failed: {status.message}"

# 7. Copy testFile to testFile2 on server
copied_file = '/data/testFile2'
print(f"Copying {target_path} → {copied_file}...")
status, _ = xrd.copy(server+'/'+target_path, server+'/'+copied_file, force=True)
assert status.ok, f"Remote copy failed: {status.message}"

# 8. Delete the copied file
print(f"Deleting {copied_file}...")
status, _ = xrd.rm(copied_file)
assert status.ok, f"rm failed: {status.message}"

print("✅ All XRootD tests passed successfully.")

