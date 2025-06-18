#!/bin/bash

## Start cmsd
/usr/bin/cmsd -c /etc/xrootd/xrootd-redirector.conf &

# Start xrootd
/usr/bin/xrootd -c /etc/xrootd/xrootd-redirector.conf &

# Wait on both
wait -n

