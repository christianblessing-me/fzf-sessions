"""Run real terminal checks in a clean process; never touch a live Herdr server."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
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
        setup = 'import fcntl,os,sys,termios;fcntl.ioctl(0,termios.TIOCSCTTY,0);os.execv(sys.argv[1],sys.argv[1:])'
        self.process = subprocess.Popen([sys.executable, '-c', setup, *command], stdin=self.slave,
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
        self.process.wait(timeout=3)
        os.close(self.master)
        os.close(self.slave)


def environment(root):
    env = dict(os.environ, TERM='xterm-256color', NO_COLOR='1', FZF_SESSIONS_NO_AI='1',
               CODEX_HOME=str(root / 'codex'), CLAUDE_CONFIG_DIR=str(root / 'claude'),
               XDG_CACHE_HOME=str(root / 'cache'))
    for name in list(env):
        if name.startswith('HERDR_') or name.startswith('FZF_SESSIONS_HERDR'):
            env.pop(name)
    env.pop('FZF_DEFAULT_OPTS', None)
    env.pop('FZF_DEFAULT_OPTS_FILE', None)
    return env


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
            assert termios.tcgetattr(terminal.slave) == terminal.original, 'TTY mode was not restored'
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
elif sys.argv[1:3] == ['agent','focus']: result={{}}
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
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            terminal.read()
            if log.exists() and 'snapshot' in log.read_text():
                break
        deadline = time.monotonic() + .4
        while time.monotonic() < deadline:
            terminal.read()
        set_state('first-id', 'first-pane')
        terminal.output = b''
        terminal.send(b'needle')
        terminal.send(b'\x1br')
        terminal.until(b'Directory / title')
        # Wait for the new live read, then enter: the first sorted result must be first-id.
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            terminal.read()
            if log.exists() and log.read_text().count('snapshot') >= 2:
                break
        else:
            raise AssertionError('Alt-R did not request a second snapshot')
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            terminal.read()
        terminal.send(b'\r')
        terminal.finish()
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert ['agent', 'focus', 'first-pane'] in calls, calls
        assert not any(call[:2] == ['tab', 'create'] for call in calls)
    finally:
        terminal.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='fzf-terminal-test-') as temp:
        root = Path(temp)
        env = environment(root)
        probe(root, env)
        {'modal': modal_case, 'picker': picker_case, 'refresh': refresh_case}[sys.argv[1]](root, env)
        print('PASS:', sys.argv[1])
