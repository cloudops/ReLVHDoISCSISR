#!/usr/env python

import argparse
import getpass
import glob
import os
import os.path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.dom.minidom

from pkg_resources import resource_filename
from update_package.common import *


def calc_install_size(rpms):
    """
    Calculate the installation-size
    """
    size = 0
    for rpm in rpms:
        out = subprocess.check_output(['rpm', '-q', '--qf', '%{size}', '-p',
                                       rpm])
        size += int(out)
    return size


def create_update_doc(filename, uuid, label, version, description, after_apply,
                       keyfile, control_pkg, size, rollups=None):
    """
    Create XML document describing update
    """
    dom = xml.dom.minidom.getDOMImplementation()
    doc = dom.createDocument(None, "update", None)
    top = doc.documentElement
    top.setAttribute('name-label', label)
    top.setAttribute('version', version)
    top.setAttribute('uuid', uuid)
    top.setAttribute('installation-size', str(size))
    if after_apply:
        top.setAttribute('after-apply-guidance', after_apply)
    if keyfile:
        top.setAttribute('key', os.path.basename(keyfile))
    if control_pkg:
        top.setAttribute('control', control_pkg)
    desc = doc.createElement("name-description")
    desc.appendChild(doc.createTextNode(description))
    top.appendChild(desc)
    if rollups:
        for r_uuid in rollups:
            rollup_elem = doc.createElement('rollsup')
            rollup_elem.setAttribute('name-label', label)
            rollup_elem.setAttribute('uuid', r_uuid)
    	    top.appendChild(rollup_elem)

    with open(filename, "w") as fileh:
        top.writexml(fileh, indent="  ", newl='\n')


def build_update_rpm(work_dir, uuid, label, version, description, rpms,
                     after_apply):
    """
    Create update RPM to deploy update payload
    """
    # create files that are included by the spec file
    with open(os.path.join(work_dir, "description"), "w") as fileh:
        fileh.write(description + '\n')
    with open(os.path.join(work_dir, "requires"), "w") as fileh:
        for rpm in rpms:
            rpmdep = subprocess.check_output(['rpm', '-q', '--qf',
                                              '%{name} >= %{version}-%{release}', '-p',
                                              rpm])
            fileh.write("Requires: %s\n" % rpmdep)
    if isinstance(after_apply, basestring) and 'restartHost' in after_apply:
        with open(os.path.join(work_dir, "posttrans"), "w") as fileh:
            fileh.write("echo %s >>/run/reboot-required.hfxs\n" % uuid)

    subprocess.check_output(['rpmbuild', '--define', '_topdir %s' % work_dir,
                             '--define', 'label %s' % label,
                             '--define', 'version %s' % version,
                             '--define', 'uuid %s' % uuid,
                             '-bb', resource_filename('update_package',
                                                      'update.spec')])
def write_rollup_files(work_dir, uuid, label, version, description, rollups):
    for rollup_uuid in rollups:
        with open(os.path.join(work_dir, "posttrans"), "a") as fileh:
    	    dom = xml.dom.minidom.getDOMImplementation()
	    doc = dom.createDocument(None, "update", None)
            top = doc.documentElement
            top.setAttribute('name-label', label)
            top.setAttribute('version', version)
            top.setAttribute('uuid', rollup_uuid)
            top.setAttribute('installation-size', "0")

    	    desc = doc.createElement('name-description')
	    desc.appendChild(doc.createTextNode(description))
	    top.appendChild(desc)

            rollup_elem = doc.createElement('rolled-up-by')
	    rollup_elem.setAttribute('name-label', label)
	    rollup_elem.setAttribute('uuid', uuid)
	    top.appendChild(rollup_elem)

            xml_str = top.toprettyxml(indent="  ", newl='\n')
	    update_file = os.path.join("/", "var", "update", "applied", rollup_uuid)

            fileh.write("cat >%s <<EOF\n%s\nEOF\n\n" % (update_file, xml_str))

def interpreter(script):
    """
    Determine the interpreter used by a script
    """
    with open(script) as fileh:
        line = fileh.readline().rstrip()
    if line.startswith('#!'):
        line = line[2:].strip()
    args = line.split()
    if args[0].endswith('/env'):
        return subprocess.check_output(['which', args[1]])
    else:
        return args[0]


def build_control_rpm(work_dir, uuid, label, version, base_requires, precheck,
                      remove):
    """
    Create control RPM to deploy scripts
    """
    # create source tarball
    interp = '/bin/sh'
    ctrl_source = os.path.join(work_dir, "SOURCES",
                               "control-%s-source.tar" % label)
    with tarfile.open(ctrl_source, "w") as tar:
        if precheck:
            tar.add(precheck, arcname="precheck")
            shutil.copyfile(precheck, os.path.join(work_dir, "precheck"))
            interp = interpreter(precheck)
        if remove:
            tar.add(remove, arcname="remove")

    # create script list include by the spec file
    with open(os.path.join(work_dir, "control-files"), "w") as fileh:
        if precheck:
            fileh.write("/var/update/%s/precheck\n" % uuid)
        if remove:
            fileh.write("/var/update/%s/remove\n" % uuid)

    subprocess.check_output(['rpmbuild', '--define', '_topdir %s' % work_dir,
                             '--define', 'label %s' % label,
                             '--define', 'version %s' % version,
                             '--define', 'uuid %s' % uuid,
                             '--define', 'requires %s' % base_requires,
                             '--define', 'precheck_interp ' + interp,
                             '-bb', resource_filename('update_package',
                                                      'control.spec')])
    return "control-" + label


