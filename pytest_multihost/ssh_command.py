from subprocess import Popen, PIPE
import threading
import shlex
import sys

class SSHCommand():

    def __init__(self, hostname, 
            user="root", identity=None,
            command=None, encoding='utf-8', logger=None):
        """
        Execute command on a remote machine
        command should be a string or a Popen style list
        """
        #super(self, SSHCommand).__init__(self)

        self.logger = logger

        if isinstance(command, str):
            command = shlex.split(command)

        if identity is None:
            identity = "~/.ssh/id_rsa"

        # make control path with mktemp
        ssh_cmd = shlex.split(
            "ssh -T "
            "-l {user} "
            "-i {identity} "
            "-o UserKnownHostsFile=/dev/null "
            "-o ControlMaster=auto "
            "-o StrictHostKeyChecking=no "
            "-o ControlPersist=10m "
            "-o ControlPath=/tmp/mytest-%r@%h:%p"
            " {hostname}".format(user=user, identity=identity, hostname=hostname))

        ssh_cmd += command
        ssh_cmd = list(
            map(
                lambda x: x if len(shlex.split(x)) == 1 else '"{}"'.format(x), 
                ssh_cmd
            )
        )

        # Need to escape twice:
        # escape a symbol itself and escape an escape
        ssh_cmd = [x.replace('\\', '\\\\').replace('\\', '\\\\') for x in ssh_cmd]
        self.log(ssh_cmd)

        self.encoding = encoding
        self.returncode = None
        self.out_data = []
        self.err_data = []

        # do not set encoding for popen. It should be binary
        self.cmd = Popen(ssh_cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)

        self.out_thread = threading.Thread(
            target=self._do_recv_data, 
            args=(self.cmd.stdout, self.out_data)
        )
        self.out_thread.start()

        self.err_thread = threading.Thread(
            target=self._do_recv_data, 
            args=(self.cmd.stderr, self.err_data)
        )
        self.err_thread.start()

    def log(self, msg):
        if self.logger:
            self.logger.info("CMD {}".format(msg))

    def _do_recv_err(self):
        #print("_do_recv_err started")
        while True:
            data = self.cmd.stderr.read()
            
            if data == b'': #and not self.cmd.poll()
                break
            
            # error output is always text
            if self.encoding:
                data = data.decode(self.encoding)
            else:
                data = data.decode()
            
            self.err_data.append(data)
        #print("_do_recv_err stopped")

    def _do_recv_data(self, stream, store):
        """Read data out of stream until eof

        @param stream: stream object to read from
        @return array of bytearrays
        """

        while True:
            data = stream.read()

            if data == b'':
                break

            store.append(data)


    def _do_recv_out(self):
        #print("_do_recv_out started")
        while True:
            data = self.cmd.stdout.read()
            
            if data == b'': # and not self.cmd.poll()
                break
            
           # if self.encoding:
           #     try:
           #         data = data.decode(self.encoding)
           #     except UnicodeDecodeError:
           #         self.encoding = None
           #         pass

            self.out_data.append(data)

        #print("_do_recv_out stopped")

    def send(self, data=None):
        """
        Send data to a command stdin
        :param data - data to send
        """

        if not data:
            return

        if not isinstance(data, bytes):
            if self.encoding:
                data = data.encode(self.encoding)
            else:
                data = data.encode()

        self.cmd.stdin.write(data)
        self.cmd.stdin.flush()


    def wait(self):
        """ 
        TODO: prevent this to be executed twice.
        """

        if not self.returncode:
            self.cmd.stdin.close()
            self.out_thread.join()
            self.cmd.stdout.close()
            self.err_thread.join()
            self.cmd.stderr.close()

            self.returncode = self.cmd.wait()

        return self.returncode


    @property
    def stdout_text(self):
        if self.returncode is not None:
            stdout = b"".join(self.out_data)
            if self.encoding:
                try:
                    return stdout.decode(self.encoding)
                except UnicodeDecodeError:
                    # Probably a command returned binary data
                    # (hello, ipatests) just return bytes and continue.
                    pass    
            return stdout

        return ""
    
    @property
    def stderr_text(self):
        if self.returncode is not None:
            if self.encoding:
                return b"".join(self.err_data).decode(self.encoding)
            return b"".join(self.err_data).decode()

        return ""


