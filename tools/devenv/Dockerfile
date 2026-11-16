# Kristall dev/test environment: Fedora 45 (same release + repos as the OS base image,
# ghcr.io/ublue-os/kinoite-main -> KWin/Plasma 6.8, Qt 6.11) with compilers, KWin/Qt/KF6 headers,
# Quickshell and test tools. Purpose: compile KWin plugins against the KWin the OS ships and run
# headless sessions (kwin_wayland --virtual + llvmpipe) to test and screenshot. Never shipped to users.
FROM quay.io/fedora/fedora:45
# A proxy (the cloud sandbox) arrives as Docker's predefined build arguments https_proxy/HTTPS_PROXY
# (build.sh passes them when set): dnf5 (libcurl) and pip read them from the environment of each
# RUN, they are not stored in the image, and — not being declared with ARG — a changed proxy port
# does not invalidate the build cache. Without a proxy (GitHub's runners) nothing changes.
COPY ca-bundle.crt /etc/pki/ca-trust/source/anchors/sandbox-proxy.crt
RUN update-ca-trust \
 && for f in /etc/yum.repos.d/*.repo /usr/share/dnf5/repos.d/*.repo; do \
      [ -f "$f" ] && sed -i 's/^metalink=\(.*\)$/metalink=\1\&protocol=https/' "$f"; done \
 && for f in /etc/yum.repos.d/fedora-cisco-openh264.repo /usr/share/dnf5/repos.d/fedora-cisco-openh264.repo; do \
      [ -f "$f" ] && sed -i 's/^enabled=1/enabled=0/' "$f"; done \
 && echo "install_weak_deps=False" >> /etc/dnf/dnf.conf && echo "max_parallel_downloads=10" >> /etc/dnf/dnf.conf
# Runtime desktop stack (must succeed)
RUN dnf5 install -y kwin plasma-workspace plasma-desktop kscreenlocker xorg-x11-server-Xwayland \
      mesa-dri-drivers mesa-libEGL mesa-libGL dbus-daemon at-spi2-core layer-shell-qt \
      gcc-c++ cmake ninja-build extra-cmake-modules git-core kwin-devel qt6-qtbase-devel \
      qt6-qtbase-private-devel qt6-qtdeclarative-devel qt6-qtwayland-devel sudo which procps-ng findutils \
 && dnf5 clean all
# Everything else is installed one-by-one so a wrong package name never breaks the image;
# names that could not be installed are listed in /devenv-missing.txt.
RUN for p in rpm-build pkgconf-pkg-config kdecoration-devel layer-shell-qt-devel plasma-wayland-protocols-devel \
      wayland-protocols-devel qt6-qtsvg-devel qt6-qttools-devel qt6-qtshadertools qt6-qt5compat qt6-qtmultimedia \
      kf6-kconfig-devel kf6-kcoreaddons-devel kf6-kwindowsystem-devel kf6-ki18n-devel kf6-kcmutils-devel \
      kf6-kconfigwidgets-devel kf6-kguiaddons-devel kf6-kglobalaccel-devel kf6-kcrash-devel kf6-kservice-devel \
      kf6-kio-devel kf6-knotifications-devel kf6-kxmlgui-devel kf6-kpackage-devel kf6-ksvg-devel \
      libepoxy-devel wayland-devel libdrm-devel libxkbcommon-devel libxcb-devel libei-devel libinput-devel systemd-devel \
      quickshell python3-pip python3-devel python3-gobject python3-dbus python3-pyatspi python3-evdev \
      python3-pytest python3-numpy python3-pillow ImageMagick ShellCheck glslang jq socat wl-clipboard wtype foot \
      konsole dolphin kate spectacle kvantum rsms-inter-fonts dejavu-sans-fonts google-noto-sans-fonts \
      google-noto-color-emoji-fonts nodejs npm ydotool keyd tuned tuned-ppd pipewire wireplumber \
      plasma-login-manager plasma-systemsettings xdg-desktop-portal-kde kf6-kirigami qqc2-desktop-style; do \
      rpm -q "$p" >/dev/null 2>&1 || dnf5 install -y "$p" >/tmp/dnf.log 2>&1 \
        || { echo "$p" >> /devenv-missing.txt; tail -2 /tmp/dnf.log; }; \
    done; \
    if ! rpm -q quickshell >/dev/null 2>&1; then \
      (dnf5 install -y dnf5-plugins && dnf5 -y copr enable errornointernet/quickshell && dnf5 install -y quickshell \
        && sed -i '/^quickshell$/d' /devenv-missing.txt) || true; \
    fi; \
    dnf5 clean all >/dev/null 2>&1; rm -f /tmp/dnf.log; \
    echo "--- missing ---"; cat /devenv-missing.txt 2>/dev/null; echo "--- versions ---"; \
    rpm -q kwin kwin-devel plasma-workspace qt6-qtbase quickshell gcc-c++ cmake
# Added 2026-11-16 (in a layer of its own, so the layers above stay cached): plasma-milou (KWin's Overview
# effect needs it), kf6-baloo-file (real file indexing for Search), firefox (the RPM the OS image
# ships: accessibility tests and measurements for hands), pipewire-utils (pw-cli for the assistant).
RUN for p in plasma-milou kf6-baloo-file firefox pipewire-utils; do \
      rpm -q "$p" >/dev/null 2>&1 || dnf5 install -y "$p" >/tmp/dnf.log 2>&1 \
        || { echo "$p" >> /devenv-missing.txt; tail -2 /tmp/dnf.log; }; \
    done; dnf5 clean all >/dev/null 2>&1; rm -f /tmp/dnf.log; rpm -q plasma-milou kf6-baloo-file firefox || true
# The assistant daemon's hash-pinned Python environment (assistant/core/image/*requirements.txt,
# copied into the build context by build.sh), exactly as its image installer builds it, so that
# assistant/core/tests/run.sh and the daemon's demo mode (`python -m kristall_assistant.daemon
# --demo` with PYTHONPATH=assistant/core) run inside the container without network. pip is pointed
# at the system CA bundle, which includes the sandbox proxy's CA when one was given.
# Python 3.14, not the system 3.15, exactly as assistant/core/image/install.sh does in the OS image:
# the pinned sherpa-onnx 1.13.8 (tested API and models) publishes no cp315 wheel.
COPY assistant-requirements.txt assistant-build-requirements.txt /tmp/assistant/
RUN dnf5 install -y python3.14 >/dev/null && dnf5 clean all >/dev/null \
 && python3.14 -m venv /opt/kristall-assistant-venv \
 && export PIP_CERT=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 \
 && /opt/kristall-assistant-venv/bin/pip install --quiet --require-hashes -r /tmp/assistant/assistant-build-requirements.txt \
 && /opt/kristall-assistant-venv/bin/pip install --quiet --require-hashes --no-build-isolation \
      --no-binary claude-agent-sdk -r /tmp/assistant/assistant-requirements.txt \
 && /opt/kristall-assistant-venv/bin/pip install --quiet pytest \
 && /opt/kristall-assistant-venv/bin/python -c 'import claude_agent_sdk, sherpa_onnx, numpy, pytest' \
 && rm -rf /tmp/assistant
ENV KRISTALL_TEST_PYTHON=/opt/kristall-assistant-venv/bin/python
RUN useradd -m -u 1000 -G wheel kristall 2>/dev/null; echo '%wheel ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/wheel-nopasswd
ENV LIBGL_ALWAYS_SOFTWARE=1
WORKDIR /work
