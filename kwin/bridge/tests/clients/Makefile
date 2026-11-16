# SPDX-License-Identifier: GPL-3.0-or-later
# Test clients for kristall-bridge (built inside the kristall-devenv container).
OUT ?= /tmp/kristall-bridge-build/bin
WP := $(shell pkg-config --variable=pkgdatadir wayland-protocols)
PWP := /usr/share/plasma-wayland-protocols
GEN := $(OUT)/gen
CFLAGS += -O2 -Wall -Wno-unused-parameter -I$(GEN)

all: $(OUT)/wlprobe $(OUT)/owner $(OUT)/qtprobe

$(GEN)/%-client-protocol.h: | $(GEN)
	@true

$(GEN):
	mkdir -p $(GEN)

define proto
$(GEN)/$(1)-client-protocol.h $(GEN)/$(1)-protocol.c: $(2) | $(GEN)
	wayland-scanner client-header $(2) $(GEN)/$(1)-client-protocol.h
	wayland-scanner private-code $(2) $(GEN)/$(1)-protocol.c
endef
$(eval $(call proto,xdg-shell,$(WP)/stable/xdg-shell/xdg-shell.xml))
$(eval $(call proto,text-input-unstable-v3,$(WP)/unstable/text-input/text-input-unstable-v3.xml))
$(eval $(call proto,xdg-decoration-unstable-v1,$(WP)/unstable/xdg-decoration/xdg-decoration-unstable-v1.xml))
$(eval $(call proto,fake-input,$(PWP)/fake-input.xml))

WLPROBE_GEN := xdg-shell text-input-unstable-v3 xdg-decoration-unstable-v1
$(OUT)/wlprobe: wlprobe.c $(foreach p,$(WLPROBE_GEN),$(GEN)/$(p)-client-protocol.h $(GEN)/$(p)-protocol.c)
	$(CC) $(CFLAGS) -o $@ wlprobe.c $(foreach p,$(WLPROBE_GEN),$(GEN)/$(p)-protocol.c) $(shell pkg-config --cflags --libs wayland-client xkbcommon)

$(OUT)/owner: owner.c $(GEN)/fake-input-client-protocol.h $(GEN)/fake-input-protocol.c
	$(CC) $(CFLAGS) -o $@ owner.c $(GEN)/fake-input-protocol.c $(shell pkg-config --cflags --libs wayland-client)

$(OUT)/qtprobe: qtprobe.cpp
	$(CXX) -O2 -std=c++20 -fPIC -o $@ qtprobe.cpp $(shell pkg-config --cflags --libs Qt6Widgets)
