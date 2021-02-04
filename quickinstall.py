#!/usr/bin/python3
# Copyright: 2013 MoinMoin:BastianBlank
# Copyright: 2013-2018 MoinMoin:RogerHaase
# License: GNU GPL v2 (or any later version), see LICENSE.txt for details.
"""
Create a virtual environment and install moin2 and all requirements in development mode.

Usage for installation:

    <python> quickinstall.py (where <python> is any Python 3.5+ executable)

Requires: Python 3.5+, pip

The first run of quickinstall.py creates these files or symlink in the repo root:

    - unix: m, activate, wikiconfig.py, intermap.txt
    - windows: m.bat, activate.bat, deactivate.bat, wikiconfig.py, intermap.txt

After initial installation, a menu of frequently used commands is provided for
moin2 developers and desktop wiki users.

    - wraps a few commonly used moin commands, do "moin --help" for infrequently used commands
    - adds default file names for selected moin commands (backup, restore, ...)
    - creates log files for functions with large output, extracts success/failure messages
    - displays error messages if user tries to run commands out of sequence

In normal usage, after the initial installation the user will activate the newly created
virtualenv before executing commands.

usage (to display a menu of commands):

    - unix:     ./m
    - windows:  m
"""


import argparse
import logging
import os
import subprocess
import sys
import platform
import glob
import shutil
import fnmatch
import timeit
from collections import Counter
import venv


if sys.hexversion < 0x3050000:
    sys.exit("Error: MoinMoin requires Python 3.5+, current version is %s\n" % (platform.python_version(), ))


WIN_INFO = 'm.bat, activate.bat, and deactivate.bat are created by quickinstall.py'
NIX_INFO = 'the m bash script and the activate symlink are created by quickinstall.py'

# text files created by commands with high volume output
QUICKINSTALL = 'm-quickinstall.txt'
TOX = 'm-tox.txt'
CODING_STD = 'm-coding-std.txt'
DOCS = 'm-docs.txt'
NEWWIKI = 'm-new-wiki.txt'
DELWIKI = 'm-delete-wiki.txt'
BACKUPWIKI = 'm-backup-wiki.txt'
DUMPHTML = 'm-dump-html.txt'
EXTRAS = 'm-extras.txt'
DIST = 'm-create-dist.txt'
INDEX = 'm-rebuild-index.txt'
# default files used for backup and restore
BACKUP_FILENAME = os.path.normpath('wiki/backup.moin')
JUST_IN_CASE_BACKUP = os.path.normpath('wiki/deleted-backup.moin')


if os.name == 'nt':
    M = 'm'  # customize help to local OS
    SEP = ' & '
    WINDOWS_OS = True
    ACTIVATE = 'activate'
else:
    M = './m'
    SEP = ';'
    WINDOWS_OS = False
    ACTIVATE = '. activate'


# commands that create log files
CMD_LOGS = {
    'quickinstall': QUICKINSTALL,
    'tests': TOX,
    # 'coding-std': CODING_STD,  # not logged due to small output
    'docs': DOCS,
    'new-wiki': NEWWIKI,
    'del-wiki': DELWIKI,
    'backup': BACKUPWIKI,
    'dump-html': DUMPHTML,
    'extras': EXTRAS,
    'dist': DIST,
    'index': INDEX,
}


help = """

usage: "{0} <target>" where <target> is:

quickinstall    update virtual environment with required packages
extras          install packages required for docs and moin development
docs            create moin html documentation (requires extras)
interwiki       refresh intermap.txt
log <target>    view detailed log generated by <target>, omit to see list

new-wiki        create empty wiki
sample          create wiki and load sample data
restore *       create wiki and restore wiki/backup.moin *option, specify file
import19 <dir>  import a moin 1.9 wiki/data instance from <dir>

run *           run built-in wiki server *options (--port 8081)
backup *        roll 3 prior backups and create new backup *option, specify file
dump-html *     create a static HTML image of wiki *options, see docs
index           delete and rebuild indexes

css             run lessc to update basic theme CSS files
tests *         run tests, log output (-v -k my_test)
coding-std      correct scripts that taint the repository with trailing spaces..

del-all         same as running the 4 del-* commands below
del-orig        delete all files matching *.orig
del-pyc         delete all files matching *.pyc
del-rej         delete all files matching *.rej
del-wiki        create a backup, then delete all wiki data
""".format(M)


