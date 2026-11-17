// SPDX-License-Identifier: GPL-3.0-or-later
// qtprobe: a Qt Widgets test client for kristall-bridge. Runs natively on Wayland or under XWayland
// (QT_QPA_PLATFORM=xcb). Logs, one JSON object per line: mouse events on the "pad" (local logical
// coordinates as Qt delivers them), hover enter/leave, wheel, keys, line-edit text, slider value,
// text-edit selection, menu actions and context-menu actions. At start it prints the layout of
// its widgets relative to the window's content origin.
#include <QAction>
#include <QApplication>
#include <QBoxLayout>
#include <QContextMenuEvent>
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLineEdit>
#include <QMainWindow>
#include <QMenu>
#include <QMenuBar>
#include <QMouseEvent>
#include <QSlider>
#include <QTextEdit>
#include <QTimer>
#include <QWheelEvent>
#include <QWindow>
#include <cstdio>

static void logj(QJsonObject o)
{
    static QElapsedTimer t = [] { QElapsedTimer e; e.start(); return e; }();
    o.insert(QStringLiteral("t"), double(t.nsecsElapsed()) / 1e6);
    const QByteArray line = QJsonDocument(o).toJson(QJsonDocument::Compact);
    fwrite(line.constData(), 1, line.size(), stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static QJsonObject mouse(const char *ev, QMouseEvent *e)
{
    return QJsonObject{{"ev", ev}, {"x", e->position().x()}, {"y", e->position().y()}, {"button", int(e->button())},
                       {"buttons", int(e->buttons())}, {"mods", int(e->modifiers())}};
}

class Pad : public QWidget
{
public:
    Pad()
    {
        setMouseTracking(true);
        setAttribute(Qt::WA_Hover);
        setMinimumSize(300, 150);
        setAutoFillBackground(true);
        QPalette p = palette();
        p.setColor(QPalette::Window, QColor(80, 160, 90));
        setPalette(p);
    }

protected:
    void mousePressEvent(QMouseEvent *e) override
    {
        logj(mouse("press", e));
    }
    void mouseReleaseEvent(QMouseEvent *e) override
    {
        logj(mouse("release", e));
    }
    void mouseDoubleClickEvent(QMouseEvent *e) override
    {
        logj(mouse("dblclick", e));
    }
    void mouseMoveEvent(QMouseEvent *e) override
    {
        logj(mouse("move", e));
    }
    void enterEvent(QEnterEvent *e) override
    {
        logj({{"ev", "hover"}, {"in", true}, {"x", e->position().x()}, {"y", e->position().y()}});
    }
    void leaveEvent(QEvent *) override
    {
        logj({{"ev", "hover"}, {"in", false}});
    }
    void wheelEvent(QWheelEvent *e) override
    {
        logj({{"ev", "wheel"}, {"dx", e->angleDelta().x()}, {"dy", e->angleDelta().y()}, {"x", e->position().x()}, {"y", e->position().y()}, {"mods", int(e->modifiers())}});
    }
    void keyPressEvent(QKeyEvent *e) override
    {
        logj({{"ev", "key"}, {"key", e->key()}, {"text", e->text()}, {"mods", int(e->modifiers())}});
    }
    void contextMenuEvent(QContextMenuEvent *e) override
    {
        logj({{"ev", "context"}, {"x", e->pos().x()}, {"y", e->pos().y()}});
        auto *m = new QMenu(this);
        m->setAttribute(Qt::WA_DeleteOnClose);
        for (const char *name : {"Alpha", "Beta", "Gamma"}) {
            QAction *a = m->addAction(QString::fromLatin1(name));
            QObject::connect(a, &QAction::triggered, [name] {
                logj({{"ev", "context_action"}, {"name", name}});
            });
        }
        QObject::connect(m, &QMenu::aboutToShow, [] {
            logj({{"ev", "context_shown"}});
        });
        m->popup(e->globalPos());
    }
};

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    // every key press any widget receives (diagnostics for key paths), with the focused widget
    struct KeyLog : QObject {
        bool eventFilter(QObject *o, QEvent *e) override
        {
            if (e->type() == QEvent::KeyPress && o->isWidgetType()) {
                auto *k = static_cast<QKeyEvent *>(e);
                logj({{"ev", "keypress"}, {"key", k->key()}, {"text", k->text()}, {"mods", int(k->modifiers())}, {"widget", QString::fromLatin1(o->metaObject()->className())}});
            }
            return false;
        }
    };
    KeyLog keyLog;
    app.installEventFilter(&keyLog);
    app.setApplicationName(QStringLiteral("qtprobe"));
    app.setDesktopFileName(QStringLiteral("qtprobe"));
    QMainWindow win;
    win.setWindowTitle(argc > 1 ? QString::fromLocal8Bit(argv[1]) : QStringLiteral("qtprobe"));
    QMenu *file = win.menuBar()->addMenu(QStringLiteral("&File"));
    for (const char *name : {"New", "Open", "Quit"}) {
        QAction *a = file->addAction(QString::fromLatin1(name));
        QObject::connect(a, &QAction::triggered, [name] {
            logj({{"ev", "action"}, {"name", name}});
        });
    }
    QObject::connect(file, &QMenu::aboutToShow, [] {
        logj({{"ev", "menu_shown"}, {"menu", "File"}});
    });
    QMenu *edit = win.menuBar()->addMenu(QStringLiteral("&Edit"));
    edit->addAction(QStringLiteral("Copy"));
    // the menu bar's state: in the window (visible, not native) or exported (native, hidden)
    struct BarLog : QObject {
        bool eventFilter(QObject *o, QEvent *e) override
        {
            if (e->type() == QEvent::Show || e->type() == QEvent::Hide) {
                auto *bar = static_cast<QMenuBar *>(o);
                QMetaObject::invokeMethod(
                    bar,
                    [bar] {
                        logj({{"ev", "menubar"}, {"visible", bar->isVisible()}, {"native", bar->isNativeMenuBar()}, {"h", bar->height()}});
                    },
                    Qt::QueuedConnection);
            }
            return false;
        }
    };
    BarLog barLog;
    win.menuBar()->installEventFilter(&barLog);

    auto *central = new QWidget;
    auto *layout = new QVBoxLayout(central);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto *line = new QLineEdit;
    line->setFixedHeight(40);
    auto *slider = new QSlider(Qt::Horizontal);
    slider->setRange(0, 100);
    slider->setFixedHeight(40);
    auto *text = new QTextEdit;
    text->setPlainText(QStringLiteral("alpha beta gamma delta epsilon"));
    text->setFixedHeight(80);
    auto *pad = new Pad;
    layout->addWidget(line);
    layout->addWidget(slider);
    layout->addWidget(text);
    layout->addWidget(pad, 1);
    win.setCentralWidget(central);
    QObject::connect(line, &QLineEdit::textChanged, [](const QString &t) {
        logj({{"ev", "line"}, {"text", t}});
    });
    QObject::connect(slider, &QSlider::valueChanged, [](int v) {
        logj({{"ev", "slider"}, {"value", v}});
    });
    QObject::connect(text, &QTextEdit::selectionChanged, [text] {
        logj({{"ev", "selection"}, {"text", text->textCursor().selectedText()}});
    });
    QObject::connect(text, &QTextEdit::textChanged, [text] {
        logj({{"ev", "textedit"}, {"text", text->toPlainText()}});
    });
    QObject::connect(&app, &QGuiApplication::focusWindowChanged, [](QWindow *w) {
        logj({{"ev", "focus_window"}, {"title", w ? w->title() : QString()}});
    });
    win.resize(600, 500);
    win.show();
    QTimer::singleShot(500, [&] {
        auto geo = [&](QWidget *w) {
            const QPoint p = w->mapTo(&win, QPoint(0, 0));
            return QJsonObject{{"x", p.x()}, {"y", p.y()}, {"w", w->width()}, {"h", w->height()}};
        };
        logj({{"ev", "layout"}, {"platform", QGuiApplication::platformName()}, {"dpr", win.devicePixelRatioF()},
              {"menubar", geo(win.menuBar())}, {"line", geo(line)}, {"slider", geo(slider)}, {"text", geo(text)}, {"pad", geo(pad)},
              {"window", QJsonObject{{"w", win.width()}, {"h", win.height()}}}, {"nativeMenuBar", win.menuBar()->isNativeMenuBar()},
              {"menubarVisible", win.menuBar()->isVisible()}});
    });
    logj({{"ev", "started"}, {"pid", int(QCoreApplication::applicationPid())}});
    return app.exec();
}
