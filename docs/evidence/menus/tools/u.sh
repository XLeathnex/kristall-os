#!/bin/bash
# run a command as the owner with the session's environment (what the user manager has)
exec runuser -u kristall -- bash -c 'export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
while IFS= read -r l; do export "$l"; done < <(systemctl --user show-environment 2>/dev/null | grep -E "^(WAYLAND_DISPLAY|DISPLAY|XAUTHORITY|LANG|LANGUAGE|LC_[A-Z]+|XDG_[A-Z_]+|QT_[A-Z_]+|GTK_[A-Z_]+|GDK_[A-Z_]+|KDE_[A-Z_]+|PATH)=")
exec "$@"' u "$@"