def search_for_phrase(filename):
    """Search a text file for key phrases and print the lines of interest or print a count by phrase."""
    files = {
        # filename: (list of phrases)
        # Note: phrases must be lower-case
        QUICKINSTALL: ('could not find', 'error', 'fail', 'timeout', 'traceback', 'success', 'cache location', 'must be deactivated', 'no such option', ),
        NEWWIKI: ('error', 'fail', 'timeout', 'traceback', 'success', ),
        BACKUPWIKI: ('error', 'fail', 'timeout', 'traceback', 'success', ),
        DUMPHTML: ('fail', 'timeout', 'traceback', 'success', 'cannot', 'denied', ),
        # use of 'error ' below is to avoid matching .../Modules/errors.o....
        EXTRAS: ('error ', 'error:', 'error.', 'error,', 'fail', 'timeout', 'traceback', 'active version', 'successfully installed', 'finished', ),
        # ': e' matches lines similar to: src/moin/converters\_tests\test_moinwiki_in_out.py:294:5: E303 too many blank lines (3)
        TOX: ('seconds =', 'internalerror', 'error:', 'traceback', ': e', ': f', ' passed, '),
        CODING_STD: ('remove trailing blanks', 'dos line endings', 'unix line endings', 'remove empty lines', ),
        DIST: ('creating', 'copying', 'adding', 'hard linking', ),
        DOCS: ('build finished', 'build succeeded', 'traceback', 'failed', 'error', 'usage', 'importerror', 'exception occurred', ),
        INDEX: ('error', 'fail', 'timeout', 'traceback', 'success', ),
    }
    ignore_phrases = {TOX: ('interpreternotfound', )}
    # for these file names, display a count of occurrances rather than each found line
    print_counts = (CODING_STD, DIST, )

    with open(filename, "r") as f:
        lines = f.readlines()
    name = os.path.split(filename)[1]
    phrases = files[name]
    ignore_phrase = ignore_phrases[name] if name in ignore_phrases else ()
    counts = Counter()
    for idx, line in enumerate(lines):
        for phrase in phrases:
            if phrase in line.lower():
                if filename in print_counts:
                    counts[phrase] += 1
                else:
                    skip = False
                    for ignore in ignore_phrase:
                        if ignore in line.lower():
                            skip = True
                            break
                    if not skip:
                        print(idx + 1, line.rstrip())
                    break
    for key in counts:
        print('The phrase "%s" was found %s times.' % (key, counts[key]))


def wiki_exists():
    """Return true if a wiki exists."""
    return bool(glob.glob('wiki/index/_all_revs_*.toc'))

def copy_config_files():
    if not os.path.isfile('wikiconfig.py'):
        shutil.copy('src/moin/config/wikiconfig.py', 'wikiconfig.py')
    if not os.path.isfile('intermap.txt'):
        shutil.copy('src/moin/config/intermap.txt', 'intermap.txt')
    if not os.path.isdir('wiki_local'):
        os.mkdir('wiki_local')


def make_wiki(command, mode='w', msg='\nSuccess: a new wiki has been created.'):
    """Process command to create a new wiki."""
    if wiki_exists() and mode == 'w':
        print('Error: a wiki exists, delete it and try again.')
    else:
        print('Output messages redirected to {0}.'.format(NEWWIKI))
        with open(NEWWIKI, mode) as messages:
            result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
        if result == 0:
            copy_config_files()
            print(msg)
            return True
        else:
            print('Important messages from %s are shown below:' % NEWWIKI)
            search_for_phrase(NEWWIKI)
            print('\nError: attempt to create wiki failed. Do "%s log new-wiki" to see complete log.' % M)
            return False


