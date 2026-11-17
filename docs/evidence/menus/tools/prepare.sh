#!/bin/bash
# Inside the container, as root: the test-only pieces the sandbox needs (ARCHITECTURE §9), then a
# fresh owner account from /etc/skel exactly as Plasma Setup would create it.
set -euo pipefail
mkdir -p /opt/integ
gcc -shared -fPIC -O2 -o /opt/integ/fake_udmabuf.so /work/kwin/glass/tests/support/fake_udmabuf.c -ldl
mkdir -p /opt/integ/real; mountpoint -q /usr/bin/kwin_wayland || cp /usr/bin/kwin_wayland /opt/integ/real/kwin_wayland   # a copy has no cap_sys_nice; KWin's QPA wants the name kwin_wayland
cat >/opt/integ/kwin_wayland <<'SH'
#!/bin/sh
# integ shim for the sandbox: the real KWin, headless (virtual backend, one 2880x1800 output),
# llvmpipe with the udmabuf shim. Everything else (wrapper, units, Xwayland, plugins) is the OS's.
export LD_PRELOAD=/opt/integ/fake_udmabuf.so KWIN_DISABLE_VULKAN=1 LIBGL_ALWAYS_SOFTWARE=1
exec /opt/integ/real/kwin_wayland --virtual --width 2880 --height 1800 "$@"
SH
chmod 755 /opt/integ/kwin_wayland
mountpoint -q /usr/bin/kwin_wayland || mount --bind /opt/integ/kwin_wayland /usr/bin/kwin_wayland
gcc -O2 -o /opt/integ/owner /work/kwin/bridge/tests/clients/owner.c /tmp/fi-protocol.c -I/tmp $(pkg-config --cflags --libs wayland-client) 2>/dev/null || {
  P=/usr/share/plasma-wayland-protocols/fake-input.xml
  wayland-scanner client-header $P /tmp/fake-input-client-protocol.h
  wayland-scanner private-code $P /tmp/fi-protocol.c
  gcc -O2 -o /opt/integ/owner /work/kwin/bridge/tests/clients/owner.c /tmp/fi-protocol.c -I/tmp $(pkg-config --cflags --libs wayland-client)
}
# the display manager has no seat here; the session is started below the way it would start it
systemctl stop plasmalogin.service || true
# a fresh owner account, as Plasma Setup creates it (home from /etc/skel), German as chosen there
loginctl disable-linger kristall 2>/dev/null || true
pkill -u kristall || true
rm -rf /home/kristall && cp -a /etc/skel /home/kristall && chown -R kristall:kristall /home/kristall
install -d -o kristall -g kristall /home/kristall/.config
L=${INTEG_LANG:-de_DE.UTF-8}
printf '[Formats]\nLANG=%s\n\n[Translations]\nLANGUAGE=%s\n' "$L" "${L%%_*}" >/home/kristall/.config/plasma-localerc
printf '[Layout]\nLayoutList=de\nUse=true\n' >/home/kristall/.config/kxkbrc   # Plasma Setup's keyboard step
chown kristall:kristall /home/kristall/.config/plasma-localerc /home/kristall/.config/kxkbrc
if [ "${INTEG_SETUP_DONE:-0}" = 1 ]; then     # walkthrough after step 1: the Setup Assistant was finished before
  install -d -o kristall -g kristall /home/kristall/.config/kristall
  printf '{"setup": {"done": true}, "appearance": {"theme": "light", "accent": "green"}}\n' >/home/kristall/.config/kristall/settings.json
  chown kristall:kristall /home/kristall/.config/kristall/settings.json
fi
localectl set-locale LANG="$L" 2>/dev/null || echo "LANG=$L" >/etc/locale.conf
echo prepared
# menus round: no idle lock while testing
install -d -o kristall -g kristall /home/kristall/.config
printf '[Daemon]\nAutolock=false\nTimeout=0\nLockOnResume=false\n' >/home/kristall/.config/kscreenlockerrc
printf '[AC][DPMSControl]\nidleTime=0\n' >/dev/null
chown kristall:kristall /home/kristall/.config/kscreenlockerrc
echo kristall:kristall | chpasswd
