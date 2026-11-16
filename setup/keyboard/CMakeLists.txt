# SPDX-License-Identifier: GPL-3.0-or-later
# kristall-keyboard: KWin plugin that makes the key beside the space bar act as Command (Mac
# shortcuts on a PC keyboard), per application, inside the compositor. See setup/README.md.
cmake_minimum_required(VERSION 3.25)
project(kristall_keyboard VERSION 1.0.0 LANGUAGES CXX)

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

find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui GuiPrivate DBus Quick Widgets)
find_package(KF6Config REQUIRED)
find_package(KF6CoreAddons REQUIRED)
find_package(KWin REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(XKB REQUIRED IMPORTED_TARGET xkbcommon)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-server)

message(STATUS "Building kristall-keyboard against KWin ${KWin_VERSION}")
if(KWin_VERSION VERSION_LESS 6.8 OR KWin_VERSION VERSION_GREATER_EQUAL 6.9)
    message(WARNING "kristall-keyboard targets KWin 6.8.x; found ${KWin_VERSION}. The internal API may differ.")
endif()

option(KRISTALL_KEYBOARD_TEST_BROKEN "Build a plugin whose initialisation fails (test of the fail-safe)" OFF)

add_library(kristall_keyboard MODULE
    src/main.cpp
    src/remapper.cpp
    src/keysettings.cpp
)
target_compile_definitions(kristall_keyboard PRIVATE QT_NO_CAST_FROM_ASCII)
if(KRISTALL_KEYBOARD_TEST_BROKEN)
    target_compile_definitions(kristall_keyboard PRIVATE KRISTALL_KEYBOARD_TEST_BROKEN=1)
endif()
target_compile_options(kristall_keyboard PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(kristall_keyboard PRIVATE
    KWin::kwin Qt6::Core Qt6::Gui Qt6::DBus KF6::ConfigCore KF6::CoreAddons PkgConfig::XKB PkgConfig::WAYLAND)
set_target_properties(kristall_keyboard PROPERTIES PREFIX "")
install(TARGETS kristall_keyboard DESTINATION ${KDE_INSTALL_PLUGINDIR}/kwin/plugins)
