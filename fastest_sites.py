#!/usr/local/bin/python
#
# Author: Jordan Sissel
#
# This script will run through all entries for MASTER_SITE_* variables in
# bsd.sites.mk and emit the list of sites in order of who is probably fastest
# for your location
#
# The ordering is determined by the latency of connecting to the specific site.
#
# Usage: fastest_site.py [varname varname2 .. varnameN]
# 
# 'varname' is one of the MASTER_SITE_FOO variables from bsd.sites.mk.
# If no varnames are specified, all MASTER_SITE_* variables are tested.
# Otherwise, only the varnames given will be tested.
#
# The output is suitable for Makefiles, or make.conf. However, I recommend:
#
# in make.conf:
#   .include "/usr/local/etc/ports_sites.conf"
#
# and use:
#   ./fastest_site.py > /usr/local/etc/ports_sites.conf
#
# Doing so this way will allow you to regenerate ports_sites.conf on a whim
# without having to worry about obliterating anything in /etc/make.conf

import asyncore
import os
import re
import socket
import subprocess
import sys
import time
import urllib

INDENT = 8
socket.setdefaulttimeout(5)

class AsyncConnect(asyncore.dispatcher):
  schemes = {
    "http": 80,
    "ftp": 21,
    "https": 443,
  }

  def __init__(self, url, callback):
    asyncore.dispatcher.__init__(self)
    self._url = url
    self._start_time = time.time()
    self._callback = callback

    self.ParseURL()
    self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
    self.buffer = ""
    try:
      self.connect((self._host, self._port))
    except socket.gaierror:
      callback(self._url, 1000)
      self.close()

  def ParseURL(self):
    #print "Url: %s" % self._url
    (scheme, remainder) = self._url.split(":", 2)
    (host, unused_path) = urllib.splithost(remainder)
    self._host = host
    self._port = AsyncConnect.schemes[scheme]

  def handle_connect(self):
    pass

  def handle_read(self):
    pass

  def handle_write(self):
    duration = time.time() - self._start_time
    #print "=> %f: %s" % (duration, self._url)
    self._callback(self._url, duration)
    self.close()

def GetVariable(varname):
  if varname in os.environ:
    return os.environ[varname]
  make = "make -f /usr/ports/Makefile -V %s" % varname
  value = Run(make)
  if value[-1] == "\n":
    value = value[:-1]
  return value

def Run(cmd):
  proc = subprocess.Popen(["/bin/sh", "-c", cmd], stdout=subprocess.PIPE)
  data = proc.communicate()[0]
  proc.wait()
  return data

def FindFastest(varname, sitelist):
  latencies = {}

  # Ignore duplicates
  sitelist = set(sitelist)

  def callback(url, duration):
    latencies.setdefault(url, 0)
    latencies[url] += duration

  for url in sitelist:
    AsyncConnect(url, callback)
  count = len(sitelist)

  # We probaly don't need more than 10 results, so if there are more than 10
  # servers, lets only track the first few that return quickly:
  if count > 10:
    count = 10
  asyncore.loop(timeout=1, count=count)

  if not latencies:
    # No data has come back yet, let's wait
    print >>sys.stderr, " => Still waiting on data for %s" % varname
    asyncore.loop(timeout=30)

  # Close any still-open connections...
  asyncore.close_all()

  # Return the latency dict sorted by latency as list of (key, value)
  latency_list = sorted(latencies.iteritems(), key=lambda (a,b): (b,a))
  return latency_list

var_re = re.compile(r"^(MASTER_SITE_[A-Z_]+)\+?=")
sites_mk = "%s/Mk/bsd.sites.mk" % (GetVariable("PORTSDIR"))
sites = {}
bad_sites = {}
site_latency = {}

# Some sites use variables in them and due to the way we request the list of
# sites these variables are not set, resulting in useless urls like
# "http://.googlecode.com/files" because the original value was set to
# "http://${PORTNAME}.googlecode.com/files"
# We don't have access to those variables so we skip them.
# It also catches http://www..com just in case that pops up in the future
bad_site_regex = re.compile(r"(\/\/\.|\.\.|[a-zA-Z]\/\/)")

fd = open(sites_mk, "r")
for line in fd:
  match = var_re.search(line)
  if match:
    varname = match.group(1)
    output = Run("make -V %s -f %s" % (varname, sites_mk))

    site_is_bad = bad_site_regex.search(output)
    if site_is_bad:
      bad_sites[varname] = output.split()
    else:
      sites[varname] = output.split()

for (varname, sitelist) in sites.iteritems():
  if len(sys.argv) > 1 and varname not in sys.argv[1:]:
    continue

  print >>sys.stderr, \
      " => Checking servers for %s (%d servers)" % (varname, len(sitelist))
  latency_list = FindFastest(varname, sitelist)

  # Don't print the trailing slash on the last line.
  print "%s=\\" % varname
  print " \\\n".join(url for url, duration in latency_list)

  print
  sys.stdout.flush()

# Walk the dict of bad sites that we know cause problems.
# If explicitly asked to sort one of them be verbose about skipping it
# otherwise be silent.
for (varname, sitelist) in bad_sites.iteritems():
  if len(sys.argv) > 1 and varname in sys.argv[1:]:
    print >>sys.stderr, "Unable to sort %s - skipping." % varname