def put_items(dir='contrib/sample/'):
    """Load sample items into wiki"""
    metas = []
    datas = []
    files = []
    for (dirpath, dirnames, filenames) in os.walk(dir):
        files.extend(filenames)
        break
    for file in files:
        if file.endswith('.meta'):
            metas.append(file)
        if file.endswith('.data'):
            datas.append(file)
    if not len(datas) == len(metas):
        print('Error: the number of .data and .meta files should be equal')
        return False
    commands = []
    command = 'moin item-put --meta {0} --data {1}'
    for meta in metas:
        data = meta.replace('.meta', '.data')
        if data in datas:
            commands.append(command.format(dir + meta, dir + data))
        else:
            print('Error: file "{0} is missing'.format(data))
            return False
    commands = SEP.join(commands)

    with open(NEWWIKI, 'a') as messages:
        result = subprocess.call(commands, shell=True, stderr=messages, stdout=messages)
    if result == 0:
        print('{0} items were added to wiki'.format(len(metas)))
        return True
    else:
        print('Important messages from %s are shown below:' % NEWWIKI)
        search_for_phrase(NEWWIKI)
        print('\nError: attempt to add items to wiki failed. Do "%s log new-wiki" to see complete log.' % M)
        return False


def delete_files(pattern):
    """Recursively delete all files matching pattern."""
    matches = 0
    for root, dirnames, filenames in os.walk(os.path.abspath(os.path.dirname(__file__))):
        for filename in fnmatch.filter(filenames, pattern):
            os.remove(os.path.join(root, filename))
            matches += 1
    print('Deleted %s files matching "%s".' % (matches, pattern))


def get_bootstrap_data_location():
    """Return the virtualenv site-packages/xstatic/pkg/bootstrap/data location."""
    command = 'python -c "from xstatic.pkg.bootstrap import BASE_DIR; print(BASE_DIR)"'
    return subprocess.check_output(command, shell=True).decode()


def get_pygments_data_location():
    """Return the virtualenv site-packages/xstatic/pkg/pygments/data location."""
    command = 'python -c "from xstatic.pkg.pygments import BASE_DIR; print(BASE_DIR)"'
    return subprocess.check_output(command, shell=True).decode()


def get_sitepackages_location():
    """Return the location of the virtualenv site-packages directory."""
    command = 'python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"'
    return subprocess.check_output(command, shell=True).decode().strip()


def create_m():
    """Create an 'm.bat or 'm' bash script that will run quickinstall.py using this Python"""
    if WINDOWS_OS:
        with open('m.bat', 'w') as f:
            f.write(':: {0}\n\n@{1} quickinstall.py %* --help\n'.format(WIN_INFO, sys.executable))
    else:
        with open('m', 'w') as f:
            f.write('#!/bin/sh\n# {0}\n\n{1} quickinstall.py $* --help\n'.format(NIX_INFO, sys.executable))
            os.fchmod(f.fileno(), 0o775)


