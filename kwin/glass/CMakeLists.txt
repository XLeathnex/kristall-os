# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.25)
project(kristall_glass VERSION 1.0.0 LANGUAGES CXX)

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

find_package(Qt6 6.11 REQUIRED COMPONENTS Core CorePrivate Gui Network DBus Quick Widgets)
find_package(KF6Config REQUIRED)
find_package(KF6CoreAddons REQUIRED)
find_package(KDecoration3 REQUIRED)
find_package(KWin REQUIRED)

message(STATUS "Building kristall-glass against KWin ${KWin_VERSION}")
if(KWin_VERSION VERSION_LESS 6.8 OR KWin_VERSION VERSION_GREATER_EQUAL 6.9)
    message(WARNING "kristall-glass targets KWin 6.8.x; found ${KWin_VERSION}. The internal API may differ.")
endif()

option(KRISTALL_GLASS_TEST_BROKEN "Build a deliberately unloadable plugin (test of load-failure handling)" OFF)

set(KRISTALL_PREFIX "${CMAKE_INSTALL_PREFIX}" CACHE PATH "Prefix the defaults file lives under")

add_library(kristall_glass MODULE
    src/main.cpp
    src/glasseffect.cpp
    src/glassrenderer.cpp
    src/glassserver.cpp
    src/glassshape.cpp
    src/glasssettings.cpp
    src/surfacetracker.cpp
    src/crashguard.cpp
    src/glass.qrc

)
target_compile_definitions(kristall_glass PRIVATE
    KRISTALL_DEFAULTS_FILE="${KRISTALL_PREFIX}/share/kristall/defaults/settings.json"
    QT_NO_KEYWORDS_DISABLED=1)
if(KRISTALL_GLASS_TEST_BROKEN)
    target_compile_definitions(kristall_glass PRIVATE KRISTALL_GLASS_TEST_BROKEN=1)
endif()
target_compile_options(kristall_glass PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(kristall_glass PRIVATE
    KWin::kwin
    Qt6::Core Qt6::CorePrivate Qt6::Gui Qt6::Network Qt6::DBus
    KF6::ConfigCore KF6::CoreAddons
    KDecoration3::KDecoration
)
set_target_properties(kristall_glass PROPERTIES PREFIX "")
# the effect factory macros contain Q_PLUGIN_METADATA; moc must see them to embed metadata.json
set_property(TARGET kristall_glass APPEND PROPERTY AUTOMOC_MACRO_NAMES
    KWIN_EFFECT_FACTORY KWIN_EFFECT_FACTORY_SUPPORTED KWIN_EFFECT_FACTORY_ENABLED KWIN_EFFECT_FACTORY_SUPPORTED_ENABLED)
install(TARGETS kristall_glass DESTINATION ${KDE_INSTALL_PLUGINDIR}/kwin/effects/plugins)
install(PROGRAMS tools/kristall-glass-ctl DESTINATION ${KDE_INSTALL_BINDIR})
