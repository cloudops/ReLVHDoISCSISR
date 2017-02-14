#!/usr/bin/python
#
# Copyright (C) CloudOps Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# VDI-per-LUN SR implementation
#
import os
import SR, VDI, SRCommand, util
import lvhdutil
import vhdutil
import iscsilib
import xs_errors
import xml.dom.minidom
from lock import Lock

CAPABILITIES = ["SR_PROBE", "VDI_CREATE", "VDI_DELETE", "VDI_ATTACH",
                "VDI_DETACH", "VDI_RESIZE", "VDI_INTRODUCE"]

CONFIGURATION = [['target', 'IP address or hostname of the iSCSI target (required)'], \
                 ['targetIQNs', 'The list of target IQNs to add as VDIs (optional)'], \
                 ['chapuser', 'The username to be used during CHAP authentication (optional)'], \
                 ['chappassword', 'The password to be used during CHAP authentication (optional)'], \
                 ['incoming_chapuser',
                  'The incoming username to be used during bi-directional CHAP authentication (optional)'], \
                 ['incoming_chappassword',
                  'The incoming password to be used during bi-directional CHAP authentication (optional)'], \
                 ['port', 'The network port number on which to query the target (optional)'], \
                 ['multihomed',
                  'Enable multi-homing to this target, true or false (optional, defaults to same value as host.other_config:multipathing)'],
                 ['force_tapdisk', 'Force use of tapdisk, true or false (optional, defaults to false)'],
                 ]

DRIVER_INFO = {
    'name': 'VDILUNSR',
    'description': 'provides a LUN-per-VDI with single SR',
    'vendor': 'Cloudops Inc',
    'copyright': '(C) 2016 Cloudops Inc',
    'driver_version': '1.0',
    'required_api_version': '1.0',
    'capabilities': CAPABILITIES,
    'configuration': CONFIGURATION
}

INITIATORNAME_FILE = '/etc/iscsi/initiatorname.iscsi'
SECTOR_SHIFT = 9
DEFAULT_PORT = 3260
# 2^16 Max port number value
MAXPORT = 65535
MAX_TIMEOUT = 15
MAX_LUNID_TIMEOUT = 60
ISCSI_PROCNAME = "iscsi_tcp"
SR_TYPE_VDILUN = "vdilun"
VHD_COOKIE = "conectix"

def log(message):
    util.SMlog("#"* 40 + str(message) + "#"*20)

def _checkTGT(tgtIQN, tgt=''):
    if not is_iscsi_daemon_running():
        return False
    iscsi_path = "/dev/iscsi/" + tgtIQN
    return os.path.isdir(iscsi_path)

def is_iscsi_daemon_running():
    cmd = ["/sbin/pidof", "-s", "/sbin/iscsid"]
    (rc,stdout,stderr) = util.doexec(cmd)
    return (rc==0)

def iscsi_login(portal, target, username, password, username_in="", password_in="",
          multipath=False):
    if username != "" and password != "":
        iscsilib.set_chap_settings(portal, target, username, password, username_in, password_in)
    iscsilib.set_replacement_tmo(portal,target, multipath)
    cmd = ["iscsiadm", "-m", "node", "-p", portal, "-T", target, "-l"]
    failuremessage = "Failed to login to target."
    try:
        (stdout,stderr) = iscsilib.exn_on_failure(cmd,failuremessage)
        iscsilib.wait_for_devs(target, portal)
    except:
        raise xs_errors.XenError('ISCSILogin')



