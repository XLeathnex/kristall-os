# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall window decoration for KWin 6.8 (KDecoration3). Built in the OS image against the
# KDecoration it ships with; KWin falls back to Breeze if this plugin is missing or fails to load.
cmake_minimum_required(VERSION 3.22)
project(kristall-decoration LANGUAGES CXX)

find_package(ECM 6.0 REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.6 REQUIRED COMPONENTS Core Gui)
find_package(KF6 REQUIRED COMPONENTS CoreAddons)
find_package(KDecoration3 REQUIRED)

set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_library(kristalldecoration MODULE decoration.cpp button.cpp guard.cpp shadow.cpp)
set_target_properties(kristalldecoration PROPERTIES OUTPUT_NAME org.kristall.decoration PREFIX "")
target_compile_options(kristalldecoration PRIVATE -Wall -Wextra)
target_link_libraries(kristalldecoration PRIVATE Qt6::Core Qt6::Gui KF6::CoreAddons KDecoration3::KDecoration)

install(TARGETS kristalldecoration DESTINATION ${KDE_INSTALL_PLUGINDIR}/org.kde.kdecoration3)
