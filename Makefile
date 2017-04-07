# the following values must be changed
SPEC := ReLVHDoISCSISR.spec
VENDOR_CODE := cloudops
VENDOR_NAME := CloudOps Inc.
LABEL = $(DRIVER_NAME)
TEXT := LVHDoISCSISR with SR resigning
UUID := d7c435bd-90e6-43d1-b81f-37785ac1f347

# versioning of pack
PACK_VERSION = $(XENSERVER_VERSION)
PACK_BUILD = $(XENSERVER_BUILD)
BASE_REQUIRES = product-version = $(XENSERVER_VERSION)

# key to sign update with
GPG_KEY_FILE := sahmed_pub.crt

# versioning of kernel module RPMs
RPM_VERSION := 1.0
RPM_RELEASE := 1

# no changes below here
RPMDIR := $(shell rpm --eval %{_rpmdir})
RPMSOURCES := $(shell rpm --eval %{_sourcedir})
ARCH := $(shell uname -p)
XENSERVER_VERSION := $(shell . /etc/os-release ; IFS=- ; set -- $$VERSION ; echo $$1)
XENSERVER_BUILD := $(shell . /etc/os-release ; IFS=- ; set -- $$VERSION ; echo $$2)
KERNEL_VERSION := $(shell uname -r)
DRIVER_NAME := $(shell sed -ne 's/^Name: *//p' $(SPEC))
ISO := $(DRIVER_NAME).iso
GPG_UID = $(shell gpg --batch -k --with-colons 2>/dev/null | awk -F: '$$1=="uid" {print $$10}')

RPM := $(DRIVER_NAME)-$(RPM_VERSION)-$(RPM_RELEASE)
RPM_FILE := $(RPM:%=$(RPMDIR)/$(ARCH)/%.$(ARCH).rpm)
SOURCE_TARBALL := $(RPMSOURCES)/$(DRIVER_NAME)-$(RPM_VERSION).tar.gz


$(ISO): $(RPM_FILE) $(GPG_KEY_FILE)
	sed -e 's/@DRIVER@/$(DRIVER_NAME)/g' groups.xml >/tmp/groups.xml
	build-update --uuid $(UUID) --label "$(LABEL)" --version $(PACK_VERSION) \
		--description "$(TEXT)" --base-requires "$(BASE_REQUIRES)" --groupfile /tmp/groups.xml \
		--key "$(GPG_UID)" --keyfile $(GPG_KEY_FILE) \
		-o $@ $(RPM_FILE)

$(RPM_FILE): $(SPEC) $(SOURCE_TARBALL)
	rpmbuild -bb --define "kernel_version $(KERNEL_VERSION)" --define "version $(RPM_VERSION)" --define "release $(RPM_RELEASE)" $<

$(SOURCE_TARBALL):
	mkdir -p $(@D)
	tar zcvf $@ $(DRIVER_NAME)-$(RPM_VERSION)

$(GPG_KEY_FILE):
	generate-test-key $@

clean:
	rm -f $(ISO)
