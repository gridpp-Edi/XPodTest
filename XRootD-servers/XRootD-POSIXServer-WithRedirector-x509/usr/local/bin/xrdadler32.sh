#!/bin/bash
# Log for debugging (optional)
echo "$(date) Invoked with: '$1'" >> /tmp/xrdadler32.log

FILE="$1"
if [ -z "$FILE" ] || [ ! -r "$FILE" ]; then
    echo "Cannot read $FILE" >&2
    exit 1
fi

CKSUM=$(xrdadler32 "$FILE" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "adler32 $CKSUM"
    exit 0
else
    echo "Checksum failed" >&2
    exit 1
fi

