/*
    Kristall OS — kristall-hands launcher
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    Embeds the system Python and runs the kristall_hands package from HANDS_LIB.

    Why a compiled launcher instead of a script: the compositor bridge (docs/contracts/bridge.md)
    grants agent input and screenshots only to a peer whose /proc/<pid>/exe is one of our installed
    binaries. For a Python script that would be /usr/bin/python3.x, which every program can run.
    Here /proc/<pid>/exe is /usr/bin/kristall-hands itself. The interpreter runs isolated
    (PYTHON* environment variables, the user site directory and the current directory are ignored),
    so the environment cannot redirect it to other code.
*/
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#ifndef HANDS_LIB
#define HANDS_LIB "/usr/lib/kristall/hands"
#endif

static int fail(PyConfig *config, PyStatus status)
{
    PyConfig_Clear(config);
    if (PyStatus_IsExit(status)) {
        return status.exitcode;
    }
    Py_ExitStatusException(status);
    return 1;
}

int main(int argc, char **argv)
{
    PyStatus status;
    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.site_import = 1;          /* system site-packages: python3-gobject (gi) lives there */
    config.write_bytecode = 0;       /* /usr is read-only; bytecode is compiled at image build */
    config.parse_argv = 0;           /* our arguments are kristall-hands arguments, not Python's */
    config.install_signal_handlers = 1;

    status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (PyStatus_Exception(status)) {
        return fail(&config, status);
    }
    /* isolated mode ignores PYTHONPATH-style settings, so the path is put in place explicitly */
    status = PyConfig_SetBytesString(&config, &config.run_command,
                                     "import sys\n"
                                     "sys.path.insert(0, '" HANDS_LIB "')\n"
                                     "from kristall_hands.__main__ import main\n"
                                     "sys.exit(main(sys.argv[1:]))\n");
    if (PyStatus_Exception(status)) {
        return fail(&config, status);
    }
    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        return fail(&config, status);
    }
    PyConfig_Clear(&config);
    return Py_RunMain();
}
