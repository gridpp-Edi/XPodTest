#!/bin/bash

# Start cmsd
/usr/bin/cmsd -c /etc/xrootd/xrootd-posix-storage-https.conf &

# Start xrootd
exec /usr/bin/xrootd -c /etc/xrootd/xrootd-posix-storage-https.conf

# Wait on both
wait -n

