# XRootD Integration Testing Framework

This is the XRootD Integration testing Framework.

As of Q2-2025 this supports bringing up 3 managed servers which have configurations given in the test-suite.

## Assumptions

These tests are built/tested with the following assumptions in mind:

```
1. XRootD has the uid/gid 1000:1000
2. All servers involved are setup as 'normal' grid servers with host certs etc.
3. The Podman socket is rootful allowing containers to run with net=host and use priviledged ports. The latter also preserves the hostname when running in the container.
4. 1 XRootD service will run per host.
   This is due to:
    a) Having the same ports used for various servers in a deployment.
    b) Having host-name rDNS explicitly built into several features.
    (This means in a cloud-env the `/etc/hosts` has been modified to work with XRootD.)
5. User-Auth'n and proxy credential renewal is handled externally to the running of these tests.
   (This may change, but for now it's assumed that this is something simply handled by the user.)
```

## Host Requirements

To successfully run the XRootD Integration Testing Framework, each host that will run XRootD server containers **must** meet the following requirements:

### 1. Podman Service

- **Podman must be installed and running as a service** on each host.
- The Podman socket (e.g., `/run/user/1000/podman/podman.sock`) must be accessible to the user running the tests.
- Ensure your user has permission to interact with Podman (typically by being in the appropriate group or running as the user who owns the socket).

### 2. Grid Certificates and CRLs

- Each host must have a valid **Grid Host Certificate** and **Host Key**:
  - `hostcert.pem` and `hostkey.pem` should be present at:
    - `/etc/grid-security/xrootd/hostcert.pem`
    - `/etc/grid-security/xrootd/hostkey.pem`
- **Certificate Revocation Lists (CRLs)** must be up to date:
  - CRLs should be stored under: `/etc/grid-security/certificates`
  - XRootD will refuse to start if CRLs are missing or outdated.

### 3. VOMS and User Credentials

- Valid user credentials and VOMS configuration should be present as required by your site and test setup.
- These files should be in their standard locations so they can be mounted into the XRootD containers as needed.

### 4. Mounting into Containers

- The above directories and files will be mounted into the XRootD containers at runtime.
- Ensure permissions allow the Podman service and containers to read these files.

---

**Summary:**  
- Podman must be running as a service and accessible.
- Grid host certificates, keys, and CRLs must be present and up to date in standard locations.
- VOMS/user credentials must be available as required.
- All required files and directories must be mountable into the XRootD containers.

## Test Configuration File Layout

Each test is described by a JSON configuration file. This file defines the servers to launch, the test client to run, and any artefacts or environment variables required for the test.

[Full Test Config Reference](testConfig.md)

