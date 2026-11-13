"""Help ui for fzf-sessions."""
from __future__ import annotations
import os
import re
import textwrap
from . import herdr as herdr_mod


def shortcut_help(herdr: bool) -> str:
    color = "NO_COLOR" not in os.environ

    def heading(text: str) -> str:
        return f"\x1b[1;36m{text}\x1b[0m" if color else text

    def key(name: str, description: str) -> str:
        label = f"{name:<18}"
        if color:
            label = f"\x1b[1m{label}\x1b[0m"
        return f"  {label}{description}"

    lines = [heading("NAVIGATE"), key("↑ / ↓", "Move between sessions"),
             key("Ctrl-J / Ctrl-K", "Move down / up"),
             key("Enter", "Jump to an open pane or resume in a new tab" if herdr else "Resume in this terminal"),
             key("Esc / Ctrl-C", "Close the picker"), "", heading("SEARCH & PREVIEW"),
             key("Type", "Search the current mode"), key("Alt-S", "Switch directory/title ↔ conversation content"),
             key("Alt-P", "Show or hide the preview"), key("Shift-↑ / Shift-↓", "Scroll the preview"), "",
             heading("ACTIONS"), key("Alt-C", "Copy the resume command and close (macOS)")]
    if herdr:
        lines.append(key("Alt-R", "Refresh open-session markers and ordering"))
    lines += [key("Alt-?", "Show this help"), "", heading("SEARCH MODES"),
              "  Directory / title   Fuzzy search of folder names and session titles.",
              "  Conversation        All query words must occur in saved messages.",
              "                      Alt-P shows highlighted matching passages."]
    if herdr:
        lines += ["", heading("HERDR STATUS"),
                  "  ● Open in Herdr   — No exact live match   ? Checking / unavailable",
                  "  Open sessions appear first. Full locations are in the preview."]
    return "\n".join(lines)