class Commands:
    """Each cmd_ method processes a choice on the menu."""
    def __init__(self):
        self.tic = timeit.default_timer()

    def run_time(self, command):
        seconds = int(timeit.default_timer() - self.tic)
        (t_min, t_sec) = divmod(seconds, 60)
        (t_hour,t_min) = divmod(t_min, 60)
        print('{} run time (h:mm:ss) {}:{:0>2}:{:0>2}'.format(command, t_hour, t_min, t_sec))

    def cmd_quickinstall(self, *args):
        """create or update a virtual environment with the required packages"""
        if os.path.isdir('.tox'):
            # keep tox test virtualenvs in sync with moin-env-python
            command = '{0} quickinstall.py --FirstCall {1}{2}tox --recreate --notest'.format(sys.executable, ' '.join(args), SEP)
            print('Running quickinstall.py and tox recreate virtualenvs... output messages redirected to {0}'.format(QUICKINSTALL))
        else:
            command = '{0} quickinstall.py --FirstCall'.format(sys.executable, ' '.join(args), )
            print('Running quickinstall.py... output messages redirected to {0}'.format(QUICKINSTALL))
        with open(QUICKINSTALL, 'w') as messages:
            # we run ourself as a subprocess so output can be captured in a log file
            result = subprocess.run(command, shell=True, stderr=messages, stdout=messages)
            # above result will be flagged as error unless all python versions specified in tox.ini are installed:
            # [tox]\n envlist = py{35,36,37,38},pypy3,flake8
        print('\nSearching {0}, important messages are shown below... Do "{1} log quickinstall" to see complete log.\n'.format(QUICKINSTALL, M))
        search_for_phrase(QUICKINSTALL)
        self.run_time('Quickinstall')

    def cmd_docs(self, *args):
        """create local Sphinx html documentation"""
        command = 'sphinx-apidoc -f -o docs/devel/api src/moin {0}cd docs{0} make html'.format(SEP)
        print('Creating HTML docs... output messages written to {0}.'.format(DOCS))
        with open(DOCS, 'w') as messages:
            result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
        print('\nSearching {0}, important messages are shown below...\n'.format(DOCS))
        search_for_phrase(DOCS)
        if result == 0:
            print('HTML docs successfully created in {0}.'.format(os.path.normpath('docs/_build/html')))
        else:
            print('Error: creation of HTML docs failed with return code "{0}". Do "{1} log docs" to see complete log.'.format(result, M))
        self.run_time('Docs')

    def cmd_extras(self, *args):
        """install optional packages: Pillow, sqlalchemy, ldap, requirements.d"""
        sp_dir = get_sitepackages_location()
        packages = ['pillow', 'sqlalchemy', ]
        if not WINDOWS_OS:
            packages.append('python-ldap')
        installer = 'pip install --upgrade '
        reqs = ['requirements.d/development.txt', 'requirements.d/docs.txt', ]
        reqs_installer = 'pip install -r '
        command = SEP.join(list(installer + x for x in packages) + list(reqs_installer + x for x in reqs))
        print('Installing {0}.'.format(', '.join(packages + reqs)))
        print('Output messages written to {0}.'.format(EXTRAS))
        with open(EXTRAS, 'w') as messages:
            subprocess.call(command, shell=True, stderr=messages, stdout=messages)
        print('\nImportant messages from {0} are shown below. Do "{1} log extras" to see complete log.'.format(EXTRAS, M))
        search_for_phrase(EXTRAS)
        self.run_time('Extras')

    def cmd_interwiki(self, *args):
        """refresh contrib/interwiki/intermap.txt"""
        print('Refreshing {0}...'.format(os.path.normpath('contrib/interwiki/intermap.txt')))
        command = '{0} scripts/wget.py http://master19.moinmo.in/InterWikiMap?action=raw intermap.txt'.format(sys.executable)
        subprocess.call(command, shell=True)

    def cmd_log(self, *args):
        """View a log file with the default text editor"""

        def log_help(logs):
            """Print list of available logs to view."""
            print("usage: {0} log <target> where <target> is:\n\n".format(M))
            choices = '{0: <16}- {1}'
            for log in sorted(logs):
                if os.path.isfile(CMD_LOGS[log]):
                    print(choices.format(log, CMD_LOGS[log]))
                else:
                    print(choices.format(log, '* file does not exist'))

        logs = set(CMD_LOGS.keys())
        if args and args[0] in logs and os.path.isfile(CMD_LOGS[args[0]]):
            if WINDOWS_OS:
                command = 'start {0}'.format(CMD_LOGS[args[0]])
            else:
                # .format requires {{ and }} to escape { and }
                command = '${{VISUAL:-${{FCEDIT:-${{EDITOR:-less}}}}}} {0}'.format(CMD_LOGS[args[0]])
            subprocess.call(command, shell=True)
        else:
            log_help(logs)

    def cmd_new_wiki(self, *args):
        """create empty wiki"""
        command = 'moin index-create -s -i'
        print('Creating a new empty wiki...')
        make_wiki(command)  # share code with loading sample data and restoring backups

    def cmd_sample(self, *args):
        """create wiki and load sample data"""
        # load items with non-ASCII names from a serialized backup
        command = 'moin index-create -s -i{0} moin load --file contrib/sample/unicode.moin'.format(SEP)
        print('Creating a new wiki populated with sample data...')
        success = make_wiki(command, msg='\nSuccess: a new wiki has been created... working...')
        # build the index
        if success:
            command = 'moin index-build'
            success = make_wiki(command, mode='a', msg='\nSuccess: the index has been created for the sample wiki... working...')
        # load individual items from contrib/sample, index will be updated
        if success:
            success = put_items()
        self.run_time('Sample')

    def cmd_restore(self, *args):
        """create wiki and load data from wiki/backup.moin or user specified path"""
        command = 'moin index-create -s -i{0} moin load --file %s{0} moin index-build'.format(SEP)
        filename = BACKUP_FILENAME
        if args:
            filename = args[0]
        if os.path.isfile(filename):
            command = command % filename
            print('Creating a new wiki and loading it with data from {0}...'.format(filename))
            make_wiki(command)
        else:
            print('Error: cannot create wiki because {0} does not exist.'.format(filename))
        self.run_time('Restore')

    def cmd_import19(self, *args):
        """import a moin 1.9 wiki directory named dir"""
        if args:
            dirname = args[0]
            if os.path.isdir(dirname):
                command = 'moin import19 -s -i --data_dir {0}'.format(dirname)
                print('Creating a new wiki populated with data from {0}...'.format(dirname))
                make_wiki(command)
            else:
                print('Error: cannot create wiki because {0} does not exist.'.format(dirname))
        else:
            print('Error: a path to the Moin 1.9 wiki/data data directory is required.')
        self.run_time('Import19')

    def cmd_index(self, *args):
        """delete and rebuild index"""
        if wiki_exists():
            command = 'moin index-create -i{0} moin index-build'.format(SEP)
            print('Rebuilding indexes...')
            try:
                with open(INDEX, 'w') as messages:
                    subprocess.call(command, shell=True, stderr=messages, stdout=messages)
                print('\nImportant messages from {0} are shown below. Do "{1} log index" to see complete log.'.format(INDEX, M))
                search_for_phrase(INDEX)
            except KeyboardInterrupt:
                pass  # eliminates traceback on windows
        else:
            print('Error: a wiki must be created before rebuilding the indexes.')
        self.run_time('Rebuild index')

    def cmd_run(self, *args):
        """run built-in wiki server"""
        if wiki_exists():
            if WINDOWS_OS:
                args += ('--threaded', )
            command = 'moin run {0}'.format(' '.join(args))
            try:
                subprocess.call(command, shell=True)
            except KeyboardInterrupt:
                pass  # eliminates traceback on windows
        else:
            print('Error: a wiki must be created before running the built-in server.')

    def cmd_backup(self, *args):
        """roll 3 prior backups and create new wiki/backup.moin or backup to user specified file"""
        if wiki_exists():
            filename = BACKUP_FILENAME
            if args:
                filename = args[0]
                print('Creating a wiki backup to {0}...'.format(filename))
            else:
                print('Creating a wiki backup to {0} after rolling 3 prior backups...'.format(filename))
                b3 = BACKUP_FILENAME.replace('.', '3.')
                b2 = BACKUP_FILENAME.replace('.', '2.')
                b1 = BACKUP_FILENAME.replace('.', '1.')
                if os.path.exists(b3):
                    os.remove(b3)
                for src, dst in ((b2, b3), (b1, b2), (BACKUP_FILENAME, b1)):
                    if os.path.exists(src):
                        os.rename(src, dst)

            command = 'moin save --all-backends --file {0}'.format(filename)
            with open(BACKUPWIKI, 'w') as messages:
                result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
            if result == 0:
                print('Success: wiki was backed up to {0}'.format(filename))
            else:
                print('Important messages from {0} are shown below. Do "{1} log backup" to see complete log.'.format(BACKUPWIKI, M))
                search_for_phrase(BACKUPWIKI)
                print('\nError: attempt to backup wiki failed.')
        else:
            print('Error: cannot backup wiki because it has not been created.')
        self.run_time('Backup')

    def cmd_dump_html(self, *args):
        """create a static html dump of this wiki"""
        if wiki_exists():
            print('Creating static HTML image of wiki...')
            command = 'moin dump-html {0}'.format(' '.join(args))
            with open(DUMPHTML, 'w') as messages:
                result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
            if result == 0:
                print('Success: wiki was dumped to html files')
            else:
                print('\nError: attempt to dump wiki to html files failed.')
            # always show errors because individual items may fail
            print('Important messages from {0} are shown below. Do "{1} log dump-html" to see complete log.'.format(DUMPHTML, M))
            search_for_phrase(DUMPHTML)
        else:
            print('Error: cannot dump wiki because it has not been created.')
        self.run_time('HTML Dump')

    def cmd_css(self, *args):
        """run lessc to update basic theme CSS files"""
        bootstrap_loc = get_bootstrap_data_location().strip() + '/less'
        pygments_loc = get_pygments_data_location().strip() + '/css'
        basic_loc = 'src/moin/themes/basic/static/custom-less'

        print('Running lessc to update Basic theme CSS files...')
        if WINDOWS_OS:
            data_loc = '{0};{1}'.format(bootstrap_loc, pygments_loc)
        else:
            data_loc = '{0}:{1}'.format(bootstrap_loc, pygments_loc)
        include = '--include-path=' + data_loc
        command = 'cd {0}{1}lessc {2} theme.less ../css/theme.css'.format(basic_loc, SEP, include)
        result = subprocess.call(command, shell=True)
        if result == 0:
            print('Success: Basic theme CSS files updated.')
        else:
            print('Error: Basic theme CSS files update failed, see error messages above.')

    def cmd_tests(self, *args):
        """run tests, output goes to m-tox.txt"""
        print('Running tests... output written to {0}.'.format(TOX))
        command = 'tox -- {1} > {0} 2>&1'.format(TOX, ' '.join(args))
        result = subprocess.call(command, shell=True)
        print('Important messages from {0} are shown below. Do "{1} log tests" to see complete log.'.format(TOX, M))
        search_for_phrase(TOX)
        self.run_time('Tests')

    def cmd_coding_std(self, *args):
        """correct scripts that taint the HG repository and clutter subsequent code reviews"""
        print('Checking for trailing blanks, DOS line endings, Unix line endings, empty lines at eof...')
        command = '%s scripts/coding_std.py' % sys.executable
        subprocess.call(command, shell=True)

    # not on menu, rarely used, similar code was in moin 1.9
    def cmd_dist(self, *args):
        """create distribution archive in dist/"""
        print('Deleting wiki data, then creating distribution archive in /dist, output written to {0}.'.format(DIST))
        self.cmd_del_wiki(*args)
        command = '{0} setup.py sdist bdist_wheel'.format(sys.executable)
        with open(DIST, 'w') as messages:
            result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
        print('Summary message from {0} is shown below:'.format(DIST))
        search_for_phrase(DIST)
        if result == 0:
            print('Success: a distribution archive was created in {0}.'.format(os.path.normpath('/dist')))
        else:
            print('Error: create dist failed with return code = {0}. Do "{1} log dist" to see complete log.'.format(result, M))

    def cmd_del_all(self, *args):
        """same as running the 4 del-* commands below"""
        self.cmd_del_orig(*args)
        self.cmd_del_pyc(*args)
        self.cmd_del_rej(*args)
        self.cmd_del_wiki(*args)

    def cmd_del_orig(self, *args):
        """delete all files matching *.orig"""
        delete_files('*.orig')

    def cmd_del_pyc(self, *args):
        """delete all files matching *.pyc"""
        delete_files('*.pyc')

    def cmd_del_rej(self, *args):
        """delete all files matching *.rej"""
        delete_files('*.rej')

    def cmd_del_wiki(self, *args):
        """create a just-in-case backup, then delete all wiki data"""
        command = 'moin save --all-backends --file {0}'.format(JUST_IN_CASE_BACKUP)
        if wiki_exists():
            print('Creating a backup named {0}; then deleting all wiki data and indexes...'.format(JUST_IN_CASE_BACKUP))
            with open(DELWIKI, 'w') as messages:
                result = subprocess.call(command, shell=True, stderr=messages, stdout=messages)
            if result != 0:
                print('Error: backup failed with return code = {0}. Complete log is in {1}.'.format(result, DELWIKI))
        # destroy wiki even if backup fails
        if os.path.isdir('wiki/data') or os.path.isdir('wiki/index'):
            shutil.rmtree('wiki/data')
            shutil.rmtree('wiki/index')
            if os.path.isdir('wiki/preview'):
                shutil.rmtree('wiki/preview')
            if os.path.isdir('wiki/sql'):
                shutil.rmtree('wiki/sql')
            print('Wiki data successfully deleted.')
        else:
            print('Wiki data not deleted because it does not exist.')
        self.run_time('Delete wiki')


