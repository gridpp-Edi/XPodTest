#!/bin/bash

# Start cmsd
/usr/bin/cmsd -c /etc/xrootd/xrootd-posix-storage-2.conf &

# Start xrootd
exec /usr/bin/xrootd -c /etc/xrootd/xrootd-posix-storage-2.conf

# Wait on both
#wait -n