def help_modal_frame(herdr: bool, columns: int, rows: int, offset: int = 0) -> tuple[str, int, int]:
    # Paint only the dialog rectangle; the running fzf view remains behind it.
    if columns < 12 or rows < 6:
        return "\x1b[1;1H" + "Resize terminal"[:max(0, columns)], 0, 0
    width = max(4, min(88, columns - 8 if columns > 16 else columns))
    inner = max(1, width - 4)
    text = re.sub(r"\x1b\[[0-9;]*m", "", shortcut_help(herdr))
    content = []
    for line in text.splitlines():
        content.extend(textwrap.wrap(line, width=inner, subsequent_indent="  " if inner > 4 else "",
                                     break_on_hyphens=False) or [""])
    visible = max(1, min(len(content), 30, rows - 8))
    offset = max(0, min(offset, len(content) - visible))
    height = visible + 4
    top, left = max(1, (rows - height) // 2 + 1), max(1, (columns - width) // 2 + 1)
    color = "NO_COLOR" not in os.environ

    def paint(value: str, code: str) -> str:
        return f"\x1b[{code}m{value}\x1b[0m" if color else value

    title = " Keyboard shortcuts "[:width - 2]
    frame = [paint("╭" + title + "─" * (width - 2 - len(title)) + "╮", "1;36")]
    for line in content[offset:offset + visible]:
        value = line.ljust(inner)
        if line and line.strip().isupper():
            value = paint(value, "1;36")
        frame.append(paint("│", "36") + " " + value + " " + paint("│", "36"))
    frame.append(paint("├" + "─" * (width - 2) + "┤", "36"))
    footer = "Esc / Enter / Alt-? close"
    if len(content) > visible:
        footer = f"↑↓ scroll · {footer} · {offset + 1}–{offset + visible}/{len(content)}"
    frame.append(paint("│", "36") + " " + paint(footer[:inner].ljust(inner), "2") + " " + paint("│", "36"))
    frame.append(paint("╰" + "─" * (width - 2) + "╯", "36"))
    output = "".join(f"\x1b[{top + i};{left}H\x1b[0m{line}" for i, line in enumerate(frame))
    return output, offset, len(content) - visible


def read_modal_key(fd: int) -> bytes:
    """Read a single key event, leaving subsequent press/release events queued."""
    import select
    key = os.read(fd, 1)
    if key != b"\x1b" or not select.select([fd], [], [], 0.05)[0]:
        return key
    key += os.read(fd, 1)
    if key[-1:] not in (b"[", b"O"):
        return key
    while len(key) < 64 and select.select([fd], [], [], 0.05)[0]:
        char = os.read(fd, 1)
        if not char:
            break
        key += char
        if 0x40 <= char[0] <= 0x7e:
            break
    return key


def modal_key_action(key: bytes) -> str:
    if key in (b"", b"\r", b"\n", b"\x03", b"\x1b", b"\x1b?", b"\x1b\x1b"):
        return "close"
    # fzf can leave enhanced keyboard reporting enabled. Escape then arrives
    # as CSI 27 u rather than a bare ESC; key releases must not act as presses.
    kitty = re.fullmatch(rb"\x1b\[(\d+)(?::(\d*))?(?::\d*)?(?:;(\d+)(?::([123]))?)?(?:;[\d:]+)?u", key)
    legacy = re.fullmatch(rb"\x1b\[27;(\d+);(\d+)~", key)
    if kitty or legacy:
        if kitty:
            if kitty[4] == b"3":
                return ""
            code, shifted = int(kitty[1]), int(kitty[2] or b"0")
            modifiers = int(kitty[3] or b"1") - 1
        else:
            code, shifted, modifiers = int(legacy[2]), 0, int(legacy[1]) - 1
        if code in (27, 13) or (modifiers & 4 and code == 99):
            return "close"
        if modifiers & 2 and (code == 63 or (code == 47 and (shifted == 63 or modifiers & 1))):
            return "close"
        if code == 106 or (modifiers & 4 and code == 110):
            return "down"
        if code == 107 or (modifiers & 4 and code == 112):
            return "up"
    if key in (b"j", b"\x0e", b"\x1bOB") or re.fullmatch(rb"\x1b\[(?:1(?:;\d+(?::[12])?)?)?B", key):
        return "down"
    if key in (b"k", b"\x10", b"\x1bOA") or re.fullmatch(rb"\x1b\[(?:1(?:;\d+(?::[12])?)?)?A", key):
        return "up"
    if re.fullmatch(rb"\x1b\[6(?:;\d+(?::[12])?)?~", key):
        return "page-down"
    if re.fullmatch(rb"\x1b\[5(?:;\d+(?::[12])?)?~", key):
        return "page-up"
    return ""


def show_shortcut_modal(herdr: bool) -> None:
    # execute-silent pauses fzf without leaving its screen. Access the same TTY
    # directly, since fzf intentionally disconnects the command's stdin/stdout.
    import select
    import termios
    import tty

    with open("/dev/tty", "r+b", buffering=0) as terminal:
        fd = terminal.fileno()
        previous = termios.tcgetattr(fd)
        offset, maximum = 0, 0
        last_size = None
        redraw = True
        try:
            tty.setraw(fd)
            raw_mode = termios.tcgetattr(fd)
            terminal.write(b"\x1b7\x1b[?25l")
            while True:
                # fzf's execute-silent restores its original terminal mode after
                # one second. Keep this dialog in raw mode so a lone Escape is
                # delivered without Enter. TCSANOW preserves already queued keys.
                if termios.tcgetattr(fd) != raw_mode:
                    termios.tcsetattr(fd, termios.TCSANOW, raw_mode)
                size = os.get_terminal_size(fd)
                if redraw or size != last_size:
                    frame, offset, maximum = help_modal_frame(herdr, size.columns, size.lines, offset)
                    terminal.write(frame.encode())
                    last_size, redraw = size, False
                if not select.select([fd], [], [], 0.1)[0]:
                    continue
                action = modal_key_action(read_modal_key(fd))
                if action == "close":
                    return
                if action == "down":
                    offset += 1
                elif action == "up":
                    offset -= 1
                elif action == "page-down":
                    offset += 10
                elif action == "page-up":
                    offset -= 10
                offset = max(0, min(offset, maximum))
                redraw = True
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, previous)
            terminal.write(b"\x1b[0m\x1b8\x1b[?25h")