class QuickInstall:

    def __init__(self, source):
        self.dir_source = source
        base, source_name = os.path.split(source)
        executable = os.path.basename(sys.executable).split('.exe')[0]
        venv_path = os.path.join(base, '{0}-venv-{1}'.format(source_name, executable))
        venv_path = os.path.abspath(venv_path)
        venv_home, venv_lib, venv_inc, venv_bin = path_locations(venv_path)
        self.dir_venv = venv_home
        self.dir_venv_bin = venv_bin

    def __call__(self):
        self.do_venv()
        self.do_helpers()
        self.do_install()
        self.do_catalog()
        sys.stdout.write("\n\nSuccessfully created or updated venv at {0}".format(self.dir_venv))

    def do_venv(self):
        venv.create(self.dir_venv, system_site_packages=False, clear=False, symlinks=False, with_pip=True, prompt=None)

    def get_pip_version(self):
        """Return pip version as a list: [1, 5, 1]"""
        command = 'pip --version'
        pip_txt = subprocess.check_output(command, shell=True)
        # expecting pip_txt similar to "pip 1.4.1 from /bitbucket/moin-2.0..."
        pip_txt = pip_txt.decode().split()
        if pip_txt[0] == 'pip':
            pip_version = [int(x) for x in pip_txt[1].split('.')]
            return pip_version
        else:
            sys.exit("Error: 'pip --version' produced unexpected results: '{0}".format(' '.join(pip_txt)))

    def do_install(self):
        pip_version = self.get_pip_version()
        args = [
            os.path.join(self.dir_venv_bin, 'pip'),
            'install',
            '--upgrade',
            '--editable',
            self.dir_source,
        ]
        if pip_version >= [9, 0]:
            args += ['--upgrade-strategy=eager', ]
        subprocess.check_call(args)

    def do_catalog(self):
        subprocess.check_call((
            os.path.join(self.dir_venv_bin, 'python'),
            os.path.join(self.dir_source, 'setup.py'),
            'compile_catalog', '--statistics',
            # needed in case user runs quickinstall.py with a cwd other than the repo root
            '--directory', os.path.join(os.path.dirname(__file__), 'src', 'moin', 'translations'),
        ))

    def create_wrapper(self, filename, target):
        """Create files in the repo root that wrap files in <path-to-virtual-env>\Scripts."""
        target = os.path.join(self.dir_venv_bin, target)
        with open(filename, 'w') as f:
            f.write(':: {0}\n\n@call {1} %*\n'.format(WIN_INFO, target))

    def do_helpers(self):
        """Create small helper scripts or symlinks in repo root, avoid keying the long path to virtual env."""
        create_m()
        if WINDOWS_OS:
            # windows commands are: activate | deactivate
            self.create_wrapper('activate.bat', 'activate.bat')
            self.create_wrapper('deactivate.bat', 'deactivate.bat')
        else:
            # linux commands are: source activate | deactivate
            if os.path.exists('activate'):
                os.unlink('activate')
            os.symlink(os.path.join(self.dir_venv_bin, 'activate'), 'activate')  # no need to define deactivate on unix


