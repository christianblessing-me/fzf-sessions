"""Run real terminal checks in a clean process; never touch a live Herdr server."""
import fcntl
import ast
import json
import http.client
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / 'fzf-sessions'


class Terminal:
    def __init__(self, command, env, rows=45, columns=120):
        self.master, self.slave = pty.openpty()
        self.original = termios.tcgetattr(self.slave)
        self.resize(rows, columns)
        self.metadata = tempfile.TemporaryDirectory(prefix='fzf-test-terminal-')
        self.mode_file = Path(self.metadata.name) / 'restored-mode'
        # Keep the controlling session alive until its final TTY state is saved.
        # macOS invalidates slave ioctls after the session leader exits.
        setup = '''import fcntl,sys,termios,subprocess
from pathlib import Path
fcntl.ioctl(0,termios.TIOCSCTTY,0)
result=subprocess.run(sys.argv[2:])
Path(sys.argv[1]).write_text(repr(termios.tcgetattr(0)))
sys.exit(result.returncode)
'''
        self.process = subprocess.Popen([sys.executable, '-c', setup, str(self.mode_file), *command], stdin=self.slave,
            stdout=self.slave, stderr=self.slave, env=env, start_new_session=True, close_fds=True)
        self.output = b''

    def resize(self, rows, columns):
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))

    def send(self, data):
        os.write(self.master, data)

    def read(self, duration=0.05):
        if select.select([self.master], [], [], duration)[0]:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return b''
            self.output += chunk
            return chunk
        return b''

    def until(self, token, timeout=6):
        deadline = time.monotonic() + timeout
        while token not in self.output and time.monotonic() < deadline:
            self.read()
            if self.process.poll() is not None:
                self.read()
                break
        if token not in self.output:
            raise AssertionError(f'Expected terminal text {token!r}; tail={self.output[-1000:]!r}')

    def finish(self, timeout=6):
        deadline = time.monotonic() + timeout
        while self.process.poll() is None and time.monotonic() < deadline:
            self.read()
        if self.process.poll() is None:
            raise AssertionError('Terminal process did not exit')
        self.read()
        if self.process.returncode:
            raise AssertionError(f'Exit {self.process.returncode}: {self.output[-1000:]!r}')

    def close(self):
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=3)
        os.close(self.master)
        os.close(self.slave)
        self.metadata.cleanup()


def environment(root):
    env = dict(os.environ, TERM='xterm-256color', NO_COLOR='1', FZF_SESSIONS_NO_AI='1',
               CODEX_HOME=str(root / 'codex'), CLAUDE_CONFIG_DIR=str(root / 'claude'),
               XDG_CACHE_HOME=str(root / 'cache'))
    for name in list(env):
        if name.startswith('HERDR_') or name.startswith('FZF_SESSIONS_HERDR'):
            env.pop(name)
    env.pop('FZF_DEFAULT_OPTS', None)
    env.pop('FZF_DEFAULT_OPTS_FILE', None)
    # Never depend on, or launch, agent CLIs installed on the test machine.
    binaries = root / 'bin'
    binaries.mkdir()
    for name in ('claude', 'codex'):
        binary = binaries / name
        binary.write_text('#!/bin/sh\necho "Unexpected agent launch in terminal test" >&2\nexit 99\n')
        binary.chmod(0o755)
    real_fzf = shutil.which('fzf')
    wrapper = binaries / 'fzf'
    # Add a private test-only state socket to interactive fzf. Filter and version
    # subprocesses must not replace the interactive socket.
    wrapper.write_text(f'''#!{sys.executable}
import os,sys
args=sys.argv[1:]
extra=[] if any(a.startswith(('--filter','--version')) for a in args) else ['--listen='+os.environ['TEST_FZF_SOCKET']]
os.execv({real_fzf!r}, [{real_fzf!r}, *args, *extra])
''')
    wrapper.chmod(0o755)
    env['TEST_FZF_SOCKET'] = str(root / 'fzf.sock')
    env.pop('FZF_API_KEY', None)
    env['PATH'] = str(binaries) + os.pathsep + env.get('PATH', '')
    return env


def wait_for_state(terminal, env, predicate, timeout=6):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        terminal.read(0.03)
        connection = http.client.HTTPConnection('localhost', timeout=0.3)
        try:
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(0.3)
            connection.sock.connect(env['TEST_FZF_SOCKET'])
            connection.request('GET', '/')
            state = json.loads(connection.getresponse().read())
            if predicate(state):
                return state
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        if terminal.process.poll() is not None:
            break
    raise AssertionError(f'fzf did not reach the expected state; last state={state!r}')


def fixture(root, session_id, title, body):
    path = root / 'claude/projects/project' / (session_id + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'type': 'user', 'cwd': str(root), 'timestamp': '2026-11-10T10:00:00Z',
                              'message': {'content': body}}) + '\n' +
                    json.dumps({'type': 'custom-title', 'customTitle': title}) + '\n')


def probe(root, env):
    terminal = Terminal([sys.executable, '-c', 'import os;f=os.open("/dev/tty",os.O_RDWR);os.write(f,b"PTY_READY")'], env)
    try:
        terminal.until(b'PTY_READY', 2)
        terminal.finish()
    except AssertionError as exc:
        if b'Operation not permitted' in terminal.output or b'Permission denied' in terminal.output:
            print('SKIP: sandbox denies access to the controlling terminal (/dev/tty)')
            raise SystemExit(77)
        raise exc
    finally:
        terminal.close()


