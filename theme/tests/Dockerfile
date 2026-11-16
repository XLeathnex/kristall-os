# kristall-devenv-theme: the dev container plus what the theme tests need and the base lacks
# Build: docker build --network host --build-arg HTTPS_PROXY="$HTTPS_PROXY" -t kristall-devenv-theme -f theme/tests/Dockerfile tools/devenv
# (GTK 3/4 demo apps, libadwaita, Firefox, kde-gtk-config, adw-gtk3, KWrite, fonts, and Plymouth +
# dracut + a kernel to check the initramfs change). Temporary; removed when the theme work is done.
FROM kristall-devenv:latest
ARG HTTPS_PROXY=""
ENV https_proxy=${HTTPS_PROXY} HTTPS_PROXY=${HTTPS_PROXY}
RUN for p in gtk3-devel-docs gtk4-devel-tools libadwaita adw-gtk3-theme kde-gtk-config kwrite firefox \
      jetbrains-mono-fonts-all unity-gtk3-module unity-gtk-module-common plymouth plymouth-plugin-two-step plymouth-scripts \
      dracut ostree kernel-core gtk3-demo gtk4-demo xdg-desktop-portal-gtk dconf; do \
      rpm -q "$p" >/dev/null 2>&1 || dnf5 install -y --setopt=install_weak_deps=False "$p" >/tmp/dnf.log 2>&1 \
        || { echo "MISSING $p"; tail -2 /tmp/dnf.log; }; done; \
    dnf5 clean all >/dev/null 2>&1; rm -rf /var/cache/dnf /var/cache/libdnf5 /tmp/dnf.log; \
    rm -rf /usr/share/gtk-doc /usr/share/doc /usr/share/help /usr/lib64/firefox/browser/features/*langpack* /usr/share/man; \
    rpm -q gtk3 gtk4 libadwaita firefox kernel-core plymouth dracut kwrite adw-gtk3-theme kde-gtk-config 2>&1
ENV https_proxy="" HTTPS_PROXY=""