class VDILUNSR(SR.SR):
    """VHDoISCSI storage repository"""

    def handles(type):
        if type == SR_TYPE_VDILUN:
            return True
        return False

    handles = staticmethod(handles)

    def load(self, sr_uuid):

        log("Calling vdilunsr load")

        if not self.dconf.has_key('target'):
            raise xs_errors.XenError('ConfigServerMissing')

        try:
            if not self.dconf.has_key('localIQN'):
                self.localIQN = self.session.xenapi.host.get_other_config(self.host_ref)['iscsi_iqn']
                assert len(self.localIQN)
            else:
                self.localIQN = self.dconf['localIQN']
                assert len(self.localIQN)
        except:
            raise xs_errors.XenError('ConfigISCSIIQNMissing')

        try:
            self.target = util._convertDNS(self.dconf['target'].split(',')[0])
        except:
            raise xs_errors.XenError('DNSError')

        self.port = DEFAULT_PORT

        if self.dconf.has_key('port') and self.dconf['port']:
            try:
                self.port = long(self.dconf['port'])
            except:
                raise xs_errors.XenError('ISCSIPort')

        if self.port > MAXPORT or self.port < 1:
            raise xs_errors.XenError('ISCSIPort')

        try:
            if not self.dconf.has_key('localIQN'):
                self.localIQN = self.session.xenapi.host.get_other_config(self.host_ref)['iscsi_iqn']
            else:
                self.localIQN = self.dconf['localIQN']
        except:
            raise xs_errors.XenError('ConfigISCSIIQNMissing')


        if self.dconf.has_key('port') and self.dconf['port']:
            try:
                self.port = long(self.dconf['port'])
            except:
                raise xs_errors.XenError('ISCSIPort')
        if self.port > MAXPORT or self.port < 1:
            raise xs_errors.XenError('ISCSIPort')


        self.isMaster = False
        if self.dconf.has_key('SRmaster') and self.dconf['SRmaster'] == 'true':
            self.isMaster = True

        self.lock = Lock(vhdutil.LOCK_TYPE_SR, self.uuid)
        self.uuid = sr_uuid

        self.sm_config = self.session.xenapi.SR.get_sm_config(self.sr_ref)

        vdis_in_sr = self.session.xenapi.SR.get_VDIs(self.sr_ref)

        log(vdis_in_sr)
        for vdi_ref in vdis_in_sr:
            vdi = self.session.xenapi.VDI.get_record(vdi_ref)
            self.vdis[vdi['uuid']] = VDILUN(self, vdi['uuid'])

    def attach(self, sr_uuid):
        iscsilib.ensure_daemon_running_ok(self.localIQN)
        log("Calling vdilunsr attach")

    def detach(self, sr_uuid):
        # Should logout of all the LUNS?
        if not self.isMaster:
            raise xs_errors.XenError('LVMMaster')

        # delete only when there are no VDIs

        if len(self.vdis) > 0:
            raise xs_errors.XenError('SRNotEmpty')

        # do nothing, the  map will automatically be removed
        log("Calling vdilunsr detach")

    def create(self, sr_uuid, size):

        log("Calling vdilunsr create")
        if not self.isMaster:
            util.SMlog('sr_create blocked for non-master')
            raise xs_errors.XenError('LVMMaster')

        # Check if this storage node is already being used
        SRs = self.session.xenapi.SR.get_all_records()
        for sr in SRs:
            record = SRs[sr]
            log(record)
            sm_config = record["sm_config"]
            if sm_config.has_key('target') and \
               sm_config['target'] == self.target and \
                    record['type'] == SR_TYPE_VDILUN:
                raise xs_errors.XenError('SRInUse')

        self.sm_config['datatype'] = 'ISCSI'
        self.sm_config['target'] = self.target
        self.session.xenapi.SR.set_sm_config(self.sr_ref, self.sm_config)

    def delete(self, sr_uuid):
        self.detach(sr_uuid)

    def probe(self):

        log("Calling vdilunsr probe")
        SRs = self.session.xenapi.SR.get_all_records()
        Rec = {}
        for sr in SRs:
            record = SRs[sr]
            sm_config = record["sm_config"]


            if sm_config.has_key('target') and \
                            sm_config['target'] == self.target and \
                            record['type'] == SR_TYPE_VDILUN:
                Rec[record["uuid"]] = sm_config
                break

        return self.srlist_toxml(Rec)


    def scan(self, sr_uuid):
        # TODO: Should probe the VDIs as well ?
        log("Calling vdilunsr scan")
        self.physical_size = 536870912000 # 500 GiB TODO: Fix
        return super(VDILUNSR, self).scan(sr_uuid)

    def refresh(self):
        # TODO: Not sure what to do here

        log("Calling vdilunsr refresh")

    def vdi(self, uuid):
        log("Calling vdilunsr vdi")
        return VDILUN(self, uuid)

    def forget_vdi(self, uuid):
        super(VDILUNSR, self).forget_vdi(uuid)


    def _updateStats(self, uuid, virtAllocDelta):

        valloc = int(self.session.xenapi.SR.get_virtual_allocation(self.sr_ref))
        # TODO Fix
        # self.virtual_allocation = valloc + virtAllocDelta
        # self.physical_utilisation = self.virtual_allocation
        # self.physical_size = self.physical_utilisation
        # self._db_update()

    def srlist_toxml(self, SRs):
        dom = xml.dom.minidom.Document()
        element = dom.createElement("SRlist")
        dom.appendChild(element)

        for val in SRs:
            record = SRs[val]
            entry = dom.createElement('SR')
            element.appendChild(entry)

            subentry = dom.createElement("UUID")
            entry.appendChild(subentry)
            textnode = dom.createTextNode(val)
            subentry.appendChild(textnode)

            subentry = dom.createElement("Target")
            entry.appendChild(subentry)
            textnode = dom.createTextNode(record['target'])
            subentry.appendChild(textnode)

            subentry = dom.createElement("TargetIQN")
            entry.appendChild(subentry)
            textnode = dom.createTextNode(record['targetIQN'])
            subentry.appendChild(textnode)
        return dom.toprettyxml()


