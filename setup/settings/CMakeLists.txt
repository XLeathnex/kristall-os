# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall's pages inside KDE System Settings: a QML backend module (org.kristall.settings) and
# one System Settings module (KCM) per page. See setup/README.md.
cmake_minimum_required(VERSION 3.25)
project(kristall_settings VERSION 1.0.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

find_package(ECM 6.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(ECMQmlModule)

find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui Qml Quick DBus)
find_package(KF6KCMUtils REQUIRED)
find_package(KF6CoreAddons REQUIRED)

# ---- the backend: org.kristall.settings ------------------------------------------------------
ecm_add_qml_module(kristallsettings URI org.kristall.settings VERSION 1.0 GENERATE_PLUGIN_SOURCE DEPENDENCIES QtQuick)
target_sources(kristallsettings PRIVATE backend/backend.cpp backend/backend.h)
target_include_directories(kristallsettings PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/backend)
set_source_files_properties(qml/Lang.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
ecm_target_qml_sources(kristallsettings SOURCES qml/Lang.qml qml/Note.qml qml/Crystal.qml)
target_link_libraries(kristallsettings PRIVATE Qt6::Core Qt6::Qml Qt6::Quick Qt6::DBus)
target_compile_options(kristallsettings PRIVATE -Wall -Wextra)
ecm_finalize_qml_module(kristallsettings DESTINATION ${KDE_INSTALL_QMLDIR})

# ---- one KCM per page -------------------------------------------------------------------------
set(KCMS appearance dock notifications assistant energy keyboard update about)
foreach(page ${KCMS})
    set(KCM kcm_kristall_${page})
    set(JSON ${CMAKE_CURRENT_SOURCE_DIR}/kcms/${page}/${KCM}.json)
    configure_file(kcm/plugin.cpp.in ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.cpp @ONLY)
    add_library(${KCM} MODULE ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.cpp kcm/kristallkcm.h)
    target_include_directories(${KCM} PRIVATE kcm)
    target_link_libraries(${KCM} PRIVATE KF6::KCMUtilsQuick KF6::CoreAddons Qt6::Qml)
    set_target_properties(${KCM} PROPERTIES PREFIX "" AUTOMOC_MOC_OPTIONS "-I${CMAKE_CURRENT_SOURCE_DIR}/kcms/${page}")
    qt_add_resources(${KCM} ${KCM}_ui PREFIX /kcm/${KCM} BASE kcms/${page} FILES kcms/${page}/main.qml)
    install(TARGETS ${KCM} DESTINATION ${KDE_INSTALL_PLUGINDIR}/plasma/kcms/systemsettings)
    # a desktop entry, so the page can be found by name and started directly (systemsettings kcm_…)
    add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.desktop
        COMMAND KF6::kcmdesktopfilegenerator ${JSON} ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.desktop DEPENDS ${JSON})
    add_custom_target(${KCM}-desktop ALL DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.desktop)
    install(FILES ${CMAKE_CURRENT_BINARY_DIR}/${KCM}.desktop DESTINATION ${KDE_INSTALL_APPDIR})
endforeach()

install(FILES data/settings-kristall-general.desktop DESTINATION ${KDE_INSTALL_DATADIR}/systemsettings/categories)
