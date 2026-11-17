#!/bin/bash
# reinstall changed components from the source tree (/work, read-only) into this container
# usage: reinstall.sh comp...   (log in /tmp/reinstall.log)
set -u
rm -rf /ctx && mkdir /ctx && (cd /work && tar --exclude=./.git --exclude='*/tests/evidence' -cf - .) | tar -C /ctx -xf -
for c in "$@"; do
  if [ "$c" = image-apps ]; then
    install -Dm0644 /ctx/image/apps/apps.json /usr/share/kristall/apps/apps.json
    install -Dm0755 /ctx/image/rootfs/usr/bin/kristall-apps /usr/bin/kristall-apps
    echo "== image-apps done"; continue
  fi
  echo "== reinstall $c"
  (cd /ctx/$c && KRISTALL_CTX=/ctx KRISTALL_COMPONENT=$c KRISTALL_STRICT=1 bash image/install.sh) > /tmp/reinstall-$(echo $c | tr / -).log 2>&1
  echo "   exit $? (log /tmp/reinstall-$(echo $c | tr / -).log)"; tail -2 /tmp/reinstall-$(echo $c | tr / -).log
done
