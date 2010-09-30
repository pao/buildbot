import time
import tempfile
import os
import subprocess
import json

import select
import errno

from twisted.python import log, failure
from twisted.internet import reactor, utils
from twisted.internet.task import LoopingCall
from twisted.web.client import getPage

from buildbot.changes import base, changes
from twisted.internet.protocol import ProcessProtocol

class GerritChangeSource(base.ChangeSource):
    """This source will maintain a connection to gerrit ssh server
    that will provide us gerrit events in json format."""
    
    compare_attrs = ["gerritserver", "gerritport"]
                     
    parent = None # filled in when we're added
    running = False
    
    def __init__(self, gerritserver, username, gerritport=29418):
        """
        @type  gerritserver: string
        @param gerritserver: the dns or ip that host the gerrit ssh server,

        @type  gerritport: int
        @param gerritport: the port of the gerrit ssh server,

        @type  username: string
        @param username: the username to use to connect to gerrit

        """
        
        self.gerritserver = gerritserver
        self.gerritport = gerritport
        self.username = username
    class LocalPP(ProcessProtocol):
        def __init__(self, change_source):
            self.change_source = change_source
            self.data = ""

        def outReceived(self, data):
            """ do line buffering"""
            self.data += data
            lines = self.data.split("\n")
            if self.data.endswith("\n"):
                self.data = ""
            else:
                self.data = lines.pop(-1) # last line is not complete
            for line in lines:
                self.change_source.lineReceived(line)
        def errReceived(self, data):
            print "gerrriterr:",data
        def processEnded(self, status_object):
            self.change_source.startService()

    def lineReceived(self, line):
        try:
            action = json.loads(line)
        except ValueError:
            print "bad json line:", line
            return
	if type(action) == type({}) and "type" in action.keys() and "change" in action.keys() and "submitter" in action.keys():
            acttype = action["type"]
            if acttype == "change-merged":
                change = action["change"]
                for i in change.keys():
                    action["change"+i] = change[i]
                patchSet = action["patchSet"]
                for i in patchSet.keys():
                    action["patchSet"+i] = patchSet[i]
                
                branch = change["branch"]
                author = change["owner"]
                email = author["email"]
                who = author["name"] + "<%s>"%(author["email"])
                c = changes.Change(who = who,
                                   files=[change["project"]],
                                   comments=change["subject"],
                                   isdir=1,
                                   branch = branch,
                                   properties = action)
                self.parent.addChange(c)
                    

    def startService(self):
        self.running = True
        self.process = reactor.spawnProcess(self.LocalPP(self), "ssh", ["ssh",self.gerritserver,"-p",str(self.gerritport), "gerrit","stream-events"])

    def stopService(self):
        self.running = False
        self.process.stop()
        return base.ChangeSource.stopService(self)

    def describe(self):
        status = ""
        if not self.running:
            status = "[STOPPED - check log]"
        str = 'GerritChangeSource watching the remote gerrit repository %s %s' \
                % (self.gerritserver, status)
        return str

    
