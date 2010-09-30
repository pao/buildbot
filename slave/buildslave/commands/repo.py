import os

from twisted.internet import defer

from buildslave.commands.base import SourceBaseCommand
from buildslave import runprocess
from buildslave.commands import utils


class Repo(SourceBaseCommand):
    """Repo specific VC operation. In addition to the arguments
    handled by SourceBaseCommand, this command reads the following keys:

    ['repourl'] (required):     the manifest GIT repository string
    ['repotarball'] (optional): the tarball base to accelerate the fetch
    ['manifest_branch'] (optional):     which manifest repo version (i.e. branch or tag) to
                               retrieve. Default: "master".
    ['manifest'] (optional):   Which manifest to use. Default: "default.xml".
    """

    header = "repo operation"

    def setup(self, args):
        SourceBaseCommand.setup(self, args)
        self.repourl = args['repourl']
        self.manifest_branch = args.get('manifest_branch')
        if not self.manifest_branch:
            self.manifest_branch = "master"
        self.manifest =  args.get('manifest')
        self.repotarball = args.get('repotarball')
        self.downloadrevision = None
        if not self.manifest:
            self.manifest = "default.xml"
        self.sourcedata = "%s -b %s -m %s\n" % (self.repourl, self.manifest_branch, self.manifest)
    def _tarCmd(self,cmds,callback):
            cmd = ["tar"]+cmds 
            c = runprocess.RunProcess(self.builder, cmd, self.builder.basedir,
                             sendRC=False, timeout=self.timeout,
                             maxTime=self.maxTime, usePTY=False)
            self.command = c
            cmdexec = c.start()
            cmdexec.addCallback(callback)
            return cmdexec

    def _fullSrcdir(self):
        return os.path.join(self.builder.basedir, self.srcdir)

    def _commitSpec(self):
        if self.revision:
            return self.revision
        return self.manifest_branch

    def sourcedirIsUpdateable(self):
        return os.path.isdir(os.path.join(self._fullSrcdir(), ".repo"))

    def _dovccmd(self, command, cb=None,abandonOnFailure=True, **kwargs):
        repo = self.getCommand("repo")
        c = runprocess.RunProcess(self.builder, [repo] + command, self._fullSrcdir(),
                         sendRC=False, timeout=self.timeout,
                         maxTime=self.maxTime, usePTY=False, **kwargs)
        self.command = c
        d = c.start()
        if cb:
            if abandonOnFailure:
                d.addCallback(self._abandonOnFailure)
            d.addCallback(cb)
        return d

    # If the repourl matches the sourcedata file, then
    # we can say that the sourcedata matches.  We can
    # ignore branch changes, since Git can work with
    # many branches fetched, and we deal with it properly
    # in doVCUpdate.
    def sourcedataMatches(self):
        try:
            olddata = self.readSourcedata()
            if not olddata.startswith(self.repourl+' '):
                return False
        except IOError:
            return False
        return True


    def doVCFull(self):
        os.makedirs(self._fullSrcdir())
        if self.repotarball and os.path.exists(self.repotarball):
            return self._tarCmd(['-xvzf',self.repotarball], self._doInit)
        else:
            return self._doInit(None)
    def _doInit(self,res):
        return self._dovccmd(['init', '-u',self.repourl,'-b',self.manifest_branch,'-m',self.manifest], self._didInit)

    def _didInit(self, res):
        return self.doVCUpdate()

    def doVCUpdate(self):
        command = ['forall', '-c', 'git', 'clean', '-f', '-d','-x']
        return self._dovccmd(command, self._doSync, abandonOnFailure=False)

    def _doSync(self, dummy):
        command = ['sync']
        self.sendStatus({"header": "synching manifest%s from branch %s from %s\n"
                                        % (self.manifest,self.manifest_branch, self.repourl)})
        return self._dovccmd(command, self._didSync)
    def _didSync(self, dummy):
        if self.repotarball and not os.path.exists(self.repotarball):
            return self._tarCmd(['-cvzf',self.repotarball,".repo"], self._doDownload)
        else:
            return self._doDownload(None)

    def _doDownload(self, dummy):
        if self.downloadrevision:
            command = ['download']+self.downloadrevision.split(' ')
            self.sendStatus({"header": "downloading changeset %s\n"
                                        % (self.revision)})
            return self._dovccmd(command, self._didDownload)
        return defer.succeed(0)
    def _didDownload(self, dummy):
        return defer.succeed(0)


    def parseGotRevision(self):
        command = ['manifest', '-o', '-']
        def _parse(res):
            return self.command.stdout
        return self._dovccmd(command, _parse, keepStdout=True)