class VDILUN(VDI.VDI):

    # 2TB - (Pad/bitmap + BAT + Header/footer)
    # 2 * 1024 * 1024 - (4096 + 4 + 0.002) in MiB
    MAX_VDI_SIZE_MB = 2093051

    VHD_SIZE_INC = 2 * 1024 * 1024
    MIN_VIRT_SIZE = 2 * 1024 * 1024
    ZEROOUT_BLOCK_SIZE = 4096  # Number of blocks to zero out when deleting VHD


    def load(self, vdi_uuid):
        # checks if the LUN exists
        log("Calling VDI LOAD")

        self.xapi_vdi = self._get_vdi_from_xapi(vdi_uuid)

        log(self.xapi_vdi)

        self.location = self.xapi_vdi.get('location', '')
        self.size = int(self.xapi_vdi.get('size', 0))
        self.iqn = self.location
        self.target = self.sr.target
        self.port = self.sr.port
        self.exists = False
        self.vdi_type = vhdutil.VDI_TYPE_VHD


        # TODO support authentication
        self.chapuser = ""
        self.chappass = ""

        self.attached = False
        try:
            self.attached = _checkTGT(self.iqn)
        except:
            pass

    def introduce(self, sr_uuid, vdi_uuid):
        log("Calling VDI introduce")

        self.attach(sr_uuid, vdi_uuid)

        if not self.vdiExists(self.path):
            self.detach(sr_uuid, vdi_uuid)
            raise xs_errors.XenError("VDIMissing")

        self.size = vhdutil.getSizeVirt(self.path)
        self.detach(sr_uuid, vdi_uuid)
        self.introduce_vdi(vdi_uuid)

        return VDI.VDI.get_params(self)

    def create(self, sr_uuid, vdi_uuid, size):
        log("Calling VDI CREATE")
        # checks if the size is correct
        self.size = self.validate_size(size)

        self.attach(sr_uuid, vdi_uuid)
        # Create the VHD on the LUN
        vhdutil.create(self.path, long(self.size), False, lvhdutil.MSIZE_MB)
        self.introduce_vdi(vdi_uuid)

        # This is done on the master, ideally, detach it
        self.detach(sr_uuid, vdi_uuid)

        return VDI.VDI.get_params(self)

    def delete(self, sr_uuid, vdi_uuid):

        # TODO: checks if no vbd exists
        log("Calling VDI DELLETE")

        if not self.sr.vdis.has_key(vdi_uuid):
            raise xs_errors.XenError('VDIUnavailable')

        if self.attached:
            raise xs_errors.XenError('VDIInUse')

        self._db_forget()
        self.sr._updateStats(self.sr.uuid, -self.size)

    def attach(self, sr_uuid, vdi_uuid):
        # Does the iscsi login

        self.iqn = self.validate_iqn()
        self.path = self.login_target()

        log("IQN")
        log(self.iqn)

        if not util.wait_for_path(self.path, MAX_TIMEOUT):
            util.SMlog("Unable to detect LUN attached to host [%s]" % self.sr.path)
            raise xs_errors.XenError('VDIUnavailable')



        ret = super(VDILUN, self).attach(sr_uuid, vdi_uuid)
        self.attached = True
        return ret

    def detach(self, sr_uuid, vdi_uuid):
        # Does iscsi logout
        log("Calling VDI DETACH")
        portal = "%s:%s" % (self.target, self.port)
        iscsilib.logout(portal, self.iqn)
        self.attached = False

    def resize(self, sr_uuid, vdi_uuid, size):
        # Updates the size in the DB
        log("Calling VDI RESIZE")

        util.SMlog("LUVDI.resize for %s" % self.uuid)

        if size / 1024 / 1024 > self.MAX_VDI_SIZE_MB:
            raise xs_errors.XenError('VDISize',
                                     opterr="VDI size cannot exceed %d MB" % \
                                            self.MAX_VDI_SIZE_MB)

        if size < self.size:
            util.SMlog('vdi_resize: shrinking not supported: ' + \
                       '(current size: %d, new size: %d)' % (self.size, size))
            raise xs_errors.XenError('VDISize', opterr='shrinking not allowed')

        if size == self.size:
            return VDI.VDI.get_params(self)

        size = util.roundup(self.VHD_SIZE_INC, size)
        old_size = self.size

        if not self.attached:
            self.attach(sr_uuid, vdi_uuid)

        vhdutil.setSizeVirtFast(self.path, size)
        self.size = vhdutil.getSizeVirt(self.path)
        self.utilisation = self.size

        vdi_ref = self.sr.srcmd.params['vdi_ref']
        self.session.xenapi.VDI.set_virtual_size(vdi_ref, str(self.size))
        self.session.xenapi.VDI.set_physical_utilisation(vdi_ref, str(self.size))
        self.sr._updateStats(self.sr.uuid, self.size - old_size)

        self.detach(sr_uuid, vdi_uuid)

        return VDI.VDI.get_params(self)

    def introduce_vdi(self, vdi_uuid):
        
        self.location = self.iqn
        self.utilisation = self.size
        self.ref = self._db_introduce()
        self.sr._updateStats(self.sr.uuid, self.size)

    def validate_size(self, size):
        if self.exists:
            raise xs_errors.XenError('VDIExists')

        if size / 1024 / 1024 > self.MAX_VDI_SIZE_MB:
            raise xs_errors.XenError('VDISize',
                    opterr="VDI size cannot exceed %d MB" % \
                            self.MAX_VDI_SIZE_MB)

        if size < self.MIN_VIRT_SIZE:
            size = self.MIN_VIRT_SIZE

        return util.roundup(self.VHD_SIZE_INC, size)

    def validate_iqn(self):

        if not self.iqn:
            vdi_sm_config = self.sr.srcmd.params["vdi_sm_config"]
            iqn = vdi_sm_config.get("targetIQN")
            iqn = unicode(iqn).encode('utf-8')
        else:
            iqn = self.iqn

        if not iqn:
            raise xs_errors.XenError('ConfigTargetIQNMissing')

        # check if LUN is reachable
        iscsi_rec = iscsilib.discovery(self.target, self.port, self.chapuser, self.chappass, iqn)  # TODO Chap
        log(iscsi_rec)

        return iqn

    def login_target(self):
        portal = "%s:%s" % (self.target, self.port)
        iscsi_login(portal, self.iqn, self.chapuser, self.chappass)
        # TODO CHap
        path = os.path.join("/dev/iscsi", self.iqn, portal, "LUN0")
        return path

    def vdiExists(self, vdi_path):
        """ Reads first 8 bytes of the path and checks for the cookie """

        fd = open(vdi_path)
        cookie = fd.read(8)
        fd.close()

        if cookie == VHD_COOKIE:
            return True

        return False

    def _get_vdi_from_xapi(self, vdi_uuid):

        vdi = {}
        try:
            vdi_ref = self.sr.session.xenapi.VDI.get_by_uuid(vdi_uuid)
            vdi = self.sr.session.xenapi.VDI.get_record(vdi_ref)
        except: # Can raise exception when creating a new VDI so it is not yet in the DB
            pass

        return vdi



if __name__ == '__main__':
    SRCommand.run(VDILUNSR, DRIVER_INFO)
else:
    SR.registerSR(VDILUNSR)
