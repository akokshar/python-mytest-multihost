#
# Copyright (C) 2013  Red Hat
# Copyright (C) 2014  pytest-multihost contributors
# See COPYING for license
#

"""Host class for integration testing"""

import os
import socket
import subprocess
import shlex

from pytest_multihost import transport
from pytest_multihost.util import check_config_dict_empty, shell_quote

from pytest_multihost.ssh_command import SSHCommand

try:
    basestring
except NameError:
    basestring = str


class BaseHost(object):
    """Representation of a remote host

    See README for an overview of the core classes.
    """
    transport_class = transport.SSHTransport
    command_prelude = ''

    def __init__(self, domain, hostname, role, ip=None,
                 external_hostname=None, username=None, password=None,
                 test_dir=None, host_type=None):
        self.host_type = host_type
        self.domain = domain
        self.role = str(role)
        if username is None:
            self.ssh_username = self.config.ssh_username
        else:
            self.ssh_username = username
        if password is None:
            self.ssh_key_filename = self.config.ssh_key_filename
            self.ssh_password = self.config.ssh_password
        else:
            self.ssh_key_filename = None
            self.ssh_password = password
        if test_dir is None:
            self.test_dir = domain.config.test_dir
        else:
            self.test_dir = test_dir

        shortname, dot, ext_domain = hostname.partition('.')
        self.shortname = shortname

        self.hostname = (hostname[:-1]
                         if hostname.endswith('.')
                         else shortname + '.' + self.domain.name)

        self.external_hostname = str(external_hostname or hostname)

        self.netbios = self.domain.name.split('.')[0].upper()

        self.logger_name = '%s.%s.%s' % (
            self.__module__, type(self).__name__, shortname)
        self.log = self.config.get_logger(self.logger_name)

        if ip:
            self.ip = str(ip)
        else:
            if self.config.ipv6:
                # $(dig +short $M $rrtype|tail -1)
                dig = subprocess.Popen(
                    ['dig', '+short', self.external_hostname, 'AAAA'])
                stdout, stderr = dig.communicate()
                self.ip = stdout.splitlines()[-1].strip()
            else:
                try:
                    self.ip = socket.gethostbyname(self.external_hostname)
                except socket.gaierror:
                    self.ip = None

            if not self.ip:
                raise RuntimeError('Could not determine IP address of %s' %
                                   self.external_hostname)

        self.host_key = None
        self.ssh_port = 22

        self.env_sh_path = os.path.join(self.test_dir, 'env.sh')

        self.log_collectors = []

    def __str__(self):
        template = ('<{s.__class__.__name__} {s.hostname} ({s.role})>')
        return template.format(s=self)

    def __repr__(self):
        template = ('<{s.__module__}.{s.__class__.__name__} '
                    '{s.hostname} ({s.role})>')
        return template.format(s=self)

    def add_log_collector(self, collector):
        """Register a log collector for this host"""
        self.log_collectors.append(collector)

    def remove_log_collector(self, collector):
        """Unregister a log collector"""
        self.log_collectors.remove(collector)

    @classmethod
    def from_dict(cls, dct, domain):
        """Load this Host from a dict"""
        if isinstance(dct, basestring):
            dct = {'name': dct}
        try:
            role = dct.pop('role').lower()
        except KeyError:
            role = domain.static_roles[0]

        hostname = dct.pop('name')
        if '.' not in hostname:
            hostname = '.'.join((hostname, domain.name))

        ip = dct.pop('ip', None)
        external_hostname = dct.pop('external_hostname', None)

        username = dct.pop('username', None)
        password = dct.pop('password', None)
        host_type = dct.pop('host_type', 'default')

        check_config_dict_empty(dct, 'host %s' % hostname)

        return cls(domain, hostname, role,
                   ip=ip,
                   external_hostname=external_hostname,
                   username=username,
                   password=password,
                   host_type=host_type)

    def to_dict(self):
        """Export info about this Host to a dict"""
        result = {
            'name': str(self.hostname),
            'ip': self.ip,
            'role': self.role,
            'external_hostname': self.external_hostname,
        }
        if self.host_type != 'default':
            result['host_type'] = self.host_type
        return result

    @property
    def config(self):
        """The Config that this Host is a part of"""
        return self.domain.config

    @property
    def transport(self):
        """
        transport property is for some reason is used in ipatests
        fake it for compatibility
        """
        return self


    def reset_connection(self):
        """Reset the connection

        The next time a connection is needed, a new Transport object will be
        made. This new transport will take into account any configuration
        changes, such as external_hostname, ssh_username, etc., that were made
        on the Host.
        """
        try:
            del self._transport
        except:
            pass

    def get_file_contents(self, filename, encoding=None):
    
        if not self.file_exists(filename):
            raise IOError

        self.log.info("GET {}".format(filename))

        cmd = self._exec_command(
            "cat {}".format(filename), 
            encoding=None
        )

        if cmd.returncode:
            return None

        contents = b''.join(cmd.out_data)
        if encoding:
            return contents.decode(encoding)
        return contents


    def put_file_contents(self, filename, contents):
        if not contents:
            return

        self.log.info("PUT {}".format(filename))

        self._exec_command(
            "tee 1>>/dev/null {}".format(filename),
            stdin_data=contents,
            encoding=None
        )


    def file_exists(self, filename):
        """Return true if the named remote file exists"""

        self.log.info('STAT {}'.format(filename))

        cmd = self._exec_command(
            "test -f {}".format(filename))

        if cmd.returncode == 0:
            return True
        return False


    def mkdir(self, path):
        self.log.info('MKDIR {}'.format(path))
        self._exec_command("mkdir -p {}".format(path))
           
    def mkdir_recursive(self, path):
        self.mkdir(path)

    def collect_log(self, filename):
        """Call all registered log collectors on the given filename"""
        for collector in self.log_collectors:
            collector(self, filename)

    def run_command(self, argv, set_env=True, stdin_text=None,
                    log_stdout=True, raiseonerr=True, cwd=None, 
                    bg=False):
        """Run the given command on this host

        Returns a Command instance. The command will have already run in the
        shell when this method returns, so its stdout_text, stderr_text, and
        returncode attributes will be available.

        :param argv: Command to run, as either a Popen-style list, or a string
                     containing a shell script
        :param set_env: If true, env.sh exporting configuration variables will
                        be sourced before running the command.
        :param stdin_text: If given, will be written to the command's stdin
        :param log_stdout: If false, standard output will not be logged
                           (but will still be available as cmd.stdout_text)
        :param raiseonerr: If true, an exception will be raised if the command
                           does not exit with return code 0
        :param cwd: The working directory for the command
        :param bg: If True, runs command in background
        """
        
        cmd_str = ""

        if cwd is None:
            cwd = self.test_dir

        if cwd:
            self.mkdir(cwd)
            cmd_str += "cd {} && ".format(cwd)

        if set_env and self.file_exists(self.env_sh_path):
            cmd_str += "source {} && ".format(self.env_sh_path)

        if self.command_prelude:
            cmd_str += "{} && ".format(self.command_prelude)

        if isinstance(argv, basestring):
            cmd_str += "( {} )".format(argv)
            cmd = shlex.split(cmd_str)
        else:
            cmd = shlex.split(cmd_str) + ['('] + argv + [')']

        return self._exec_command(cmd, stdin_data=stdin_text, bg=bg)


    def _exec_command(self, command, stdin_data=None,
                        bg=False, encoding='utf-8'):

#        import pydevd
#        pydevd.settrace('10.43.21.202', port=3333, stdoutToServer=True, 
#                stderrToServer=True)

        cmd = SSHCommand(self.hostname, user=self.ssh_username, 
                identity=self.ssh_key_filename,
                command=command, encoding=encoding, logger=self.log)

        if stdin_data:
            cmd.send(stdin_data)

        if not bg:
            cmd.wait()
            self.log.info("RETURNCODE {}".format(cmd.returncode))
            if cmd.returncode:
                self.log.info("STDERR {}".format(cmd.stderr_text))
                #import ipdb; ipdb.set_trace()

        return cmd


class Host(BaseHost):
    """A Unix host"""
    command_prelude = 'set -e'


class WinHost(BaseHost):
    """
    Representation of a remote Windows host.
    """

    def __init__(self, domain, hostname, role, **kwargs):
        # Set test_dir to the Windows directory, if not given explicitly
        kwargs.setdefault('test_dir', domain.config.windows_test_dir)
        super(WinHost, self).__init__(domain, hostname, role, **kwargs)
