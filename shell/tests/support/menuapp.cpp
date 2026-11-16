// SPDX-License-Identifier: GPL-3.0-or-later
// A real Qt Widgets application with a menu bar, for the shell's app-menu test. Qt exports the
// menu bar over DBusMenu when an AppMenu registrar is on the session bus (the shell then shows it).
// Prints "TRIGGERED <text>" when an action is triggered.
#include <QApplication>
#include <QMainWindow>
#include <QMenuBar>
#include <QLabel>
#include <QActionGroup>
#include <QSystemTrayIcon>
#include <QPainter>
#include <QPixmap>
#include <cstdio>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("menuapp"));
    app.setDesktopFileName(QStringLiteral("org.kristall.MenuApp"));
    QMainWindow w;
    w.setWindowTitle(QStringLiteral("Menu App"));
    w.setCentralWidget(new QLabel(QStringLiteral("Kristall menu test")));
    auto report = [](QAction *a) { std::printf("TRIGGERED %s\n", qPrintable(a->text().remove(QLatin1Char('&')))); std::fflush(stdout); };

    QMenu *file = w.menuBar()->addMenu(QStringLiteral("&Datei"));
    file->addAction(QStringLiteral("&Neu"), QKeySequence::New);
    file->addAction(QStringLiteral("Ö&ffnen …"), QKeySequence::Open);
    QMenu *recent = file->addMenu(QStringLiteral("Zuletzt geöffnet"));
    recent->addAction(QStringLiteral("Brief.txt"));
    recent->addAction(QStringLiteral("Notizen.md"));
    file->addSeparator();
    QAction *save = file->addAction(QStringLiteral("&Sichern"), QKeySequence::Save);
    save->setEnabled(false);
    file->addSeparator();
    file->addAction(QStringLiteral("&Beenden"), QKeySequence(QStringLiteral("Ctrl+Q")));

    QMenu *edit = w.menuBar()->addMenu(QStringLiteral("&Bearbeiten"));
    edit->addAction(QStringLiteral("Widerrufen"), QKeySequence::Undo);
    edit->addAction(QStringLiteral("Ausschneiden"), QKeySequence::Cut);
    edit->addAction(QStringLiteral("Kopieren"), QKeySequence::Copy);

    QMenu *view = w.menuBar()->addMenu(QStringLiteral("&Darstellung"));
    QAction *bar = view->addAction(QStringLiteral("Statusleiste"));
    bar->setCheckable(true);
    bar->setChecked(true);
    view->addSeparator();
    auto *group = new QActionGroup(&w);
    for (const char *z : {"Klein", "Mittel", "Groß"}) {
        QAction *a = view->addAction(QString::fromUtf8(z));
        a->setCheckable(true);
        a->setActionGroup(group);
        a->setChecked(QLatin1String(z) == QLatin1String("Mittel"));
    }
    QMenu *help = w.menuBar()->addMenu(QStringLiteral("&Hilfe"));
    help->addAction(QStringLiteral("Über Menu App"));

    QObject::connect(w.menuBar(), &QMenuBar::triggered, report);
    if (app.arguments().contains(QStringLiteral("--tray"))) {
        // a StatusNotifierItem with a menu (Qt exports both over D-Bus when a watcher exists)
        QPixmap pm(32, 32);
        pm.fill(Qt::transparent);
        QPainter p(&pm);
        p.setRenderHint(QPainter::Antialiasing);
        p.setBrush(QColor(0x30, 0x9b, 0xff));
        p.setPen(Qt::NoPen);
        p.drawEllipse(4, 4, 24, 24);
        p.end();
        auto *tray = new QSystemTrayIcon(QIcon(pm), &w);
        auto *trayMenu = new QMenu(&w);
        trayMenu->addAction(QStringLiteral("Synchronisieren"));
        QAction *pause = trayMenu->addAction(QStringLiteral("Pausiert"));
        pause->setCheckable(true);
        trayMenu->addSeparator();
        trayMenu->addAction(QStringLiteral("Beenden"));
        QObject::connect(trayMenu, &QMenu::triggered, report);
        tray->setContextMenu(trayMenu);
        tray->setToolTip(QStringLiteral("Menu App Sync"));
        tray->show();
        std::printf("TRAY %d\n", QSystemTrayIcon::isSystemTrayAvailable() ? 1 : 0);
    }
    std::printf("NATIVE %d\n", w.menuBar()->isNativeMenuBar() ? 1 : 0);
    std::fflush(stdout);
    w.resize(600, 400);
    if (app.arguments().contains(QStringLiteral("--maximized")))
        w.showMaximized();
    else
        w.show();
    return app.exec();
}
