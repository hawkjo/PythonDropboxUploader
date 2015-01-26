import sys
import os
import gzip
import paramiko


def get_gzip_friendly_open_fnc(*args):
    """
    get_open_fnc returns the correct open function to use for file, gzip compatible.
    Arguments:
        Any number of file names, all of which are either gzipped or not.
    Returns:
        The open function to use: either 'open' or 'gzip.open'
    """
    fname_extensions = set([os.path.splitext(fname)[-1] for fname in args])
    if '.gz' not in fname_extensions:
        return open
    elif fname_extensions == set(['.gz']):
        import gzip
        return gzip.open
    else:
        sys.exit(
            'Error: All files must be of the same format and either fastq or gzipped fastq files.')


def gzip_friendly_open(fname, mode='r'):
    """
    gzip_friendly_open returns a file handle appropriate for the file, whether gzipped or not.
    """
    if os.path.splitext(fname)[-1] == '.gz':
        return gzip.open(fname, mode)
    else:
        return open(fname, mode)


class cd:
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        self.newPath = newPath

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class ssh:
    """
    Convenient wrapper class for paramiko allowing me the syntax:

        with ssh( 'borok' ) as ssh:
            stdin, stdout, stderr = ssh.ssh_client.exec_command( 'ls' )
            for line in stdout: print line.strip()
            ssh.sftp_client.put( 'filename' )
    """

    def __init__(self, hostname, username=None, password=None):
        self.hostname = hostname
        self.username = username
        self.password = password

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if self.username and self.password:
            self.ssh_client.connect(self.hostname, username=self.username, password=self.password)
        elif not self.username and not self.password:
            config = paramiko.SSHConfig()
            config.parse(open('/home/hawkjo/.ssh/config'))
            d = config.lookup(self.hostname)
            self.ssh_client.load_system_host_keys()
            self.ssh_client.connect(d['hostname'],
                                    username=d['user'],
                                    key_filename=d['identityfile'])
        else:
            sys.exit('SSH error: Either use config/keys or username/password')
        self.sftp_client = self.ssh_client.open_sftp()

    def close(self):
        self.sftp_client.close()
        self.ssh_client.close()

    def __enter__(self):
        return self

    def __exit__(self, etype, value, traceback):
        self.close()

    def sftp_mkdir_p(self, dir_path):
        try:
            self.sftp_client
        except:
            sys.exit('sftp_client not defined. Check docstring for proper usage.')

        if not dir_path:
            return

        self.sftp_client.chdir('.')
        starting_dir = self.sftp_client.getcwd()

        folders = dir_path.split('/')
        if folders[0] == '':
            self.sftp_client.chdir('/')
            folders = folders[1:]
        for folder in folders:
            try:
                self.sftp_client.chdir(folder)
            except IOError:
                self.sftp_client.mkdir(folder)
                self.sftp_client.chdir(folder)
        self.sftp_client.chdir(starting_dir)