def modal_case(root, env):
    for escape in (b'\x1b', b'\x1b[27;1u'):
        terminal = Terminal([sys.executable, str(ENTRYPOINT), '--shortcut-modal', 'herdr'], env)
        try:
            terminal.until(b'Keyboard shortcuts')
            terminal.resize(28, 90)
            terminal.send(b'\x1b[B')
            terminal.read(0.1)
            terminal.send(escape)
            terminal.finish()
            restored = ast.literal_eval(terminal.mode_file.read_text())
            original = terminal.original
            # PENDIN is kernel bookkeeping for queued input on BSD systems.
            restored[3] &= ~getattr(termios, 'PENDIN', 0)
            original[3] &= ~getattr(termios, 'PENDIN', 0)
            assert restored == original, 'TTY mode was not restored'
        finally:
            terminal.close()


def picker_case(root, env):
    fixture(root, 'selected-id', 'A' * 55 + ' unique_suffix', 'A historical discussion about historicneedle.')
    terminal = Terminal([sys.executable, str(ENTRYPOINT), '--dry-run', 'unique_suffix'], env)
    try:
        terminal.until(b'SESSION')
        terminal.send(b'\x1b?')
        terminal.until(b'Keyboard shortcuts')
        terminal.output = b''
        # execute-silent changes TTY mode after one second. A quick dismissal
        # misses that regression; keep the real fzf dialog open past the timer.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            terminal.read()
        terminal.output = b''
        terminal.send(b'\x1b')
        terminal.until(b'Directory / title')
        assert terminal.process.poll() is None, 'Escape closed the picker instead of help'
        terminal.send(b'\r')
        terminal.finish()
        assert b'claude --resume selected-id' in terminal.output, 'Full-title query or selection was lost'
    finally:
        terminal.close()
    terminal = Terminal([sys.executable, str(ENTRYPOINT), '--dry-run', 'historicneedle'], env)
    try:
        terminal.until(b'Directory / title')
        terminal.send(b'\x1bs')
        terminal.until(b'Conversation')
        terminal.send(b'\x1bp')
        terminal.until(b'MATCHING PASSAGES')
        terminal.until(b'historicneedle')
        terminal.send(b'\x1b')
        terminal.finish()
    finally:
        terminal.close()


def refresh_case(root, env):
    fixture(root, 'first-id', 'needle first', 'first body')
    fixture(root, 'second-id', 'needle second', 'second body')
    state = root / 'live.json'
    log = root / 'herdr.jsonl'
    fake = root / 'fake-herdr'
    fake.write_text(f'''#!{sys.executable}
import json,os,sys,time
from pathlib import Path
if sys.argv[1:] == ['--version']:
 print('herdr 0.9.5');sys.exit()
with Path(os.environ['TEST_LOG']).open('a') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')
agent=json.loads(Path(os.environ['TEST_STATE']).read_text())
if sys.argv[1:3] == ['api','snapshot']:
 time.sleep(.15)
 result={{'snapshot':{{'agents':[agent], 'panes':[], 'workspaces':[], 'tabs':[]}}}}
elif sys.argv[1:3] == ['agent','list']: result={{'agents':[agent]}}
elif sys.argv[1:3] == ['agent','focus']: sys.exit(0)
else: print('Unexpected mutation',file=sys.stderr);sys.exit(1)
print(json.dumps({{'result':result}}))
''')
    fake.chmod(0o755)
    def set_state(sid, pane):
        state.write_text(json.dumps({'agent': 'claude', 'agent_session': {'agent': 'claude', 'kind': 'id', 'value': sid},
            'workspace_id': 'another-workspace', 'tab_id': 'another-tab', 'pane_id': pane, 'agent_status': 'idle'}))
    set_state('second-id', 'second-pane')
    env.update(HERDR_ENV='1', HERDR_WORKSPACE_ID='source-workspace', HERDR_BIN_PATH=str(fake),
               TEST_LOG=str(log), TEST_STATE=str(state))
    terminal = Terminal([sys.executable, str(ENTRYPOINT), '--herdr'], env)
    try:
        terminal.until(b'SESSION')
        def first_is_open(state, sid):
            matches = state.get('matches') or []
            return (not state.get('reading') and len(matches) == 2
                    and sid in matches[0]['text'] and '●' in matches[0]['text'])
        wait_for_state(terminal, env, lambda state: first_is_open(state, 'second-id'))
        set_state('first-id', 'first-pane')
        terminal.output = b''
        terminal.send(b'need')
        wait_for_state(terminal, env, lambda state: state.get('query') == 'need' and not state.get('reading'))
        terminal.send(b'\x1br')
        wait_for_state(terminal, env, lambda state: state.get('query') == 'need' and first_is_open(state, 'first-id'))
        assert log.read_text().count('snapshot') >= 2, 'Alt-R did not request a second snapshot'
        terminal.send(b'le')
        wait_for_state(terminal, env, lambda state: state.get('query') == 'needle' and first_is_open(state, 'first-id'))
        # Reload may preserve the previously selected session. Navigate to the
        # top before asserting that the newly open session is sorted first.
        terminal.send(b'\x1b[A' * 3)
        wait_for_state(terminal, env, lambda state: 'first-id' in (state.get('current') or {}).get('text', ''))
        terminal.send(b'\r')
        terminal.finish()
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert ['agent', 'focus', 'first-pane'] in calls, calls
        assert not any(call[:2] in (['tab', 'create'], ['workspace', 'create']) for call in calls)
    finally:
        terminal.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='fzf-terminal-test-', dir='/tmp') as temp:
        root = Path(temp)
        env = environment(root)
        probe(root, env)
        {'modal': modal_case, 'picker': picker_case, 'refresh': refresh_case}[sys.argv[1]](root, env)
        print('PASS:', sys.argv[1])
