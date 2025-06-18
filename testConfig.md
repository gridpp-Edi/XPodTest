
### Example Structure

```json
{
  "name": "Example XRootD Test",
  "default_version": "gridppedi/xrdtesting:xrd-v5.8.3",
  "TEST_PATH": "/tmp/xrdtest",
  "servers": [
    {
      "server": "host1.example.com",
      "uri": "unix:///run/user/1000/podman/podman.sock",
      "version": "gridppedi/xrdtesting:xrd-v5.8.3",
      "server_config": {
        "entrypoint": ["/usr/bin/xrootd", "-c", "/etc/xrootd/xrootd-clustered.cfg"],
        "volumes": {
          "/etc/grid-security/xrootd": { "bind": "/etc/grid-security/xrootd", "mode": "ro" },
          "/etc/grid-security/certificates": { "bind": "/etc/grid-security/certificates", "mode": "ro" },
          "/tmp": { "bind": "/tmp", "mode": "ro" }
        },
        "host": "host1.example.com",
        "port": 1094
      }
    }
    // ... more servers as needed ...
  ],
  "test_config": {
    "uri": "unix:///run/user/1000/podman/podman.sock",
    "test_command": ["/usr/bin/xrdcp", "root://host1.example.com//tmp/testfile", "/dev/null"],
    "test_volumes": {
      "/etc/grid-security/xrootd": { "bind": "/etc/grid-security/xrootd", "mode": "ro" },
      "/etc/grid-security/certificates": { "bind": "/etc/grid-security/certificates", "mode": "ro" },
      "/tmp": { "bind": "/tmp", "mode": "ro" }
    },
    "test_env": {
      "XRD_LOGLEVEL": "DEBUG"
    },
    "artefact_paths": [
      "/tmp/xrdtest/testfile"
    ]
  }
}
```

### Key Fields

- **name**: (string) A human-readable name for the test.
- **default_version**: (string) Default container image version to use for servers and test client if not overridden.
- **TEST_PATH**: (string) Path used for test artefacts and substitutions.  
  **Note:** This directory is expected to exist on all hosts involved in the test and should contain any files or test-specific configuration needed by the test (such as test input files, reference data, or additional configs). Ensure this path is present and populated on every host before running the tests.
- **servers**: (list) List of server definitions. Each server should specify:
  - `server`: Hostname or identifier.
  - `uri`: Podman socket URI for the host.
  - `version`: (optional) Container image version for this server.
  - `server_config`: Entrypoint, volumes, host, and port for the server container.
    - `volumes`: (object) Each key is a host path, and the value is an object with:
      - `bind`: The path inside the container.
      - `mode`: Mount mode, e.g., `"ro"` for read-only or `"rw"` for read-write.
- **test_config**: (object) Configuration for the test client container:
  - `uri`: Podman socket URI where the test client should run.
  - `test_command`: Command to execute in the test client container.
  - `test_volumes`: Volumes to mount into the test client container, using the same structure as above.
  - `test_env`: (optional) Environment variables for the test client.
  - `artefact_paths`: (optional) List of artefact file paths to be cleaned up after the test.

**Note:**  
- All paths and URIs should be valid and accessible from the host running the test framework.
- The `uri` under `test_config` determines where the test client container is launched.
- The `artefact_paths` are cleaned up using the Podman service associated with the relevant server.
- The `volumes` structure follows the format:  
  `"<host_path>": { "bind": "<container_path>", "mode": "<ro|rw>" }`

