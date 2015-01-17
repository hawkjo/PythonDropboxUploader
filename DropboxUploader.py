#!/usr/bin/env python

import locale
import os
import pprint
import sys

PY3 = sys.version_info[0] == 3

if PY3:
    from io import StringIO
else:
    from StringIO import StringIO

from dropbox import client, rest, session

def command(login_required=True):
    """a decorator for handling authentication and exceptions"""
    def decorate(f):
        def wrapper(self, *args):
            if login_required and self.api_client is None:
                sys.stdout.write("Please 'login' to execute this command\n")
                return

            for i in xrange(5):
                try:
                    return f(self, *args)
                except TypeError, e:
                    sys.stdout.write(str(e) + '\n')
                except rest.ErrorResponse, e:
                    if e.status == 500:
                        sys.stdout.write('\nError: Out of space.\n')
                        raise
                    elif i < 4:
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
            for f in resp['contents']:
                name = os.path.basename(f['path'])
                encoding = locale.getdefaultlocale()[1] or 'ascii'
                sys.stdout.write(('%s\n' % name).encode(encoding))

    @command()
    def cd(self, path=None):
        """change current working directory"""
        if path is None:
            self.current_path = ''
        elif path == "..":
            self.current_path = "/".join(self.current_path.split("/")[0:-1])
        else:
            self.current_path += "/" + path

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

    @command()
    def mkdir(self, path):
        """create a new directory"""
        try:
            self.api_client.file_create_folder(self.current_path + "/" + path)
        except rest.ErrorResponse, e:
            if e.status == 403:
                sys.stdout.write('%s already exists.\n' % path)
                return
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
        to_file = open(os.path.expanduser(to_path), "wb")

        f, metadata = self.api_client.get_file_and_metadata(self.current_path + "/" + from_path)
        print 'Metadata:', metadata
        to_file.write(f.read())

    @command()
    def put(self, from_path, to_path):
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
                response = self.api_client.put_file(full_path, from_file)
            sys.stdout.write('Success!\n')
            return response
        except rest.ErrorResponse, e:
            sys.stdout.write('Failed\n\n\n')
            raise

    @command()
    def additive_sync(self, dname, add_to_dropbox=False, add_to_local=False):
        """
        Sync local directory recursively to Dropbox.

        !!! Warning !!!
        Extremely simple. You must be in local parent directory before starting
        cli_client.py and desired dropbox parent directly before executing
        command.
        !!!!!!!!!!!!!!!

        Examples:
        Dropbox> put_recursive test_dir
        """
        if not add_to_dropbox and not add_to_local:
            sys.stdout.write('Additive sync not adding files anywhere.\n')
            return

        if not os.path.isdir(dname):
            sys.stdout.write(dname + ' is not a directory.\n')
            return

        cwd = os.getcwd()
        self.mkdir(dname)
        for root, dirs, files in os.walk(dname):
            for dname in dirs:
                dpath = os.path.join(root, dname)
                sys.stdout.write('Making directory %s...' % dpath)
                try:
                    self.mkdir(dpath)
                    sys.stdout.write('Success!\n')
                except:
                    sys.stdout.write('Failed\n\n\n')
                    raise
            for fname in files:
                fpath = os.path.join(root, fname)
                self.put(fpath, fpath)

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

