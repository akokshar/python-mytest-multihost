#
# Copyright (C) 2014 pytest-multihost contributors. See COPYING for license
#

import getpass
import pytest
from subprocess import CalledProcessError
import contextlib
import os

import mytest_multihost
#import pytest_multihost.transport
from mytest_multihost.config import Config

try:
    from paramiko import AuthenticationException
except ImportError:
    class AuthenticationException(Exception):
        """Never raised"""

def get_conf_dict():
    return {
        'ssh_username': getpass.getuser(),
        'domains': [
            {
                'name': 'localdomain',
                'hosts': [
                    {
                        'name': 'localhost',
                        'external_hostname': 'localhost',
                        'ip': '127.0.0.1',
                        'role': 'local',
                    },
                    {
                        'name': 'localhost',
                        'external_hostname': 'localhost',
                        'ip': '127.0.0.1',
                        'username': '__nonexisting_test_username__',
                        'role': 'badusername',
                    },
                    {
                        'name': 'localhost',
                        'external_hostname': 'localhost',
                        'ip': '127.0.0.1',
                        'username': 'root',
                        'password': 'BAD PASSWORD',
                        'role': 'badpassword',
                    },
                ],
            },
        ],
    }

@pytest.fixture(scope='class')
def multihost(request):
    conf = get_conf_dict()
    mh = mytest_multihost.make_multihost_fixture(
        request,
        descriptions=[
            {
                'hosts': {
                    'local': 1,
                },
            },
        ],
        _config=Config.from_dict(conf),
    )
    assert conf == get_conf_dict()
    mh.host = mh.config.domains[0].hosts[0]
    return mh.install()


@contextlib.contextmanager
def _first_command(host):
    """If managed command fails, prints a message to help debugging"""
    try:
        yield
    except (AuthenticationException, CalledProcessError):
        print (
            'Cannot login to %s using default SSH key (%s), user %s. '
            'You might want to add your own key '
            'to ~/.ssh/authorized_keys.'
            'Or, run py.test with -m "not needs_ssh"') % (
                host.external_hostname,
                host.ssh_key_filename,
                getpass.getuser())
        raise


@pytest.mark.needs_ssh
class TestLocalhost(object):

    def test_echo(self, multihost):
        host = multihost.host

        with _first_command(host):
            echo = host.run_command(['echo', 'hello', 'world'])

        assert echo.stdout_text == 'hello world\n'

    def test_put_get_file_contents(self, multihost, tmpdir):
        host = multihost.host
        filename = str(tmpdir.join('test.txt'))
        with _first_command(host):
            host.put_file_contents(filename, 'test')
        result = host.get_file_contents(filename)
        assert result == b'test'

        result = host.get_file_contents(filename, encoding='utf-8')
        assert result == 'test'

    def test_get_file_contents_nonexisting(self, multihost, tmpdir):
        host = multihost.host
        filename = str(tmpdir.join('test.txt'))
        with pytest.raises(IOError):
            host.get_file_contents(filename)

    def test_mkdir(self, multihost, tmpdir):
        host = multihost.host
        filename = str(tmpdir.join('testdir'))
        with _first_command(host):
            host.transport.mkdir(filename)
        assert os.path.exists(filename)
        assert os.path.isdir(filename)

    def test_background(self, multihost):
        #import ipdb; ipdb.set_trace()
        host = multihost.host
        run_nc = 'nc -l -p 12080 > /tmp/filename.out'
        cmd = host.run_command(run_nc, bg=True, raiseonerr=False)
        send_file = 'nc -N localhost 12080 < /etc/resolv.conf'
        cmd1 = host.run_command(send_file)
        cmd.wait()
        assert cmd1.returncode == 0
