#!/bin/bash
# Starts kristall-integ with systemd as PID 1 (cgroup2 mounted privately: the host is cgroup v1).
set -e
name=${1:-kristall-menus-os}
docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d -t -e container=docker --name "$name" --privileged --cgroupns=private --shm-size=1g \
  -v /home/user/kristall:/work:ro \
  -v /tmp/claude-0/-home-user-kristall-os/86b195bd-b2b0-5fa6-8457-b161a4db30d9/scratchpad/menus/tools:/integ:ro \
  -v /tmp/claude-0/-home-user-kristall-os/86b195bd-b2b0-5fa6-8457-b161a4db30d9/scratchpad/menus/shots:/shots \
  kristall-integ:latest bash -c 'umount -R /sys/fs/cgroup 2>/dev/null; mount -t cgroup2 none /sys/fs/cgroup && exec /usr/lib/systemd/systemd --system'
for i in $(seq 1 60); do
  s=$(docker exec "$name" systemctl is-system-running 2>/dev/null || true)
  [[ $s == running || $s == degraded ]] && break
  sleep 1
done
echo "system: $s"
