
from buildbot.status.web.base import HtmlResource
from collections import defaultdict
import buildbot
import twisted
import sys
import jinja2


class BuilderChangelog(HtmlResource):
    title = "Builder Changelog"
    
    stat = None
    builder_str = ''
    build_from_str = ''
    build_to_str = ''

    def __init__(self, builder_str, build_from_str, build_to_str):
        HtmlResource.__init__(self)
        self.builder_str = builder_str
        self.build_from_str = build_from_str
        self.build_to_str = build_to_str

    def parse_synclog(self, log, accum_change = None):
        if accum_change is None:
            accum_change = defaultdict(lambda: defaultdict(list))
        skip_a_bit = False
        for l in log.getText().split('\n'):
            if "git://" in l:
		if "github.com" in l or "android.git.kernel.org" in l:
                    skip_a_bit = False
                    url_base = l.strip().split('//')[1]
                else:
                    skip_a_bit = True
            if skip_a_bit:
                continue
            if "->" in l:
                details = l.strip().split()
                #explicit froyo check to improve snr
                if "[new branch]" in l and "froyo" in l:
                    sha1s = [None]
                    branch = details[3]
                elif "froyo" in l:
                    if details[0] == "+":
                        del details[0]
                    sha1s = details[0].split('..')
                    branch = details[1]
                else:
                    continue
                accum_change[url_base][branch].extend(sha1s)
            elif l == '\n' or "Initializing project" in l:
                pass
            else:
                #unrecognized line
                pass 
        return accum_change

    def delta_synclog(self, net_change):
        # Turn the net change dictionary into links
        delta_links = []
        for base_url, branchlog in net_change.iteritems():
            for branch, sha1s in branchlog.iteritems():
                if sha1s[0] is None:
                    if "github" in base_url:
                        delta_links.append(''.join(['New: http://',
                                                    base_url,
                                                    '/commits/',
                                                    branch,
                                                    ]))
                    else:
                        url_parts = base_url.split('/')
                        delta_links.append(''.join(['New: http://',
                                                    url_parts[0],
                                                    '/?p=',
                                                    '/'.join(url_parts[1:]),
                                                    '.git;a=shortlog',
                                                    ]))
                else:
                    if "github" in base_url:
                        delta_links.append(''.join(['http://',
                                                    base_url,
                                                    '/compare/',
                                                    sha1s[0],
                                                    '...',
                                                    sha1s[-1],
                                                    ]))
                    else:
                        url_parts = base_url.split('/')
                        delta_links.append(''.join(['http://',
                                                    url_parts[0],
                                                    '/?p=',
                                                    '/'.join(url_parts[1:]),
                                                    '.git;a=commitdiff;hp=',
                                                    sha1s[0],
                                                    ';h=',
                                                    sha1s[-1],
                                                    ]))
        return delta_links

    def emit_changelinks(self, which, build_from, build_to):
        b = self.stat.getBuilder(which)

        if "repo sync" in [s.getName() for s in b.getBuild(-1).getSteps()
                            if s.isFinished()]:
            build_latest = b.getBuild(-1).getNumber()
        else:
            build_latest = b.getBuild(-2).getNumber()
        if build_from is None:
            build_from = build_latest - 1
        else:
            build_from = int(build_from)
        if build_to is None:
            build_to = build_latest
        else:
            build_to = int(build_to)
            
        if build_from >= build_to:
            return 'Final build (%d) should be later than source build (%d).' % (build_to, build_from), build_from, build_to
        if build_from < 0 or build_from > build_latest-1:
            return 'Source build (%d) must be between 0 and %d.' % (build_from, build_latest-1), build_from, build_to
        if build_to < 1 or build_to > build_latest:
            return 'Final build (%d) must be between 1 and %d.' % (build_to, build_latest), build_from, build_to
            
        commitlogs = None
        for i in range(build_from+1, build_to+1):
            commitlogs = self.parse_synclog([s.getLogs()[0] for s in b.getBuild(i).getSteps() 
                if s.getName() == "repo sync"][0], commitlogs)
        delta_links = self.delta_synclog(commitlogs)
        return '<br />'.join(['<a href="%s">%s</a>' % (l,l) for l in delta_links]), build_from, build_to

    def content(self, request, cxt):
        self.stat = self.getStatus(request)
        (links_str, build_from, build_to) = self.emit_changelinks(self.builder_str, self.build_from_str, self.build_to_str)

        cxt.update(dict(changelinks=links_str,
                        builder=self.builder_str,
                        build_from=build_from,
                        build_to=build_to,
                        ))

        template = request.site.buildbot_service.templates.get_template("changelog.html")
        template.autoescape = True
        return template.render(**cxt)

class BuilderChangelogParent(HtmlResource):
    builder_str = ''
    def __init__(self, builder_str):
        HtmlResource.__init__(self)
        self.builder_str = builder_str
        
    def getChild(self, name, request):
        buildnums = [num for num in name.split('.') if num != '']
        if len(buildnums) == 0:
            build_from = None
            build_to = None
        elif len(buildnums) == 1:
            build_from = buildnums[0]
            build_to = None
        else:
            build_from = buildnums[0]
            build_to = buildnums[1]
        return BuilderChangelog(self.builder_str, build_from, build_to)

    def content(self, request, cxt):
        cxt.update(dict(content="<h2>Must name a builder.</h2>"))
        template = request.site.buildbot_service.templates.get_template("empty.html")
        template.autoescape = True
        return template.render(**cxt)

class Changelog(HtmlResource):
    def getChild(self, name, request):
        return BuilderChangelogParent(name)
