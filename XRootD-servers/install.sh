#!/bin/bash

cd XRootD-POSIXServer-x509/data
if [ ! -f testFile ]; then
  openssl rand -out testFile -base64 $(( 2**30 * 3/4 ))
  chown -R 1000:1000 ./testFile
fi
cd ../..

cd XRootD-POSIXServer-token/data
if [ ! -f testFile ]; then
  openssl rand -out testFile -base64 $(( 2**30 * 3/4 ))
  chown -R 1000:1000 ./testFile
fi
cd ../..

cd XRootD-POSIXServer-WithRedirector-x509/data
if [ ! -f testFile ]; then
  openssl rand -out testFile -base64 $(( 2**30 * 3/4 ))
  chown -R 1000:1000 ./testFile
fi
cd ../..

cd XRootD-POSIXServer-HTTPS-x509/data
if [ ! -f testFile ]; then
  openssl rand -out testFile -base64 $(( 2**30 * 3/4 ))
  chown -R 1000:1000 ./testFile
fi
cd ../..

