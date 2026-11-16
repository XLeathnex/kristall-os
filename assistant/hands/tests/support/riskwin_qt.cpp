// SPDX-License-Identifier: GPL-3.0-or-later
// riskwin_qt: the Qt 6 twin of riskwin.py for the risky-target gate (tests/test_riskgate_e2e.py).
// A "new message" dialog with a line edit and the buttons Senden (the default button: Return in the
// line edit presses it), Abbrechen, In den Papierkorb, Text löschen and Aufräumen…, which opens a
// message box "Möchtest du 3 Dateien endgültig löschen?" with Abbrechen and OK (OK is the default).
// Every activation is logged on stdout as a JSON line.
// Build: g++ -std=c++17 -fPIC riskwin_qt.cpp $(pkg-config --cflags --libs Qt6Widgets) -o riskwin_qt
#include <QApplication>
#include <QDialog>
#include <QElapsedTimer>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>
#include <cstdio>

static QElapsedTimer clock0;

static void logLine(const QString &json)
{
    std::printf("%s\n", json.toUtf8().constData());
    std::fflush(stdout);
}

static QString esc(QString s)
{
    return s.replace(QLatin1Char('\\'), QLatin1String("\\\\")).replace(QLatin1Char('"'), QLatin1String("\\\""));
}

int main(int argc, char **argv)
{
    clock0.start();
    QApplication app(argc, argv);
    app.setDesktopFileName(QStringLiteral("riskwin-qt"));
    QDialog win;
    win.setWindowTitle(argc > 1 ? QString::fromUtf8(argv[1]) : QStringLiteral("Neue Nachricht – Testpost"));
    win.resize(640, 200);
    auto *box = new QVBoxLayout(&win);
    box->addWidget(new QLabel(QStringLiteral("Nachricht an Oma:")));
    auto *line = new QLineEdit(QStringLiteral("Hallo Oma, bis Sonntag!"));
    box->addWidget(line);
    auto *row = new QHBoxLayout;
    box->addLayout(row);
    const QStringList names = {QStringLiteral("Senden"), QStringLiteral("Abbrechen"), QStringLiteral("In den Papierkorb"),
                               QStringLiteral("Text löschen"), QStringLiteral("Aufräumen…")};
    for (const QString &name : names) {
        auto *b = new QPushButton(name);
        b->setAutoDefault(false);
        if (name == names[0])
            b->setDefault(true);
        row->addWidget(b);
        QObject::connect(b, &QPushButton::clicked, [&win, line, name] {
            logLine(QStringLiteral("{\"ev\":\"clicked\",\"name\":\"%1\",\"t\":%2}").arg(esc(name)).arg(clock0.elapsed()));
            if (name == QStringLiteral("Text löschen")) {
                line->clear();
            } else if (name == QStringLiteral("Aufräumen…")) {
                auto *mb = new QMessageBox(QMessageBox::Warning, QStringLiteral("Aufräumen"),
                                           QStringLiteral("Möchtest du 3 Dateien endgültig löschen?"), QMessageBox::NoButton, &win);
                mb->setInformativeText(QStringLiteral("Urlaub.jpg, Rechnung.pdf und Notizen.txt werden nicht in den Papierkorb gelegt."));
                QPushButton *cancel = mb->addButton(QStringLiteral("Abbrechen"), QMessageBox::RejectRole);
                QPushButton *ok = mb->addButton(QStringLiteral("OK"), QMessageBox::AcceptRole);
                mb->setDefaultButton(ok);
                mb->setAttribute(Qt::WA_DeleteOnClose);
                QObject::connect(mb, &QMessageBox::buttonClicked, [ok, cancel](QAbstractButton *which) {
                    logLine(QStringLiteral("{\"ev\":\"dialog\",\"response\":\"%1\"}")
                                .arg(which == ok ? QStringLiteral("ok") : which == cancel ? QStringLiteral("cancel") : QStringLiteral("other")));
                });
                mb->open();
                logLine(QStringLiteral("{\"ev\":\"dialog_open\"}"));
            }
        });
    }
    win.show();
    line->setFocus();
    logLine(QStringLiteral("{\"ev\":\"started\"}"));
    return app.exec();
}
