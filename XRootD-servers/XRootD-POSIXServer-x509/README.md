
## About

This is the 'minimal' setup needed to run an XRootD server which supports checking x509 authentication as well as enabling adler32 checksums of files it serves and 3rd party copies.

.
├── docker-compose.yml
├── entrypoint.sh
├── etc
│   └── xrootd
│       └── xrootd-posix-storage.conf
├── scripts
│   ├── pythonChunkStream.py
│   ├── pythonStream.py
│   └── pythonVectorStream.py
└── usr
    └── local
        └── bin
            └── xrdadler32.sh

## Tests

The tests which are run against this are the basic x509 copy in/out, 3rd party copies, adler32 checks and some basic stats.

## Servers

This config is composed of 1 server and can be brought up/down using:

```
podman-compose -f docker-compose.yml down -t0
```

```
podman-compose -f docker-compose.yml up -d
```

