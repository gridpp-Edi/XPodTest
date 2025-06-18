
## About

This is the 'minimal' setup needed to run an XRootD server with 1 Redirector and 1 target which supports checking x509 authentication as well as enabling adler32 checksums of files it serves and 3rd party copies.

There is a 2nd posix endpoint config present named `-2` not attached to the redirector. This is for testing source/target copying only.

Some of the testing also involves placing 2 servers behind the 1 redirector and performing the same copy tests as with a normal POSIX server.

## Configuration

The main changes from a pure POSIX server implementation are:

1.
```
# NB This is where a lot of cloud based computing problems occur
# Make sure that the redirector authenticates with a cert which matches this hostname (not IP!)
all.manager xrd2.edi.scotgrid.ac.uk:1095
```
This is present in POSIX server(xrd1) and allows the REDIRECTOR(xrd2) to manage the lookup and metadata of files on this endpoint.

2.
```
all.role manager
all.manager xrd2.edi.scotgrid.ac.uk:1095
# Set this node as a redirector (does not serve data)

cmsd.allow host xrd1.edi.scotgrid.ac.uk
cmsd.allow host xrd2.edi.scotgrid.ac.uk
# Only allow this host to register as a data server
```
This is to allow the POSIX server(xrd1) to connect to the REDIRECTOR(xrd2) and the REDIRECTOR to act as a manager accepting external connections and requests.

## Tests

The tests which are run against this are the basic x509 copy in/out, 3rd party copies, adler32 checks and some basic stats.

## Servers

This config is composed of 1 server and can be brought up/down using:

Server1 Down:
```
podman-compose -f docker-compose-POSIX.yml down -t0
```

Server2 Down:
```
podman-compose -f docker-compose-REDIRECTOR.yml down -t0
```

Server1 Up:
```
podman-compose -f docker-compose-POSIX.yml up -d
```

Server2 Up:
```
podman-compose -f docker-compose-REDIRECTOR.yml up -d
```


