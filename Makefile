# the following values must be changed
SPEC := ReLVHDoISCSISR.spec
VENDOR_CODE := cloudops
VENDOR_NAME := CloudOps Inc.
LABEL = $(PACKAGE_NAME)
TEXT := LVHDoISCSISR with SR resigning

# versioning of pack
PACK_VERSION = $(XENSERVER_VERSION)
PACK_BUILD = $(XENSERVER_BUILD)

# versioning of RPM
RPM_VERSION := 1.0
RPM_RELEASE := 1

# no changes below here
RPMDIR := $(shell rpm --eval %{_rpmdir})
RPMSOURCES := $(shell rpm --eval %{_sourcedir})
ARCH := $(shell uname -p)
XENSERVER_VERSION := $(shell set -- `tr '-' ' ' </etc/redhat-release` && echo $$4)
XENSERVER_BUILD := $(shell set -- `tr '-' ' ' </etc/redhat-release` && echo $$5)
PACKAGE_NAME := $(shell sed -ne 's/^Name: *//p' $(SPEC))
ISO := $(PACKAGE_NAME).iso
ISO_MD5 := $(ISO).md5
TAR := $(PACKAGE_NAME).tar.gz
METADATA_MD5 := $(PACKAGE_NAME).metadata.md5

RPMS := $(PACKAGE_NAME)-$(RPM_VERSION)-$(RPM_RELEASE)
RPM_FILES := $(patsubst %, $(RPMDIR)/$(ARCH)/%.$(ARCH).rpm, $(RPMS))


build-iso: build-rpms
	python setup.py --output=$(dir $(ISO)) --iso --vendor-code=$(VENDOR_CODE) "--vendor-name=$(VENDOR_NAME)" --label=$(LABEL) "--text=$(TEXT)" --version=$(PACK_VERSION) --build=$(PACK_BUILD) $(RPM_FILES)

build-tarball: build-rpms
	python setup.py --output=$(dir $(ISO)) --tar --vendor-code=$(VENDOR_CODE) "--vendor-name=$(VENDOR_NAME)" --label=$(LABEL) "--text=$(TEXT)" --version=$(PACK_VERSION) --build=$(PACK_BUILD) $(RPM_FILES)

build-rpms: build-srctarballs
	rpmbuild -bb --define "version $(RPM_VERSION)" --define "release $(RPM_RELEASE)" $(SPEC)

build-srctarballs:
	mkdir -p $(RPMSOURCES)
	tar zcvf $(RPMSOURCES)/$(PACKAGE_NAME)-$(RPM_VERSION).tar.gz $(PACKAGE_NAME)-$(RPM_VERSION)

clean:
	rm -f $(ISO) $(ISO_MD5) $(TAR) $(METADATA_MD5)
