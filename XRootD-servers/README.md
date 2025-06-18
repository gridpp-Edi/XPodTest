
## README

It is assumed that this file be mounted into all of the servers to be used as part of the XRootD intgegration tests.

## General Observations

This folder contains the various XRootD server configs.

These files are tested/verified in this framework.

### Configuration Files

Due to opinions of this projects author.

This project WILL AVOID introducing the concept of control flow into the configuration files.
This adds complexity to part of the deployment which should be CRYSTAL CLEAR to avoid confusion.

Where it is explicit that different components (cmsd/xrootd) NEED different config files due to overlapping/conflicting configurables they will be passed explicitly different config files to avoid branching and if/else statements in the config.

We do NOT like 1 size fits all.

### XRootD configuration syntax

Documented in more detail here [XRootD docs](https://xrootd.web.cern.ch/doc/dev55/Syntax_config.htm).

However, as an observation configurable options for the XRootD files come in 2 formats.

Their main difference is in how they handle in-line comments. One DOES, one DOES NOT.

### 1 simple options

These are options such as hostname, port number.

These are parsed in such a way that an inline comment does no harm.

e.g.

This is valid:
```
cmsd.port 1095
```

This is also valid:
```
cmsd.port 1095 # This is the default cmsd port
```

### 2 string options

More complex configuration options (such as the parsing of the x509 Auth'n plugin for example) allow for many options to be passed in a string. This DOES NOT allow for in-line comments as above.

e.g.

This is valid:
```
xrootd.chksum adler32 /path/to/script.sh
# My Custon Adler32 script
```

This will give errors:
```
xrootd.chksum adler32 /path/to/script.sh # My Custom Adler32 script
```


## After install

After copying this to a shared storage area it's then advisible to run `install.sh` This will install fake data files into the relavent folders to be copied and tested with.