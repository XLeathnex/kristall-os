# SPDX-License-Identifier: GPL-3.0-or-later
"""Static analysis of shell commands the model wants to run.

The goal is not to prove a command safe — that is impossible — but to put each
command into the right *kind* of action so the policy can decide whether the
owner must be asked.  Anything we cannot understand is treated as "unknown",
which always asks.  The analysis is conservative: every simple command in a
pipeline/list is classified and the most serious one wins.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

# Severity order; higher wins when combining.  Must match policy.CATEGORY_ORDER.
ORDER = [
    "read", "reversible", "files.modify", "system.config", "processes.stop",
    "system.power", "apps.install", "files.delete", "shell.run", "send",
    "purchase", "elevated", "credentials", "deny",
]
RANK = {c: i for i, c in enumerate(ORDER)}


def worst(a: str, b: str) -> str:
    return a if RANK[a] >= RANK[b] else b


@dataclass
class Finding:
    category: str
    program: str = ""
    targets: list[str] = field(default_factory=list)   # paths the command acts on
    note: str = ""


@dataclass
class ShellAnalysis:
    category: str
    findings: list[Finding]
    programs: list[str]

    @property
    def main(self) -> Finding:
        best = self.findings[0]
        for f in self.findings:
            if RANK[f.category] > RANK[best.category]:
                best = f
        return best


READ_ONLY = {
    "ls", "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "wc", "du", "df",
    "free", "uname", "date", "cal", "uptime", "whoami", "id", "hostname", "hostnamectl", "pwd",
    "echo", "printf", "which", "type", "file", "stat", "realpath", "readlink", "basename",
    "dirname", "sort", "uniq", "cut", "tr", "jq", "column", "ps", "pgrep", "lsblk", "lscpu",
    "lsusb", "lspci", "lsmod", "sensors", "env", "printenv", "locale", "true", "false", "test",
    "[", "seq", "nproc", "tree", "fc-list", "xdg-user-dir", "xdg-mime", "md5sum", "sha256sum",
    "sha1sum", "cmp", "diff", "comm", "nl", "fold", "fmt", "expr", "bc", "sleep", "journalctl",
    "loginctl", "inxi", "upower", "acpi", "iwgetid", "ping", "host", "dig", "nslookup",
    "exiftool", "pdfinfo", "pdftotext", "identify", "ffprobe", "mediainfo", "zcat", "zgrep",
    "unzip", "tar", "7z", "fastfetch", "neofetch", "getent", "timedatectl", "localectl",
    "kreadconfig6", "kreadconfig5", "awk", "sed", "basenc", "base64", "strings", "xxd", "hexdump",
}
# Programs whose effect is easily undone (open things, adjust volume/brightness,
# show a notification, create something new).
REVERSIBLE = {
    "xdg-open", "gio", "gtk-launch", "kioclient", "kioclient5", "kstart", "kstart6",
    "notify-send", "playerctl", "mkdir", "touch", "kristall-settings",
    "wl-copy", "wl-paste", "spectacle", "pw-play", "paplay", "canberra-gtk-play",
}
UNPACK_OR_CREATE = {"tar", "unzip", "7z", "zip", "gzip", "gunzip", "xz", "convert", "magick", "ffmpeg"}
SEND = {"mail", "mailx", "sendmail", "mutt", "msmtp", "neomutt", "ssh", "scp", "sftp", "ftp", "nc", "ncat", "telnet"}
ELEVATE = {"sudo", "pkexec", "doas", "su", "run0", "sudoedit"}
SYSTEM_TOOLS = {"rpm-ostree", "bootc", "dnf", "dnf5", "rpm", "mkfs", "fdisk", "parted", "wipefs",
                "dd", "mount", "umount", "cryptsetup", "useradd", "userdel", "passwd", "chpasswd",
                "modprobe", "insmod", "rmmod", "sysctl", "firewall-cmd", "nft", "iptables", "grub2-mkconfig"}
POWER = {"shutdown", "reboot", "poweroff", "halt"}
KILL = {"kill", "pkill", "killall", "xkill"}
DELETE = {"rm", "rmdir", "shred", "unlink", "srm", "truncate"}
WRAPPERS = {"nice", "ionice", "nohup", "command", "builtin", "time", "stdbuf", "chrt", "taskset", "exec"}
INTERPRETERS = {"bash", "sh", "zsh", "fish", "dash", "python", "python3", "perl", "ruby", "node",
                "lua", "php", "osascript", "eval", "source", ".", "xargs", "parallel", "watch",
                "flatpak-spawn", "systemd-run", "at", "batch", "busctl", "qdbus", "qdbus6", "gdbus",
                "dbus-send"}
CONTROL_OPS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "\n"}
REDIRECT_OPS = {">", ">>", ">|", "&>", "&>>", "<", "<<", "<<<", "<>", "2>", "2>>"}


def _split_commands(tokens: list[str]) -> list[list[str]]:
    cmds: list[list[str]] = [[]]
    for t in tokens:
        if t in CONTROL_OPS:
            if cmds[-1]:
                cmds.append([])
        else:
            cmds[-1].append(t)
    return [c for c in cmds if c]


def _tokenize(command: str) -> list[str] | None:
    try:
        lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.commenters = "#"
        toks = list(lex)
    except ValueError:
        return None
    # shlex splits "2>" into "2", ">" — rejoin numeric fd redirections.
    out: list[str] = []
    for t in toks:
        if out and t and t[0] in "<>" and out[-1].isdigit():
            out[-1] = out[-1] + t
        else:
            out.append(t)
    return out


def _exists(path: str, cwd: str) -> bool:
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.lexists(p)


def _strip_prefix(argv: list[str]) -> tuple[list[str], bool]:
    """Remove env assignments and harmless wrappers; report elevation."""
    elevated = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if "=" in a and not a.startswith("-") and a.split("=", 1)[0].replace("_", "").isalnum():
            i += 1
            continue
        base = os.path.basename(a)
        if base in ELEVATE:
            elevated = True
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 1
            continue
        if base == "env":
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or "=" in argv[i]):
                i += 1
            continue
        if base == "timeout":
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or argv[i][:1].isdigit()):
                i += 1
            continue
        if base in WRAPPERS:
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 1
            continue
        break
    return argv[i:], elevated


def _operands(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def classify_simple(argv: list[str], cwd: str) -> Finding:
    """Classify one simple command (no control operators)."""
    # Redirections first: writes to files.
    words: list[str] = []
    redirect_cat = "read"
    redirect_targets: list[str] = []
    i = 0
    while i < len(argv):
        t = argv[i]
        if t in REDIRECT_OPS or (t[:-1].isdigit() and t[-1:] in "<>") or t.rstrip(">").endswith("&"):
            target = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            if ">" in t and target and target not in ("/dev/null", "/dev/stdout", "/dev/stderr") \
                    and not target.startswith("&"):
                redirect_targets.append(target)
                redirect_cat = worst(redirect_cat, "files.modify" if _exists(target, cwd) else "reversible")
            continue
        words.append(t)
        i += 1
    if not words:
        return Finding(redirect_cat, "", redirect_targets)

    words, elevated = _strip_prefix(words)
    if not words:
        return Finding("elevated" if elevated else redirect_cat, "sudo" if elevated else "")
    prog = os.path.basename(words[0])
    args = words[1:]
    ops = _operands(args)
    f = _classify_program(prog, args, ops, cwd)
    f.category = worst(f.category, redirect_cat)
    f.targets = f.targets + redirect_targets
    if elevated or prog in SYSTEM_TOOLS:
        f.category = worst(f.category, "elevated")
        if elevated:
            f.note = "elevated"
    if any("$(" in w or "`" in w for w in words):
        f.category = worst(f.category, "shell.run")
        f.note = f.note or "substitution"
    return f


def _classify_program(prog: str, args: list[str], ops: list[str], cwd: str) -> Finding:
    a = set(args)
    if prog in DELETE:
        return Finding("files.delete", prog, ops)
    if prog in KILL:
        return Finding("processes.stop", prog, ops)
    if prog in POWER:
        return Finding("system.power", prog)
    if prog in SEND:
        return Finding("send", prog, ops)
    if prog in SYSTEM_TOOLS:
        return Finding("elevated", prog, ops)
    if prog in INTERPRETERS:
        return Finding("shell.run", prog, ops, "interpreter")
    if prog == "find":
        if a & {"-delete"}:
            return Finding("files.delete", prog, ops)
        if a & {"-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}:
            return Finding("shell.run", prog, ops, "find -exec")
        return Finding("read", prog, ops)
    if prog == "sed":
        if any(x == "-i" or x.startswith("-i") or x == "--in-place" for x in args):
            return Finding("files.modify", prog, ops)
        if any("w " in x or x.endswith("w") and "/" in x for x in ops[:1]):
            return Finding("shell.run", prog, ops)
        return Finding("read", prog, ops)
    if prog == "awk":
        prog_text = " ".join(ops[:1])
        if "system(" in prog_text or ">" in prog_text or "|" in prog_text:
            return Finding("shell.run", prog, ops)
        return Finding("read", prog, ops)
    if prog in ("tar", "unzip", "7z", "zip", "gzip", "gunzip", "xz"):
        if prog == "tar" and not (a & {"-x", "--extract", "-c", "--create", "-r", "-u"}) \
                and not any(x.startswith("-") and ("x" in x or "c" in x) and not x.startswith("--") for x in args):
            return Finding("read", prog, ops)
        if prog == "unzip" and "-l" in a:
            return Finding("read", prog, ops)
        if prog == "7z" and ops[:1] == ["l"]:
            return Finding("read", prog, ops)
        return Finding("reversible", prog, ops, "creates files")
    if prog in ("convert", "magick", "ffmpeg"):
        out = ops[-1:] if ops else []
        if out and _exists(out[0], cwd):
            return Finding("files.modify", prog, out)
        return Finding("reversible", prog, out, "creates files")
    if prog == "ln":
        # A new link is harmless; replacing an existing file with a link (ln -sf) destroys it.
        if len(ops) >= 2:
            if _any_overwrite(ops, cwd):
                return Finding("files.modify", prog, ops[-1:])
        elif ops and _exists(os.path.basename(ops[0].rstrip("/")), cwd):
            return Finding("files.modify", prog, [os.path.basename(ops[0].rstrip("/"))])
        return Finding("reversible", prog, ops, "link")
    if prog in ("cp", "mv", "rsync", "install"):
        if prog == "rsync" and any(":" in o and not o.startswith("/") for o in ops):
            return Finding("send", prog, ops)
        if prog == "rsync" and "--delete" in " ".join(args):
            return Finding("files.delete", prog, ops)
        dest = ops[-1] if len(ops) >= 2 else ""
        if prog == "mv":
            # A move to the trash is reversible; any other move can overwrite.
            if dest and ("Trash" in dest or dest.startswith("trash:")):
                return Finding("reversible", prog, ops[:-1], "trash")
            if dest and _exists(dest, cwd) and not os.path.isdir(os.path.expanduser(dest)):
                return Finding("files.modify", prog, ops)
            return Finding("files.modify" if _any_overwrite(ops, cwd) else "reversible", prog, ops)
        if dest and _exists(dest, cwd) and not os.path.isdir(os.path.expanduser(dest)):
            return Finding("files.modify", prog, [dest])
        return Finding("reversible", prog, ops, "copy")
    if prog in ("chmod", "chown", "chgrp", "chattr", "setfacl"):
        return Finding("files.modify", prog, ops[1:])
    if prog == "gio":
        sub = ops[:1]
        if sub in (["trash"],):
            return Finding("reversible", prog, ops[1:], "trash")
        if sub in (["remove"], ["rm"]):
            return Finding("files.delete", prog, ops[1:])
        if sub in (["copy"], ["move"], ["set"], ["save"]):
            return Finding("files.modify", prog, ops[1:])
        return Finding("reversible", prog, ops[1:])
    if prog in ("trash", "trash-put", "kioclient", "kioclient5"):
        if prog.startswith("kioclient") and ops[:1] in (["remove"], ["rm"]):
            return Finding("files.delete", prog, ops[1:])
        return Finding("reversible", prog, ops, "trash" if prog.startswith("trash") else "")
    if prog in ("curl", "wget"):
        sending = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form",
                   "-T", "--upload-file", "--post-data", "--post-file", "--json"}
        if a & sending or any(x.startswith(("--data", "--form", "--json", "--post")) for x in args):
            return Finding("send", prog, ops)
        for j, x in enumerate(args):
            if x in ("-X", "--request", "--method") and j + 1 < len(args) \
                    and args[j + 1].upper() not in ("GET", "HEAD"):
                return Finding("send", prog, ops)
            if x.startswith(("-X", "--request=", "--method=")) and len(x) > 2 \
                    and x.split("=", 1)[-1].lstrip("-X").upper() not in ("GET", "HEAD", ""):
                return Finding("send", prog, ops)
        out = os.path.expandvars(_download_target(prog, args))
        if out and out not in ("-", "/dev/null") and _exists(out, cwd):
            return Finding("files.modify", prog, [out])
        if prog == "wget" or a & {"-o", "-O", "--output", "--remote-name"}:
            return Finding("reversible", prog, ops, "download")
        return Finding("read", prog, ops)
    if prog == "git":
        rest, skip = [], False
        for x in args:               # drop global options such as -C <dir>, -c k=v
            if skip:
                skip = False
                continue
            if x in ("-C", "-c", "--git-dir", "--work-tree"):
                skip = True
                continue
            if not x.startswith("-"):
                rest.append(x)
        sub = rest[:1]
        if sub and sub[0] in ("status", "log", "diff", "show", "branch", "remote", "ls-files", "blame", "rev-parse", "describe", "tag"):
            return Finding("read", prog, ops)
        if sub and sub[0] in ("push", "send-email", "request-pull"):
            return Finding("send", prog, ops)
        if sub and sub[0] in ("clean", "reset", "checkout", "restore", "rm", "stash"):
            return Finding("files.delete", prog, ops)
        return Finding("reversible", prog, ops)
    if prog in ("flatpak",):
        sub = ops[:1]
        if sub and sub[0] in ("list", "info", "search", "remotes", "history", "ps", "permissions", "permission-show"):
            return Finding("read", prog, ops)
        if sub and sub[0] in ("run",):
            return Finding("reversible", prog, ops, "open app")
        if sub and sub[0] in ("install", "update", "uninstall", "remove", "upgrade"):
            if "--system" in a:
                return Finding("elevated", prog, ops)
            return Finding("apps.install", prog, ops[1:])
        if sub and sub[0] in ("kill",):
            return Finding("processes.stop", prog, ops)
        return Finding("shell.run", prog, ops)
    if prog in ("pip", "pip3", "npm", "pnpm", "yarn", "cargo", "gem", "pipx", "uv"):
        if ops[:1] and ops[0] in ("list", "show", "freeze", "search", "view", "outdated"):
            return Finding("read", prog, ops)
        return Finding("apps.install", prog, ops)
    if prog == "systemctl":
        user = "--user" in a
        sub = ops[:1]
        if sub and sub[0] in ("status", "is-active", "is-enabled", "list-units", "list-unit-files", "show", "cat", "list-timers"):
            return Finding("read", prog, ops)
        if sub and sub[0] in ("poweroff", "reboot", "suspend", "hibernate", "halt", "hybrid-sleep", "suspend-then-hibernate"):
            return Finding("system.power", prog, ops)
        if not user:
            return Finding("elevated", prog, ops)
        if sub and sub[0] in ("stop", "kill", "disable", "mask"):
            return Finding("processes.stop", prog, ops)
        return Finding("system.config", prog, ops)
    if prog == "loginctl":
        if ops[:1] and ops[0] in ("lock-session", "lock-sessions"):
            return Finding("reversible", prog, ops)
        if ops[:1] and ops[0] in ("terminate-session", "terminate-user", "kill-session", "kill-user", "poweroff", "reboot"):
            return Finding("system.power", prog, ops)
        return Finding("read", prog, ops)
    if prog == "crontab":
        return Finding("read" if "-l" in a else "system.config", prog, ops)
    if prog in ("pactl", "wpctl", "brightnessctl", "nmcli", "bluetoothctl", "rfkill", "gsettings",
                "kwriteconfig6", "kwriteconfig5", "plasma-apply-colorscheme", "plasma-apply-wallpaperimage",
                "powerprofilesctl", "tuned-adm", "xdg-settings", "timedatectl", "localectl"):
        sub = ops[:1]
        if sub and (sub[0].startswith(("list", "get", "info", "status", "show", "stat", "monitor"))
                    or sub[0] in ("device", "general", "connection") and len(ops) > 1 and ops[1] in ("show", "status", "list", "wifi")
                    and not (len(ops) > 2 and ops[2] in ("connect", "delete", "modify", "up", "down"))):
            return Finding("read", prog, ops)
        if prog == "nmcli" and any(o in ("delete", "modify") for o in ops):
            return Finding("system.config", prog, ops)
        if prog in ("timedatectl", "localectl") and sub and sub[0].startswith("set"):
            return Finding("elevated", prog, ops)
        return Finding("reversible", prog, ops, "setting")
    if prog in READ_ONLY:
        return Finding("read", prog, ops)
    if prog in REVERSIBLE:
        return Finding("reversible", prog, ops)
    return Finding("shell.run", prog, ops, "unknown program")


def _download_target(prog: str, args: list[str]) -> str:
    """The file a curl/wget download writes to, if it is named explicitly."""
    names = ("-o", "--output") if prog == "curl" else ("-O", "--output-document")
    for j, x in enumerate(args):
        if x in names and j + 1 < len(args):
            return args[j + 1]
        for n in names:
            if n.startswith("--") and x.startswith(n + "="):
                return x.split("=", 1)[1]
            if not n.startswith("--") and x.startswith(n) and len(x) > len(n):
                return x[len(n):]
    return ""


def _any_overwrite(ops: list[str], cwd: str) -> bool:
    if len(ops) < 2:
        return False
    dest = os.path.expanduser(ops[-1])
    if not os.path.isabs(dest):
        dest = os.path.join(cwd, dest)
    if os.path.isdir(dest):
        return any(os.path.lexists(os.path.join(dest, os.path.basename(s.rstrip("/")))) for s in ops[:-1])
    return os.path.lexists(dest)


def analyze(command: str, cwd: str) -> ShellAnalysis:
    toks = _tokenize(command)
    if toks is None:
        return ShellAnalysis("shell.run", [Finding("shell.run", "", [], "unparsable")], [])
    findings = [classify_simple(c, cwd) for c in _split_commands(toks)]
    if not findings:
        return ShellAnalysis("read", [Finding("read")], [])
    cat = "read"
    for f in findings:
        cat = worst(cat, f.category)
    # Piping into a shell or interpreter executes arbitrary text.
    progs = [f.program for f in findings if f.program]
    return ShellAnalysis(cat, findings, progs)
