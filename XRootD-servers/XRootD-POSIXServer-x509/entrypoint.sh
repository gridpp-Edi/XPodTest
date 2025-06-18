#!/bin/bash

# Start cmsd
/usr/bin/cmsd -c /etc/xrootd/xrootd-posix-storage.conf &

# Start xrootd
exec /usr/bin/xrootd -c /etc/xrootd/xrootd-posix-storage.conf

# Wait on both
#wait -n