# code below and path_locations copied from virtualenv.py v16.7.10 because path_locations dropped in v20.0.0 rewrite.
PY_VERSION = "python{}.{}".format(sys.version_info[0], sys.version_info[1])
IS_PYPY = hasattr(sys, "pypy_version_info")
IS_WIN = sys.platform == "win32"
ABI_FLAGS = getattr(sys, "abiflags", "")
join = os.path.join


def mkdir(at_path):
    if not os.path.exists(at_path):
        os.makedirs(at_path)


def path_locations(home_dir, dry_run=False):
    """Return the path locations for the environment (where libraries are,
    where scripts go, etc)"""
    home_dir = os.path.abspath(home_dir)
    lib_dir, inc_dir, bin_dir = None, None, None
    # XXX: We'd use distutils.sysconfig.get_python_inc/lib but its
    # prefix arg is broken: http://bugs.python.org/issue3386
    if IS_WIN:
        # Windows has lots of problems with executables with spaces in
        # the name; this function will remove them (using the ~1
        # format):
        if not dry_run:
            mkdir(home_dir)
        if " " in home_dir:
            import ctypes

            get_short_path_name = ctypes.windll.kernel32.GetShortPathNameW
            size = max(len(home_dir) + 1, 256)
            buf = ctypes.create_unicode_buffer(size)
            try:
                # noinspection PyUnresolvedReferences
                u = unicode
            except NameError:
                u = str
            ret = get_short_path_name(u(home_dir), buf, size)
            if not ret:
                print('Error: the path "{}" has a space in it'.format(home_dir))
                print("We could not determine the short pathname for it.")
                print("Exiting.")
                sys.exit(3)
            home_dir = str(buf.value)
        lib_dir = join(home_dir, "Lib")
        inc_dir = join(home_dir, "Include")
        bin_dir = join(home_dir, "Scripts")
    if IS_PYPY:
        lib_dir = home_dir
        inc_dir = join(home_dir, "include")
        bin_dir = join(home_dir, "bin")
    elif not IS_WIN:
        lib_dir = join(home_dir, "lib", PY_VERSION)
        inc_dir = join(home_dir, "include", PY_VERSION + ABI_FLAGS)
        bin_dir = join(home_dir, "bin")
    return home_dir, lib_dir, inc_dir, bin_dir


