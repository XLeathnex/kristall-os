# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall OS: a bootable container image (bootc) built on Universal Blue's Kinoite.
#
# Base stream: Fedora 45. Bump FEDORA_VERSION deliberately (and test) to move to the next Fedora;
# the daily CI build picks up every security update of the 45 stream on its own.
# Optionally pin an exact base for a reproducible rebuild: --build-arg BASE_DIGEST=sha256:...
#
#   podman build -t localhost/kristall-os:latest .        (see image/README.md)
ARG BASE_IMAGE=ghcr.io/ublue-os/kinoite-main
ARG FEDORA_VERSION=45
ARG BASE_DIGEST=""

FROM ${BASE_IMAGE}:${FEDORA_VERSION}${BASE_DIGEST:+@${BASE_DIGEST}}

# 1 = every component in image/components.list must exist (release builds in CI).
ARG KRISTALL_STRICT=0
# Recorded in os-release / build-info.json; set by CI.
ARG KRISTALL_IMAGE_VERSION=""
ARG KRISTALL_IMAGE_REF=""
ARG KRISTALL_REPO_URL=""
ARG KRISTALL_GIT_SHA=""

# The repository is mounted read-only at /ctx for the build only; nothing of it is copied
# except what the component installers install.
RUN --mount=type=bind,source=.,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    KRISTALL_STRICT="${KRISTALL_STRICT}" \
    KRISTALL_IMAGE_VERSION="${KRISTALL_IMAGE_VERSION}" \
    KRISTALL_IMAGE_REF="${KRISTALL_IMAGE_REF}" \
    KRISTALL_REPO_URL="${KRISTALL_REPO_URL}" \
    KRISTALL_GIT_SHA="${KRISTALL_GIT_SHA}" \
    bash /ctx/image/build.sh

# Current practice for bootc images: static checks of the final filesystem.
RUN bootc container lint

LABEL org.opencontainers.image.title="kristall-os" \
      org.opencontainers.image.description="Kristall OS: an image-based desktop that updates itself" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      containers.bootc="1" \
      ostree.bootable="true"
