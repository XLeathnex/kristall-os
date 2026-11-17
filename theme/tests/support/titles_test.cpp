// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only: prints ownerCaption() (theme/decoration/titles.cpp) for each argument, one per line.
#include "../../decoration/titles.h"

#include <QCoreApplication>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);
    for (int i = 1; i < argc; ++i) {
        out << Kristall::ownerCaption(QString::fromUtf8(argv[i])) << '\n';
    }
    return 0;
}