def copy_packages(work_dir, rpms):
    """
    Copy payload and any additional RPMS
    """
    pkg_dir = os.path.join(work_dir, 'root/Packages')
    os.mkdir(pkg_dir)
    extra_pkgs = glob.glob(os.path.join(work_dir, 'RPMS/noarch/*.rpm'))
    for rpm in rpms + extra_pkgs:
        shutil.copy2(rpm, pkg_dir)


def group_file(work_dir, label):
    """
    Create a standard group file
    """
    groupfile = os.path.join(work_dir, "groups.xml")
    with open(groupfile, "w") as fileh:
        fileh.write("""<!DOCTYPE comps PUBLIC "-//Red Hat, Inc.//DTD Comps info//EN" "comps.dtd">
<comps>
  <group>
   <id>update</id>
   <default>False</default>
   <uservisible>True</uservisible>
   <name>%(label)s</name>
   <description></description>
    <packagelist>
      <packagereq type="mandatory">update-%(label)s</packagereq>
    </packagelist>
  </group>
</comps>
""" % {'label': label})
    return groupfile


def check_uuid(uuid):
    """
    Validate UUID
    """
    if re.match(r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$',
                uuid):
        return uuid
    sys.exit("%s: invalid UUID: %s" % (sys.argv[0], uuid))


def check_label(label):
    """
    Validate update label
    """
    if re.match(r'[\w-]+$', label):
        return label
    sys.exit("%s: invalid label: %s" % (sys.argv[0], label))


def check_guidance(guidance):
    """
    Validate after-apply guidance
    """
    valid = ("restartXAPI", "restartHost", "restartPV", "restartHVM")
    for g in guidance.split(','):
        if g not in valid:
            sys.exit("%s: invalid guidance: %s" % (sys.argv[0], g))
    return guidance


def parse_args_or_exit(argv=None):
    """
    Parse command line options
    """
    parser = argparse.ArgumentParser(description="Build update media")
    parser.add_argument("rpms", metavar="RPM", nargs="+",
                        help="Packages to include")
    parser.add_argument("--uuid", type=check_uuid, required=True,
                        help="Update unique identifier")
    parser.add_argument("-l", "--label", type=check_label, required=True,
                        help="Update textual label")
    parser.add_argument("-v", "--version", required=True,
                        help="Update version")
    parser.add_argument("-d", "--description", required=True,
                        help="Update description")
    parser.add_argument("-o", "--output", metavar="ISO", required=True,
                        help="Output ISO file")
    parser.add_argument("-k", "--key", metavar="UID", default=None,
                        help="UID of gpg key")
    parser.add_argument("--keyfile", default=None,
                        help="File name of gpg key")
    parser.add_argument("--base-requires", default=None,
                        help="Product version dependency")
    parser.add_argument("--after-apply", type=check_guidance, default=None,
                        help="Post apply guidance")
    parser.add_argument("--precheck", default=None,
                        help="Precheck script")
    parser.add_argument("--remove", default=None,
                        help="Uninstall script")
    parser.add_argument('--no-passphrase', action='store_false',
                        dest="prompt_pass", help="Disable passphrase prompt")
    parser.add_argument('--rollups', default=None,
                        help="Comma-seperated list of UUIDs of previous versions")
    parser.add_argument("--groupfile", default=None,
                        help="Group information")

    return parser.parse_args(argv)


def main(argv):
    """
    Create and sign constituent parts then assemble ISO
    """
    args = parse_args_or_exit(argv)
    passphrase = None
    control_pkg = None
    if args.key and args.prompt_pass:
        passphrase = getpass.getpass("Enter passphrase for %s: " % args.key)
    work_dir = tempfile.mkdtemp(prefix='build-update-')
    try:
        os.mkdir(os.path.join(work_dir, 'root'))
        os.mkdir(os.path.join(work_dir, 'SOURCES'))
        has_control = args.base_requires or args.precheck or args.remove
        if has_control:
            control_pkg = build_control_rpm(work_dir, args.uuid, args.label,
                                            args.version, args.base_requires,
                                            args.precheck, args.remove)
        rollups = []
        if args.rollups:
		rollups = args.rollups.split(",")

        size = calc_install_size(args.rpms)
        create_update_doc(os.path.join(work_dir, 'root/update.xml'), args.uuid,
                          args.label, args.version, args.description,
                          args.after_apply, args.keyfile, control_pkg, size, rollups)

        write_rollup_files(work_dir, args.uuid, args.label, args.version, args.description, rollups)

        build_update_rpm(work_dir, args.uuid, args.label, args.version,
                         args.description, args.rpms, args.after_apply)
        copy_packages(work_dir, args.rpms)
        if args.key:
            sign_update_doc(work_dir, args.key, passphrase)
            packages = glob.glob(os.path.join(work_dir, "root/Packages/*.rpm"))
            sign_packages(work_dir, args.key, passphrase, packages)
        if args.groupfile:
            groupfile = args.groupfile
        else:
            groupfile = group_file(work_dir, args.label)
        create_repo(work_dir, args.key, passphrase, groupfile)
        build_iso(work_dir, args.output, args.uuid, args.label)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _main():
    """
    Entry point for setuptools CLI wrapper
    """
    main(sys.argv[1:])


# Entry point when run directly
if __name__ == "__main__":
    _main()
