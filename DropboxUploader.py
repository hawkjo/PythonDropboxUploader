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
                sys.stdout.write("Please 'login' to execute this command\n")
                return

            for i in xrange(num_tries):
                try:
                    return f(self, *args, **kwargs)
                except TypeError, e:
                    sys.stdout.write(str(e) + '\n')
                except rest.ErrorResponse, e:
                    if e.status == 500:
                        sys.stdout.write('\nError: Out of space.\n')
                        raise
                    elif i < num_tries-1:
                        pass
                    else:
                        msg = e.user_error_msg or str(e)
                        sys.stdout.write('Error: %s\n' % msg)

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
        self.prompt = "Dropbox> "

        self.api_client = None
        try:
            serialized_token = open(self.TOKEN_FILE).read()
            if serialized_token.startswith('oauth1:'):
                access_key, access_secret = serialized_token[len('oauth1:'):].split(':', 1)
                sess = session.DropboxSession(self.APP_KEY, self.APP_SECRET)
                sess.set_token(access_key, access_secret)
                self.api_client = client.DropboxClient(sess)
                print "[loaded OAuth 1 access token]"
            elif serialized_token.startswith('oauth2:'):
                access_token = serialized_token[len('oauth2:'):]
                self.api_client = client.DropboxClient(access_token)
                print "[loaded OAuth 2 access token]"
            else:
                print "Malformed access token in %r." % (self.TOKEN_FILE,)
        except IOError:
            pass # don't worry if it's not there

        try:
            self.app_key = open(self.APP_KEY_FILE).read()
            self.app_secret = open(self.APP_SECRET_FILE).read()
        except:
            print """Error reading app info. Please store your app key and secret in the files:
            <base dir>/app_key.txt
            <base dir>/app_secret.txt
            """
            raise

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
        print self.current_path

    @command(login_required=False)
    def login(self):
        """log in to a Dropbox account"""
        flow = client.DropboxOAuth2FlowNoRedirect(self.APP_KEY, self.APP_SECRET)
        authorize_url = flow.start()
        sys.stdout.write("1. Go to: " + authorize_url + "\n")
        sys.stdout.write("2. Click \"Allow\" (you might have to log in first).\n")
        sys.stdout.write("3. Copy the authorization code.\n")
        code = raw_input("Enter the authorization code here: ").strip()

        try:
            access_token, user_id = flow.finish(code)
        except rest.ErrorResponse, e:
            sys.stdout.write('Error: %s\n' % str(e))
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
        sys.stdout.write("1. Go to: " + authorize_url + "\n")
        sys.stdout.write("2. Click \"Allow\" (you might have to log in first).\n")
        sys.stdout.write("3. Press ENTER.\n")
        raw_input()

        try:
            access_token = sess.obtain_access_token()
        except rest.ErrorResponse, e:
            sys.stdout.write('Error: %s\n' % str(e))
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
        sys.stdout.write(f.read())
        sys.stdout.write("\n")

    @command(num_tries=5)
    def mkdir(self, path):
        """create a new directory"""
        sys.stdout.write('Making directory %s...' % path)
        sys.stdout.flush()
        try:
            self.api_client.file_create_folder(self.current_path + "/" + path)
            sys.stdout.write('Success!\n')
        except rest.ErrorResponse, e:
            if e.status == 403:
                sys.stdout.write('Already exists.\n' % path)
                return
            else:
                sys.stdout.write('Failed\n\n\n')
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
        print self.api_client.share(path)['url']

    @command()
    def account_info(self):
        """display account information"""
        f = self.api_client.account_info()
        pprint.PrettyPrinter(indent=3).pprint(f)

    @command()
    def get(self, from_path, to_path):
        """
        Copy file from Dropbox to local file and print out the metadata.

        Examples:
        Dropbox> get file.txt ~/dropbox-file.txt
        """
        from_path = self.current_path + "/" + from_path
        sys.stdout.write('Downloading %s...' % from_path)
        sys.stdout.flush()
        try:
            to_file = open(os.path.expanduser(to_path), "wb")
            f, metadata = self.api_client.get_file_and_metadata(from_path)
            to_file.write(f.read())
            print 'Success!'
        except rest.ErrorResponse, e:
            print 'Failed.\n\n'
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
        sys.stdout.write('Uploading %s...' % from_path)
        sys.stdout.flush()
        try:
            with open(os.path.expanduser(from_path), "rb") as from_file:
                response = self.api_client.put_file(
                    full_path,
                    from_file,
                    overwrite=overwrite,
                    parent_rev=parent_rev)
            print 'Success!'
            return response
        except rest.ErrorResponse, e:
            print 'Failed.\n\n'
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
            root_metadata = self.api_client.metadata(self.current_path + '/' + root)
            remote_dirs_metadata_given_name = {metadata['path'].lower(): metadata
                for metadata in root_metadata['contents'] if metadata['is_dir']}
            remote_files_metadata_given_name = {metadata['path'].lower(): metadata
                for metadata in root_metadata['contents'] if not metadata['is_dir']}

            for dname in dirs:
                dname = self.remove_dotslash(dname)
                drelpath = os.path.join(root, dname)
                dpath = os.path.join(self.current_path, drelpath)
                if dpath.lower() in remote_dirs_metadata_given_name:
                    print '%s already exists.' % drelpath
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
                        print '%s in dropbox newer. Skipping.' % frelpath
                        continue
                    self.put(frelpath, frelpath, parent_rev=metadata['rev'])
                else:
                    self.put(frelpath, frelpath)
        print 'Time to sync %s: %.2f seconds' % (self.current_path, start_time - time.time())

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
                    print '%s already exists' % (os.path.abspath(dname))
                    continue
                elif os.path.isfile(dname):
                    os.unlink(dname)

                os.mkdir(dname)
                with cd(dname):
                    self.cd(dname)
                    self.sync_dropbox_folder_to_local()
                    self.cd('..')

            else:
                fpath = fd_metadata['path']
                fname = os.path.basename(fpath)
                if os.path.isdir(fname):
                    shutil.rmtree(fname)
                elif os.path.isfile(fname):
                    remote_mtime = self.POSIX_mtime_given_metadata(fd_metadata)
                    if remote_mtime < os.path.getmtime(fname):
                        print '%s newer on local drive. Skipping.' % (os.path.abspath(fname))
                        continue
                self.get(fname, fname)
        print 'Time to sync %s: %.2f seconds' % (self.current_path, start_time - time.time())

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
            print 'For upload id: %r, uploaded bytes [%d-%d]' % (upload_id, offset, new_offset)

    @command()
    def commit_chunks(self, to_path, upload_id):
        """Commit the previously uploaded chunks for the given file.

        Examples:
        Dropbox> commit_chunks auto/dropbox-copy-test.txt <upload-id>
        """
        metadata = self.api_client.commit_chunked_upload(to_path, upload_id)
        print 'Metadata:', metadata

    @command()
    def search(self, string):
        """Search Dropbox for filenames containing the given string."""
        results = self.api_client.search(self.current_path, string)
        for r in results:
            sys.stdout.write("%s\n" % r['path'])

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
                sys.stdout.write('%s: %s\n' % (cmd_name, f.__doc__))

    def POSIX_mtime_given_metadata(self, metadata):
        # Converting to POSIX time is a bitch. Hence this wrapper function.
        return time.mktime(parse(metadata['modified']).astimezone(tzlocal()).timetuple())

    def remove_dotslash(self, s):
        if s.startswith('./'):
            s = s[2:]
        elif s == '.':
            s = ''
        return s


class cd:
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        self.newPath = newPath

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)
