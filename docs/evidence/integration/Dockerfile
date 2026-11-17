# kristall-integ: the dev container plus every component installed by the real image/build.sh,
# as close to the OS image as is possible without the kinoite-main base.
FROM kristall-devenv:latest
# Packages the Kinoite base ships that the dev container lacks (apps of image/apps/apps.json that
# are RPMs in the base, Plasma Setup, flatpak), the negativo17 repository the base has enabled,
# and test-only apps: a GTK 3 app with a menu bar (mousepad) and a GTK 4 app (gtk4-demo).
# The dev container's nodejs 22 conflicts with the image's nodejs26 (the base has no nodejs).
RUN dnf5 -y remove nodejs nodejs-npm >/dev/null \
 && curl -fsSLo /etc/yum.repos.d/negativo17-fedora-multimedia.repo https://negativo17.org/repos/fedora-multimedia.repo \
 && for p in plasma-setup flatpak kwrite ark plasma-systemmonitor mousepad gtk4-devel-tools \
       pipewire-pulseaudio pulseaudio-utils xdotool gnome-text-editor; do \
      rpm -q "$p" >/dev/null 2>&1 || dnf5 install -y --setopt=install_weak_deps=False "$p" >/tmp/dnf.log 2>&1 \
        || { echo "$p" >> /integ-missing.txt; tail -3 /tmp/dnf.log; }; done; dnf5 clean all >/dev/null; true
COPY . /ctx
RUN set -o pipefail; KRISTALL_STRICT=1 KRISTALL_BUILD_PHASES=prepare,components,presets \
      bash /ctx/image/build.sh 2>&1 | tee /integ-build.log
# The finalize phase minus check_kernel (no kernel in a container): sessions, manifests, cleanup.
RUN set -o pipefail; sed '/^# -* main/,$d' /ctx/image/build.sh > /tmp/b.sh \
 && bash -c 'source /tmp/b.sh; set -euo pipefail; check_sessions; check_manifests' 2>&1 | tee /integ-finalize.log; rm -f /tmp/b.sh
