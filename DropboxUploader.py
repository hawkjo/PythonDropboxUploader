#!/usr/bin/env python

import locale
import os
import pprint
import sys
import re
import shutil
import time
from dateutil.parser import parse
from dateutil.tz import tzlocal

PY3 = sys.version_info[0] == 3

if PY3:
    from io import StringIO
else:
    from StringIO import StringIO

from dropbox import client, rest, session

def command(login_required=True, num_tries=1):
    """a decorator for handling authentication and exceptions"""
    def decorate(f):
        def wrapper(self, *args, **kwargs):
            if login_required and self.api_client is None:
                self.out.write("Please 'login' to execute this command\n")
                return

            for i in xrange(num_tries):
                try:
                    return f(self, *args, **kwargs)
                except TypeError, e:
                    self.out.write('Error:' + str(e) + '\n')
                except rest.ErrorResponse, e:
                    if i < num_tries-1:
                        pass
                    elif e.status == 507:
                        self.out.write('\nError: Out of space.\n')
                        raise
                    else:
                        msg = e.user_error_msg or str(e)
                        self.out.write('Error: %s\n' % msg)
                except BufferError, e:
                    if i < num_tries-1:
                        pass

        wrapper.__doc__ = f.__doc__
        return wrapper
    return decorate

class DropboxUploader:
    """A convenient wrapper python interface to dropbox."""

    # Add the directory with your files here.
    BASE_DIR = os.path.expanduser('~/local/include/PythonDropboxUploader/')
    APP_KEY_FILE = os.path.join(BASE_DIR, 'app_key.txt')
    APP_SECRET_FILE = os.path.join(BASE_DIR, 'app_secret.txt')

    TOKEN_FILE = os.path.join(BASE_DIR, 'token_store.txt')

    def __init__(self):
        self.current_path = ''
        self.out = sys.stdout
        self.logging = False

        self.api_client = None
        try:
            serialized_token = open(self.TOKEN_FILE).read()
            if serialized_token.startswith('oauth1:'):
                access_key, access_secret = serialized_token[len('oauth1:'):].split(':', 1)
                sess = session.DropboxSession(self.APP_KEY, self.APP_SECRET)
                sess.set_token(access_key, access_secret)
                self.api_client = client.DropboxClient(sess)
                self.out.write("[loaded OAuth 1 access token]\n")
            elif serialized_token.startswith('oauth2:'):
                access_token = serialized_token[len('oauth2:'):]
                self.api_client = client.DropboxClient(access_token)
                self.out.write("[loaded OAuth 2 access token]\n")
            else:
                self.out.write("Malformed access token in %r.\n" % (self.TOKEN_FILE,))
        except IOError:
            pass # don't worry if it's not there

        try:
            self.app_key = open(self.APP_KEY_FILE).read()
            self.app_secret = open(self.APP_SECRET_FILE).read()
        except:
            self.out.write("""Error reading app info. Please store your app key and secret in the files:
            <base dir>/app_key.txt
            <base dir>/app_secret.txt

            """)
            raise

    def __del__(self):
        self.end_log()

    @command()
    def ls(self):
        """list files in current remote directory"""
        resp = self.api_client.metadata(self.current_path)
        if 'contents' in resp:
            encoding = locale.getdefaultlocale()[1] or 'ascii'
            return [os.path.basename(f['path']).encode(encoding) for f in resp['contents']]

    @command()
    def cd(self, path=None):
        """change current working directory"""
        if path is None:
            self.current_path = ''
        elif path == "..":
            self.current_path = "/".join(self.current_path.split("/")[0:-1])
        else:
            self.current_path += "/" + path

    @command()
    def pwd(self):
        """print current remote working directory"""
        self.out.write(self.current_path + '\n')

    @command(login_required=False)
    def login(self):
        """log in to a Dropbox account"""
        flow = client.DropboxOAuth2FlowNoRedirect(self.APP_KEY, self.APP_SECRET)
        authorize_url = flow.start()
        self.out.write("1. Go to: " + authorize_url + "\n")
        self.out.write("2. Click \"Allow\" (you might have to log in first).\n")
        self.out.write("3. Copy the authorization code.\n")
        code = raw_input("Enter the authorization code here: ").strip()

        try:
            access_token, user_id = flow.finish(code)
        except rest.ErrorResponse, e:
            self.out.write('Error: %s\n' % str(e))
            return

        with open(self.TOKEN_FILE, 'w') as f:
            f.write('oauth2:' + access_token)
        self.api_client = client.DropboxClient(access_token)

    @command(login_required=False)
    def login_oauth1(self):
        """log in to a Dropbox account"""
        sess = session.DropboxSession(self.APP_KEY, self.APP_SECRET)
        request_token = sess.obtain_request_token()
        authorize_url = sess.build_authorize_url(request_token)
        self.out.write("1. Go to: " + authorize_url + "\n")
        self.out.write("2. Click \"Allow\" (you might have to log in first).\n")
        self.out.write("3. Press ENTER.\n")
        raw_input()

        try:
            access_token = sess.obtain_access_token()
        except rest.ErrorResponse, e:
            self.out.write('Error: %s\n' % str(e))
            return

        with open(self.TOKEN_FILE, 'w') as f:
            f.write('oauth1:' + access_token.key + ':' + access_token.secret)
        self.api_client = client.DropboxClient(sess)

    @command()
    def logout(self):
        """log out of the current Dropbox account"""
        self.api_client = None
        os.unlink(self.TOKEN_FILE)
        self.current_path = ''

    @command()
    def cat(self, path):
        """display the contents of a file"""
        f, metadata = self.api_client.get_file_and_metadata(self.current_path + "/" + path)
        self.out.write(f.read())
        self.out.write("\n")

    @command(num_tries=5)
    def mkdir(self, path):
        """create a new directory"""
        self.out.write('Making directory %s...' % path)
        self.out.flush()
        try:
            self.api_client.file_create_folder(self.current_path + "/" + path)
            self.out.write('Success!\n')
        except rest.ErrorResponse, e:
            if e.status == 403:
                self.out.write('Already exists.\n' % path)
                return
            else:
                self.out.write('Failed\n\n\n')
                raise

    @command()
    def rm(self, path):
        """delete a file or directory"""
        self.api_client.file_delete(self.current_path + "/" + path)

    @command()
    def mv(self, from_path, to_path):
        """move/rename a file or directory"""
        self.api_client.file_move(self.current_path + "/" + from_path,
                                  self.current_path + "/" + to_path)

    @command()
    def share(self, path):
        """Create a link to share the file at the given path."""
        self.out.write(self.api_client.share(path)['url'] + '\n')

    @command()
    def account_info(self):
        """display account information"""
        f = self.api_client.account_info()
        pprint.Prettyprinter(indent=3).pprint(f, self.out)

    @command()
    def get(self, from_path, to_path):
        """
        Copy file from Dropbox to local file and print out the metadata.

        Examples:
        Dropbox> get file.txt ~/dropbox-file.txt
        """
        encoding = locale.getdefaultlocale()[1] or 'ascii'
        from_path = (self.current_path + "/" + from_path).encode(encoding)
        to_path = os.path.expanduser(to_path)
        self.out.write('Downloading %s...' % from_path)
        self.out.flush()
        chunk_size = 4194304
        try:
            f, metadata = self.api_client.get_file_and_metadata(from_path)
            with open(to_path, "wb") as to_file:
                if metadata['bytes'] < chunk_size:
                    to_file.write(f.read())
                else:
                    while True:
                        buf = f.read(chunk_size)
                        if not buf:
                            break
                        to_file.write(buf)
                        self.out.write('.')
            if metadata['bytes'] != os.path.getsize(to_path):
                raise BufferError('Byte counts on local drive do not match Dropbox.')
            self.out.write('Success!\n')
        except rest.ErrorResponse, e:
            self.out.write('Failed.\n\n\n')
            raise

    @command(num_tries=5)
    def put(self, from_path, to_path, overwrite=False, parent_rev=None):
        """
        Copy local file to Dropbox

        Examples:
        Dropbox> put ~/test.txt dropbox-copy-test.txt
        """
        encoding = locale.getdefaultlocale()[1] or 'ascii'
        full_path = (self.current_path + "/" + to_path).decode(encoding)
        self.out.write('Uploading %s...' % from_path)
        self.out.flush()
        try:
            with open(os.path.expanduser(from_path), "rb") as from_file:
                response = self.api_client.put_file(
                    full_path,
                    from_file,
                    overwrite=overwrite,
                    parent_rev=parent_rev)
            self.out.write('Success!\n')
            return response
        except rest.ErrorResponse, e:
            self.out.write('Failed.\n\n\n')
            raise

    @command()
    def sync_local_folder_to_dropbox(self):
        """Sync local directory to Dropbox.

        Additively (no deletion) syncs current local directory to current dropbox directory.

        Syntax:
            DropboxUploader.sync_local_folder_to_dropbox()
        """
        start_time = time.time()
        for root, dirs, files in os.walk('.'):
            root = self.remove_dotslash(root)
            root_metadata = self.api_client.metadata(
                (self.current_path + '/' + root).encode(encoding))
            remote_dirs_metadata_given_name = {metadata['path'].lower(): metadata
                for metadata in root_metadata['contents'] if metadata['is_dir']}
            remote_files_metadata_given_name = {metadata['path'].lower(): metadata
                for metadata in root_metadata['contents'] if not metadata['is_dir']}

            for dname in dirs:
                dname = self.remove_dotslash(dname)
                drelpath = os.path.join(root, dname)
                dpath = os.path.join(self.current_path, drelpath)
                if dpath.lower() in remote_dirs_metadata_given_name:
                    self.out.write('%s already exists.\n' % drelpath)
                else:
                    self.mkdir(drelpath)

            for fname in files:
                fname = self.remove_dotslash(fname)
                frelpath = os.path.join(root, fname)
                fpath = os.path.join(self.current_path, frelpath)
                if fpath.lower() in remote_files_metadata_given_name:
                    metadata = remote_files_metadata_given_name[fpath.lower()]
                    remote_mtime = self.POSIX_mtime_given_metadata(metadata)
                    if remote_mtime > os.path.getmtime(frelpath):
                        if fd_metadata['bytes'] == os.path.getsize(frelpath):
                            self.out.write('%s newer on Dropbox. Skipping.\n'
                                % (frelpath))
                            continue
                        elif fd_metadata['bytes'] > os.path.getsize(frelpath):
                            self.out.write('%s newer and larger on Dropbox. Skipping.\n'
                                % (frelpath))
                            continue
                        else:
                            self.out.write(
                                '%s newer on Dropbox, but incomplete. Reuploading.\n'
                                % (frelpath))
                    self.put(frelpath, frelpath, parent_rev=metadata['rev'])
                else:
                    self.put(frelpath, frelpath)
        self.out.write('Time to sync %s: %.2f seconds\n'
            % (self.current_path, time.time() - start_time))

    @command()
    def sync_dropbox_folder_to_local(self):
        """Sync Dropbox directory to local.

        Additively (no deletion) syncs current dropbox directory to current local directory.

        Syntax:
            DropboxUploader.sync_local_folder_to_dropbox()
        """
        start_time = time.time()
        root_metadata = self.api_client.metadata(self.current_path)
        for fd_metadata in root_metadata['contents']:
            if fd_metadata['is_dir']:
                dpath = fd_metadata['path']
                dname = os.path.basename(dpath)
                if os.path.isdir(dname):
                    self.out.write('%s already exists\n' % (os.path.abspath(dname)))
                elif os.path.isfile(dname):
                    os.unlink(dname)
                    os.mkdir(dname)
                else:
                    os.mkdir(dname)
                with cd(dname), DropboxUploader_cd(self, dname):
                    self.sync_dropbox_folder_to_local()

            else:
                fpath = fd_metadata['path']
                fname = os.path.basename(fpath)
                if os.path.isdir(fname):
                    shutil.rmtree(fname)
                elif os.path.isfile(fname):
                    remote_mtime = self.POSIX_mtime_given_metadata(fd_metadata)
                    if remote_mtime < os.path.getmtime(fname):
                        if fd_metadata['bytes'] == os.path.getsize(fname):
                            self.out.write('%s newer on local drive. Skipping.\n'
                                % (os.path.abspath(fname)))
                            continue
                        elif fd_metadata['bytes'] < os.path.getsize(fname):
                            self.out.write('%s newer and larger on local drive. Skipping.\n'
                                % (os.path.abspath(fname)))
                            continue
                        else:
                            self.out.write(
                                '%s newer on local drive, but incomplete. Redownloading.\n'
                                % (os.path.abspath(fname)))
                self.get(fname, fname)
        self.out.write('Time to sync %s: %.2f seconds\n'
            % (self.current_path, time.time() - start_time))

    @command()
    def put_chunk(self, from_path, to_path, length, offset=0, upload_id=None):
        """Put one chunk of a file to Dropbox.

        Examples:
        Dropbox> put_chunk ~/test-1kb.txt dropbox-copy-test.txt 1000
        Dropbox> put_chunk ~/test-1kb.txt dropbox-copy-test.txt 24 1000 <upload_id>
        Dropbox> commit_chunks auto/dropbox-copy-test.txt <upload-id>
        """
        length = int(length)
        offset = int(offset)
        with open(from_path) as to_upload:
            to_upload.seek(offset)
            new_offset, upload_id = self.api_client.upload_chunk(StringIO(to_upload.read(length)),
                                                                 offset, upload_id)
            self.out.write('For upload id: %r, uploaded bytes [%d-%d]\n'
                % (upload_id, offset, new_offset))

    @command()
    def commit_chunks(self, to_path, upload_id):
        """Commit the previously uploaded chunks for the given file.

        Examples:
        Dropbox> commit_chunks auto/dropbox-copy-test.txt <upload-id>
        """
        metadata = self.api_client.commit_chunked_upload(to_path, upload_id)
        self.out.write('Metadata:\n')
        pprint.pprint(metadata, self.out)

    @command()
    def search(self, string):
        """Search Dropbox for filenames containing the given string."""
        results = self.api_client.search(self.current_path, string)
        for r in results:
            self.out.write("%s\n" % r['path'])

    @command(login_required=False)
    def help(self):
        # Find every attribute with a non-empty docstring and print out the
        # docstring.
        all_names = dir(self)
        cmd_names = []
        for name in all_names:
            if not name.startswith('_'):
                cmd_names.append(name)
        cmd_names.sort()
        for cmd_name in cmd_names:
            f = getattr(self, cmd_name)
            if f.__doc__:
                self.out.write('%s: %s\n' % (cmd_name, f.__doc__))

    def POSIX_mtime_given_metadata(self, metadata):
        # Converting to POSIX time is a bitch. Hence this wrapper function.
        return time.mktime(parse(metadata['modified']).astimezone(tzlocal()).timetuple())

    def remove_dotslash(self, s):
        if s.startswith('./'):
            s = s[2:]
        elif s == '.':
            s = ''
        return s

    def start_log(self, fpath):
        self.out = Tee(os.path.expanduser(fpath), 'a')
        self.logging = True
        self.out.write(time.strftime('Starting log at %a, %d %b %Y %H:%M:%S UTC\n\n', time.gmtime()))

    def end_log(self):
        if self.logging:
            self.out.write(time.strftime('\nEnding log at %a, %d %b %Y %H:%M:%S UTC\n\n', time.gmtime()))
            self.out = sys.stdout
            self.logging = False


class cd:
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        self.newPath = newPath

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class DropboxUploader_cd:
    """Context manager for changing the current working directory"""
    def __init__(self, d, newPath):
        self.d = d
        if newPath.startswith('/'):
            self.newPath = newPath
        else:
            self.newPath = self.d.current_path + '/' + newPath

    def __enter__(self):
        self.savedPath = self.d.current_path
        self.d.current_path = self.newPath

    def __exit__(self, etype, value, traceback):
        self.d.current_path = self.savedPath


class Tee:
    """A convenience class for outputting to stdout and a log file."""
    def __init__(self, name, mode):
        self.file = open(name, mode)
        self.stdout = sys.stdout

    def __del__(self):
        self.file.close()

    def write(self, data):
        if isinstance(data, unicode):
            data = data.encode('utf-8')
        self.file.write(data)
        self.file.flush()
        self.stdout.write(data)
        self.stdout.flush()

    def flush(self):
        self.stdout.flush()
        self.file.flush()
