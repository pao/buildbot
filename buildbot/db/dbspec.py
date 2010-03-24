# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla-specific Buildbot steps.
#
# The Initial Developer of the Original Code is
# Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Brian Warner <warner@lothar.com>
#   Chris AtLee <catlee@mozilla.com>
#   Dustin Mitchell <dustin@zmanda.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

import sys, os, cgi, re, time

from twisted.python import log, reflect
from twisted.internet import defer, reactor
from twisted.enterprise import adbapi

from buildbot.db.connector import DBConnector
from buildbot.db.exceptions import *

class ExpiringConnectionPool(adbapi.ConnectionPool):
    """
    A Connection pool that expires connections after a certain amount of idle
    time.
    """
    def __init__(self, dbapiName, max_idle=60, *args, **kwargs):
        """
        @param max_idle: reconnect connections that have been idle more than
                         this number of seconds.
        """

        log.msg("Using expiring pool with max_idle=%i" % max_idle)

        adbapi.ConnectionPool.__init__(self, dbapiName, *args, **kwargs)
        self.max_idle = max_idle

        self.connection_lastused = {}

    def connect(self):
        tid = self.threadID()
        now = time.time()
        lastused = self.connection_lastused.get(tid)
        if lastused and lastused + self.max_idle < now:
            conn = self.connections.get(tid)
            if self.noisy:
                log.msg("expiring old connection")
            self.disconnect(conn)

        conn = adbapi.ConnectionPool.connect(self)
        self.connection_lastused[tid] = now
        return conn

    def disconnect(self, conn):
        adbapi.ConnectionPool.disconnect(self, conn)
        tid = self.threadID()
        del self.connection_lastused[tid]

class DBSpec(object):
    """
    A specification for the database type and other connection parameters.
    """

    # List of connkw arguments that are applicable to the connection pool only
    pool_args = ["max_idle"]
    def __init__(self, dbapiName, *connargs, **connkw):
        # special-case 'sqlite3', replacing it with the available implementation
        if dbapiName == 'sqlite3':
            dbapiName = self._get_sqlite_dbapi_name()

        self.dbapiName = dbapiName
        self.connargs = connargs
        self.connkw = connkw

    @classmethod
    def from_url(cls, url, basedir=None):
        """
        Parses a URL of the format
          driver://[username:password@]host:port/database[?args]
        and returns a DB object representing this URL.  Percent-
        substitution will be performed, replacing %(basedir)s with
        the basedir argument.

        raises ValueError on an invalid URL.
        """
        match = re.match(r"""
        ^(?P<driver>\w+)://
        (
            ((?P<user>\w+)(:(?P<passwd>\S+))?@)?
            ((?P<host>[-A-Za-z0-9.]+)(:(?P<port>\d+))?)?/
            (?P<database>\S+?)(\?(?P<args>.*))?
        )?$""", url, re.X)
        if not match:
            raise ValueError("Malformed url")

        d = match.groupdict()
        driver = d['driver']
        user = d['user']
        passwd = d['passwd']
        host = d['host']
        port = d['port']
        if port is not None:
            port = int(port)
        database = d['database']
        args = {}
        if d['args']:
            for key, value in cgi.parse_qsl(d['args']):
                args[key] = value

        if driver == "sqlite":
            # user, passwd, host, and port must all be None
            if not user == passwd == host == port == None:
                raise ValueError("user, passwd, host, port must all be None")
            if not database:
                database = ":memory:"
            else:
                database = database % dict(basedir=basedir)
                database = os.path.join(basedir, database)
            return cls("sqlite3", database, **args)
        elif driver == "mysql":
            args['host'] = host
            args['db'] = database
            if user:
                args['user'] = user
            if passwd:
                args['passwd'] = passwd
            if port:
                args['port'] = port
            if 'max_idle' in args:
                args['max_idle'] = int(args['max_idle'])

            return cls("MySQLdb", **args)
        else:
            raise ValueError("Unsupported dbapi %s" % driver)

    def _get_sqlite_dbapi_name(self):
        # see which dbapi we can use and return that name; prefer
        # pysqlite2.dbapi2 if it is available.
        sqlite_dbapi_name = None
        try:
            from pysqlite2 import dbapi2 as sqlite3
            sqlite_dbapi_name = "pysqlite2.dbapi2"
        except ImportError:
            # don't use built-in sqlite3 on 2.5 -- it has *bad* bugs
            if sys.version_info >= (2,6):
                import sqlite3
                sqlite_dbapi_name = "sqlite3"
            else:
                raise
        return sqlite_dbapi_name

    def get_dbapi(self):
        """
        Get the dbapi module used for this connection (for things like exceptions
        and module-global attributes
        """
        return reflect.namedModule(self.dbapiName)

    def get_sync_connection(self):
        """
        Get a synchronous connection to the specified database.  This returns a simple
        DBAPI connection object.
        """
        dbapi = self.get_dbapi()
        connkw = self.connkw.copy()
        for arg in self.pool_args:
            if arg in connkw:
                del connkw[arg]
        conn = dbapi.connect(*self.connargs, **connkw)
        return conn

    def get_async_connection_pool(self):
        """
        Get an asynchronous (adbapi) connection pool for the specified database.
        """

        # add some connection keywords
        connkw = self.connkw.copy()
        connkw["cp_reconnect"] = True
        connkw["cp_noisy"] = True

        # This disables sqlite's obsessive checks that a given connection is
        # only used in one thread; this is justified by the Twisted ticket
        # regarding the errors you get on connection shutdown if you do *not*
        # add this parameter: http://twistedmatrix.com/trac/ticket/3629
        if 'sqlite' in self.dbapiName:
            connkw['check_same_thread'] = False
        log.msg("creating adbapi pool: %s %s %s" % \
                (self.dbapiName, self.connargs, connkw))

        # MySQL needs support for expiring idle connections
        if self.dbapiName == 'MySQLdb':
            return ExpiringConnectionPool(self.dbapiName, *self.connargs, **connkw)
        else:
            return adbapi.ConnectionPool(self.dbapiName, *self.connargs, **connkw)