if __name__ == '__main__':
    # create a set of valid menu choices
    commands = Commands()
    choices = set()
    names = dir(commands)
    for name in names:
        if name.startswith('cmd_'):
            choices.add(name)
    args = sys.argv[:]

    if len(args) > 2 and args[-1] == '--help':
        # m and m.bat have trailing --help so "./m" comes across as "python quickinstall.py --help"
        # if user did "./m <option>" we have "python quickinstall.py <option> --help" then we can delete the --help and do <option>
        args = args[:-1]

    if (os.path.isfile('activate') or os.path.isfile('activate.bat')) and (len(args) == 2 and args[1] in ('-h', '--help')):
        # user keyed "./m", "./m -h", or "./m --help"
        print(help)

    else:
        if not (os.path.isfile('m') or os.path.isfile('m.bat')):
            # user is running "python quickinstall.py" after fresh clone (or m or m.bat has been deleted)
            create_m()  # create "m" or "m.bat" file so above IF will be false next time around
            command = getattr(commands, 'cmd_quickinstall')
            # run this same script (quickinstall.py) again in a subprocess to create the virtual env
            command()
            # a few success/failure messages will have printed on users terminal, suggest next step
            print('\n> > > Type "%s" to activate venv, then "%s" for menu < < <' % (ACTIVATE, M))

        elif args == ['quickinstall.py', 'quickinstall']:
            # user keyed "./m quickinstall" to update virtualenv
            command = getattr(commands, 'cmd_quickinstall')
            # run this same script (quickinstall.py) again in a subprocess to recreate the virtual env
            command()

        else:
            if args == ['quickinstall.py']:
                # user keyed "python quickinstall.py" instead of "./m quickinstall"
                # run this same script (quickinstall.py) again in a subprocess to create the virtual env
                command = getattr(commands, 'cmd_quickinstall')
                command()

            elif args == ['quickinstall.py', '--FirstCall']:
                # we are in a subprocess call after "python quickinstall.py" or  "./m quickinstall"
                orig_stdout = sys.stdout
                orig_stderr = sys.stderr
                with open(QUICKINSTALL, 'a') as messages:
                    sys.stdout = messages
                    sys.stderr = messages
                    QuickInstall(os.path.dirname(os.path.realpath(args[0])))()
                    copy_config_files()
                    sys.stdout = orig_stdout
                    sys.stderr = orig_stderr

            else:
                # we have some simple command like "./m css" that does not update virtualenv
                choice = 'cmd_%s' % args[1]
                choice = choice.replace('-', '_')
                if choice in choices:
                    choice = getattr(commands, choice)
                    choice(*args[2:])
                else:
                    print(help)
                    print('Error: unknown menu selection "%s"' % args[1])
