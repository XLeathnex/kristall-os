// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only LD_PRELOAD shim for the cloud sandbox: the dev container has no /dev/dri and no
// /dev/udmabuf, and KWin 6.8 only creates its llvmpipe "software render device" when
// /dev/udmabuf can be opened. This shim pretends /dev/udmabuf exists and implements
// UDMABUF_CREATE by handing back a dup() of the memfd itself (llvmpipe imports "dmabufs" by
// mmap()ing the fd, which works for a memfd). Never shipped, never used on real hardware.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <linux/udmabuf.h>

static int fake_open(const char *path)
{
    if (path && strcmp(path, "/dev/udmabuf") == 0) {
        return openat(AT_FDCWD, "/dev/null", O_RDWR | O_CLOEXEC);
    }
    return -2;
}

#define WRAP_OPEN(name)                                                         \
    int name(const char *path, int flags, ...)                                  \
    {                                                                           \
        int r = fake_open(path);                                                \
        if (r != -2)                                                            \
            return r;                                                           \
        mode_t mode = 0;                                                        \
        if (flags & (O_CREAT | O_TMPFILE)) {                                    \
            va_list ap;                                                         \
            va_start(ap, flags);                                                \
            mode = va_arg(ap, mode_t);                                          \
            va_end(ap);                                                         \
        }                                                                       \
        static int (*real)(const char *, int, ...);                             \
        if (!real)                                                              \
            real = dlsym(RTLD_NEXT, #name);                                     \
        return real(path, flags, mode);                                         \
    }
WRAP_OPEN(open)
WRAP_OPEN(open64)

int __open_2(const char *path, int flags)
{
    int r = fake_open(path);
    if (r != -2)
        return r;
    static int (*real)(const char *, int);
    if (!real)
        real = dlsym(RTLD_NEXT, "__open_2");
    return real(path, flags);
}

int ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    // There is no real /dev/udmabuf here, so every UDMABUF_CREATE is meant for the fake device
    // (KWin may have opened it more than once).
    if (fd >= 0 && request == UDMABUF_CREATE) {
        struct udmabuf_create *c = arg;
        if (c->offset != 0) {
            errno = EINVAL; // KWin falls back to its regular shm upload path
            return -1;
        }
        return fcntl((int)c->memfd, F_DUPFD_CLOEXEC, 0);
    }
    static int (*real)(int, unsigned long, ...);
    if (!real)
        real = dlsym(RTLD_NEXT, "ioctl");
    return real(fd, request, arg);
}
