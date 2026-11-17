# SPDX-License-Identifier: GPL-3.0-or-later
# kristall-bridge: KWin plugin exposing windows, agent input and screenshots over a Unix socket.
cmake_minimum_required(VERSION 3.25)
project(kristall_bridge VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

find_package(ECM 6.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)

find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui GuiPrivate Network Concurrent DBus Quick Widgets)
find_package(KF6Config REQUIRED)
find_package(KF6CoreAddons REQUIRED)
find_package(KDecoration3 REQUIRED)
find_package(KWin REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-client wayland-server)
pkg_check_modules(XKB REQUIRED IMPORTED_TARGET xkbcommon)
pkg_check_modules(XCB REQUIRED IMPORTED_TARGET xcb) # X round trips to Xwayland (ordered keys for X11 windows)
pkg_check_modules(SYSTEMD IMPORTED_TARGET libsystemd)
pkg_get_variable(WAYLAND_PROTOCOLS_DIR wayland-protocols pkgdatadir)
find_program(WAYLAND_SCANNER wayland-scanner REQUIRED)

message(STATUS "Building kristall-bridge against KWin ${KWin_VERSION}")
if(KWin_VERSION VERSION_LESS 6.8 OR KWin_VERSION VERSION_GREATER_EQUAL 6.9)
    message(WARNING "kristall-bridge targets KWin 6.8.x; found ${KWin_VERSION}. The internal API may differ.")
endif()

# Plasma's window-management protocol ships with plasma-wayland-protocols (build dependency only).
find_file(PLASMA_WM_XML plasma-window-management.xml
    PATHS /usr/share/plasma-wayland-protocols ${CMAKE_INSTALL_PREFIX}/share/plasma-wayland-protocols REQUIRED)

# Client-side code for the bridge's in-process helper connection (see src/helperclient.cpp).
set(PROTO_OUT ${CMAKE_CURRENT_BINARY_DIR}/protocols)
file(MAKE_DIRECTORY ${PROTO_OUT})
set(PROTO_SOURCES)
function(kristall_protocol name xml)
    add_custom_command(
        OUTPUT ${PROTO_OUT}/${name}-client-protocol.h ${PROTO_OUT}/${name}-protocol.c
        COMMAND ${WAYLAND_SCANNER} client-header ${xml} ${PROTO_OUT}/${name}-client-protocol.h
        COMMAND ${WAYLAND_SCANNER} private-code ${xml} ${PROTO_OUT}/${name}-protocol.c
        DEPENDS ${xml} VERBATIM)
    set(PROTO_SOURCES ${PROTO_SOURCES} ${PROTO_OUT}/${name}-client-protocol.h ${PROTO_OUT}/${name}-protocol.c PARENT_SCOPE)
endfunction()
kristall_protocol(xdg-shell ${WAYLAND_PROTOCOLS_DIR}/stable/xdg-shell/xdg-shell.xml)
kristall_protocol(wlr-layer-shell-unstable-v1 ${CMAKE_CURRENT_SOURCE_DIR}/protocols/wlr-layer-shell-unstable-v1.xml)
kristall_protocol(plasma-window-management ${PLASMA_WM_XML})
kristall_protocol(ext-data-control-v1 ${WAYLAND_PROTOCOLS_DIR}/staging/ext-data-control/ext-data-control-v1.xml)

option(KRISTALL_BRIDGE_TEST_BROKEN "Build a plugin whose initialisation fails (test of fail-soft handling)" OFF)

add_library(kristall_bridge MODULE
    src/main.cpp
    src/bridgeplugin.cpp
    src/server.cpp
    src/windows.cpp
    src/agent.cpp
    src/agentkeyboard.cpp
    src/screenshot.cpp
    src/screenshotlayer.cpp
    src/helperclient.cpp
    src/util.cpp
    ${PROTO_SOURCES}
)
target_include_directories(kristall_bridge PRIVATE ${PROTO_OUT})
target_compile_definitions(kristall_bridge PRIVATE QT_NO_KEYWORDS_DISABLED=1 QT_NO_CAST_FROM_ASCII)
if(KRISTALL_BRIDGE_TEST_BROKEN)
    target_compile_definitions(kristall_bridge PRIVATE KRISTALL_BRIDGE_TEST_BROKEN=1)
endif()
if(SYSTEMD_FOUND)
    target_compile_definitions(kristall_bridge PRIVATE KRISTALL_HAVE_SYSTEMD=1)
    target_link_libraries(kristall_bridge PRIVATE PkgConfig::SYSTEMD)
endif()
target_compile_options(kristall_bridge PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(kristall_bridge PRIVATE
    KWin::kwin
    Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::Network Qt6::Concurrent Qt6::DBus
    KF6::ConfigCore KF6::CoreAddons
    KDecoration3::KDecoration
    PkgConfig::WAYLAND PkgConfig::XKB PkgConfig::XCB
)
set_target_properties(kristall_bridge PROPERTIES PREFIX "")
install(TARGETS kristall_bridge DESTINATION ${KDE_INSTALL_PLUGINDIR}/kwin/plugins)
