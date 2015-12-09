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
# ReLVHDoISCSISR: LVHD over ISCSI software initiator SR driver with resigning of duplicate SRs
#

import SR, LVHDSR, LVHDoISCSISR, SRCommand, util, lvhdutil
from srmetadata import LVMMetadataHandler, UUID_TAG, NAME_LABEL_TAG, IS_A_SNAPSHOT_TAG, \
    VDI_DELETED_TAG, READ_ONLY_TAG, MANAGED_TAG, SNAPSHOT_OF_TAG, VDI_TYPE_TAG

import os
import copy
import sys
import tempfile
import xs_errors
import lvmconfigparser
import vhdutil
from lvhdutil import VG_LOCATION, VG_PREFIX
from lvutil import CMD_PVCREATE, LVM_BIN, MDVOLUME_NAME
from pprint import pformat as pf

CMD_VGCFGRESTORE = os.path.join(LVM_BIN, "vgcfgrestore")
CMD_PVDISPLAY = os.path.join(LVM_BIN, "pvdisplay")

CAPABILITIES = ["SR_PROBE", "SR_UPDATE", "SR_METADATA", "SR_TRIM",
                "VDI_CREATE", "VDI_DELETE", "VDI_ATTACH", "VDI_DETACH",
                "VDI_GENERATE_CONFIG", "VDI_CLONE", "VDI_SNAPSHOT",
                "VDI_RESIZE", "ATOMIC_PAUSE", "VDI_RESET_ON_BOOT/2",
                "VDI_UPDATE"]

CONFIGURATION = [['SCSIid', 'The scsi_id of the destination LUN'], \
                 ['target', 'IP address or hostname of the iSCSI target'], \
                 ['targetIQN', 'The IQN of the target LUN group to be attached'], \
                 ['chapuser', 'The username to be used during CHAP authentication'], \
                 ['chappassword', 'The password to be used during CHAP authentication'], \
                 ['incoming_chapuser',
                  'The incoming username to be used during bi-directional CHAP authentication (optional)'], \
                 ['incoming_chappassword',
                  'The incoming password to be used during bi-directional CHAP authentication (optional)'], \
                 ['port', 'The network port number on which to query the target'], \
                 ['multihomed',
                  'Enable multi-homing to this target, true or false (optional, defaults to same value as host.other_config:multipathing)'], \
                 ['usediscoverynumber', 'The specific iscsi record index to use. (optional)'], \
                 ['allocation', 'Valid values are thick or thin (optional, defaults to thick)'],
                 ['resign', 'Resignature the SR instead of deleting all data, true or false. Defaults to false']]

DRIVER_INFO = {
    'name': 'LVHD over iSCSI with resigning of duplicates',
    'description': 'SR plugin which represents disks as Logical Volumes within a Volume Group created on an iSCSI LUN',
    'vendor': 'CloudOps Inc',
    'copyright': '(C) 2015 CloudOps Inc',
    'driver_version': '1.0',
    'required_api_version': '1.0',
    'capabilities': CAPABILITIES,
    'configuration': CONFIGURATION,
}


class ReLVHDoISCSISR(LVHDoISCSISR.LVHDoISCSISR):
    """LVHD over ISCSI storage repository with resigning of duplicates"""

    LV_VHD_PREFIX = 'VHD-'

    def handles(type):
        if __name__ == '__main__':
            name = sys.argv[0]
        else:
            name = __name__
        if name.endswith("LVMoISCSISR"):
            return type == "lvmoiscsi"
        if type == "relvhdoiscsi":
            return True
        return False

    handles = staticmethod(handles)

    def create(self, sr_uuid, size):

        if self._checkConfigResign():
            if util.test_SCSIid(self.session, sr_uuid, self.SCSIid):
                raise xs_errors.XenError('SRInUse')

            try:
                # attach the device
                util.SMlog("Trying to attach iscsi disk")

                self.iscsi.attach(sr_uuid)
                if not self.iscsi.attached:
                    raise xs_errors.XenError('SRNotAttached')

                util.SMlog("Attached iscsi disk at %s \n" % self.iscsi.path)

                # generate new UUIDs for VG and LVs
                old_vg_name = self._getVgName(self.dconf['device'])
                lvm_config_dict = self._getLvmInfo(old_vg_name)
                lvUuidMap = {}  # Maps old lv uuids to new uuids

                for lv_name in lvm_config_dict[old_vg_name]['logical_volumes']:
                    if lv_name == MDVOLUME_NAME:
                        continue
                    oldUuid = lv_name[4:]  # remove the VHD-
                    lvUuidMap[oldUuid] = util.gen_uuid()

                new_vg_name = VG_PREFIX + sr_uuid

                self._resignLvm(sr_uuid, old_vg_name, lvUuidMap, lvm_config_dict)
                # causes creation of nodes and activates the lvm volumes
                LVHDSR.LVHDSR.load(self, sr_uuid)

                new_vdi_info = self._resignSrMetadata(new_vg_name, self.uuid, lvUuidMap)
                self._resignVdis(new_vg_name, lvUuidMap)
                self._deleteAllSnapshots(new_vdi_info)

                # set the mdexists flag so that attach will not create it again
                self.mdexists = self.lvmCache.checkLV(self.MDVOLUME_NAME)

            except:
                util.logException("RESIGN_CREATE")
                raise

            util.SMlog("Calling Attach for new VDIs")
            return super(ReLVHDoISCSISR, self).attach(sr_uuid)  # resigned disk, attach it

        return super(ReLVHDoISCSISR, self).create(sr_uuid, size)  # fresh disk, initialize it

    def _resignLvm(self, new_uuid, old_vg_name, lvUuidMap, lvm_config_dict):

        resigned_lvm_config = copy.deepcopy(lvm_config_dict)
        vg_info = resigned_lvm_config[old_vg_name]
        del resigned_lvm_config[old_vg_name]

        new_vg_name = VG_PREFIX + new_uuid
        resigned_lvm_config[new_vg_name] = vg_info

        # resign the PV
        pv_uuid = None

        for pv in vg_info['physical_volumes']:
            pv_uuid = lvmconfigparser.gen_lvm_uuid()
            vg_info['physical_volumes'][pv]['id'] = pv_uuid
            vg_info['physical_volumes'][pv]['device'] = self.dconf['device']

        assert pv_uuid, "PV not found in config"

        # resign the LVs
        for lv_name in vg_info['logical_volumes'].keys():
            vg_info['logical_volumes'][lv_name]['id'] = lvmconfigparser.gen_lvm_uuid()
            if lv_name != MDVOLUME_NAME:
                # change the vg name
                old_uuid = lv_name[4:]  # Remove the VHD-
                new_uuid = lvUuidMap[old_uuid]
                new_lv_name = self.LV_VHD_PREFIX + new_uuid

                vg_info['logical_volumes'][new_lv_name] = vg_info['logical_volumes'][lv_name]
                del vg_info['logical_volumes'][lv_name]

        # write new config to disk
        _fd, config_file = tempfile.mkstemp()
        resigned_config = lvmconfigparser.LvmConfigParser(resigned_lvm_config)
        fd = open(config_file, 'w')
        fd.write(resigned_config.toConfigString())
        fd.close()

        # restore from this config
        util.pread2([CMD_PVCREATE, '-u', pv_uuid, '-ff', '-y', '--restorefile',
                     config_file, self.dconf['device']])

        util.pread2([CMD_VGCFGRESTORE, '-f', config_file, new_vg_name])

        # remove the tempfile which stored the config
        os.remove(config_file)
        util.SMlog("RESIGN DONE.")


    def _getLvmInfo(self, vg_name):
        """
        Parses the LVM volume and returns a config dict
        :param vg_name: Name of the VG
        :return: lvm config dict
        """

        _fd, temp_file = tempfile.mkstemp()
        util.pread2(['vgcfgbackup', '-f', temp_file, vg_name])

        # parse old config
        lvm_config = lvmconfigparser.LvmConfigParser()
        lvm_config.parse(temp_file)
        lvm_config_dict = lvm_config.toDict()

        os.remove(temp_file)

        assert vg_name in lvm_config_dict, "No volume group found"
        assert 'physical_volumes' in lvm_config_dict[vg_name], "No physical volumes found"
        assert len(lvm_config_dict[vg_name]['physical_volumes']) == 1, "LUN should container only 1 physical volume"
        assert 'logical_volumes' in lvm_config_dict[vg_name], "No logical volumes found"

        return lvm_config_dict


    def _getSrMetadata(self, mdata_dev):
        """
        Xen stores the metatadata about an LVM SR in a separate volume group
        named MGT. This function reads that metadata and returns as a dict

        :param mdata_dev: The MGT volume device that holds the SR metadata
        """

        util.SMlog("Resigning the SR metadata")

        sr_info, vdi_info = LVMMetadataHandler(mdata_dev).getMetadata()

        util.SMlog("sr_info: %s" % sr_info)
        util.SMlog("vdi_info: %s" % vdi_info)

        vdi_info_map = {}

        for offset, vi in vdi_info.iteritems():
            vdi_info_map[vi['uuid']] = vi

        return vdi_info_map

    def _deleteAllSnapshots(self, vdi_info):

        self._loadvdis()

        util.SMlog("Deleting all snapshots")
        for offset, vi in vdi_info.iteritems():
            if vi['is_a_snapshot'] == '1':
                uuid = vi['uuid']
                vdi = self.allVDIs[uuid]
                assert vdi, "VDI not found for deletion"
                util.SMlog("Delete %s" % uuid)
                lv_name = self.LV_VHD_PREFIX + uuid
                self.lvmCache.remove(lv_name)


    def _resignSrMetadata(self, vg_name, sr_uuid, vdi_uuids):
        """
        Xen stores the metatadata about an LVM SR in a separate volume group
        named MGT. This function reads that metadata and resigns it.

        :param mdata_dev: The MGT volume device that holds the SR metadata
        :param sr_uuid: new UUID that needs to be used
        :param vdi_uuids: a map between old uuid and new uuids which was generated when rewriting LVM config

        """

        util.SMlog("Resigning the SR metadata")

        mdata_dev = os.path.join(lvhdutil.VG_LOCATION, vg_name, MDVOLUME_NAME)
        sr_info, vdi_info = LVMMetadataHandler(mdata_dev).getMetadata()

        util.SMlog("sr_info: %s" % pf(sr_info))
        util.SMlog("vdi_info: %s" % pf(vdi_info))

        sr_info[UUID_TAG] = sr_uuid

        # change the uuids and name labels for VDIs
        for vdi_offset in vdi_info.keys():
            vdi_map = vdi_info[vdi_offset]
            old_uuid = vdi_map[UUID_TAG]
            new_uuid = vdi_uuids[old_uuid]
            vdi_map[UUID_TAG] = new_uuid

            if vdi_map[SNAPSHOT_OF_TAG]:
                old_snapshot_uuid = vdi_map[SNAPSHOT_OF_TAG]
                if old_snapshot_uuid in vdi_uuids:
                    # sometimes the uuid is not present and this may be
                    # a stale snapshot which will be clean by GC
                    vdi_map[SNAPSHOT_OF_TAG] = vdi_uuids[old_snapshot_uuid]

            #vdi_map[NAME_LABEL_TAG] = self.CLONE_NAME_LABEL_PREFIX + vdi_map[NAME_LABEL_TAG]

        util.SMlog("Vdi info to update %s" % pf(vdi_info))
        LVMMetadataHandler(mdata_dev).writeMetadata(sr_info, vdi_info)

        return vdi_info


    def _resignVdis(self, vg_name, lvUuidMap):
        """
        Changes the parent locators in each VDI so it points to the resigned LVs

        :param vg_name: The Volumegroup where the VDIs reside
        :param lvUuidMap: map from old uuids to new uuids
        """

        for uuid in lvUuidMap.values():

            lv_name = self.LV_VHD_PREFIX + uuid
            self.lvmCache.activateNoRefcount(lv_name)
            self.lvmCache.setReadonly(lv_name, False)

            path = os.path.join(lvhdutil.VG_LOCATION, vg_name, lv_name)
            util.SMlog("RESIGN VDI %s" % path)
            old_parent = vhdutil._getVHDParentNoCheck(path)

            if old_parent:

                old_parent_uuid = old_parent[4:]  # remove the VHD-
                new_parent_uuid = lvUuidMap[old_parent_uuid]

                parent_lv_name = self.LV_VHD_PREFIX + new_parent_uuid
                self.lvmCache.activateNoRefcount(parent_lv_name)

                parent_path = os.path.join(lvhdutil.VG_LOCATION, vg_name, parent_lv_name)

                util.SMlog("RESIGN VDI HAS PARENT  %s" % parent_path)
                vhdutil.setParent(path, parent_path, False)


    def _getVgName(self, lvm_device):
        """
        Get the VG name using pvdisplay for a given device
        :param lvm_device: The device for which we want to find VG of
        :return: vg name
        """

        vg_name = None

        # get VG name from pvdisplay
        util.SMlog("Reading metadata from device:%s" % lvm_device)
        stdout = util.pread2([CMD_PVDISPLAY, lvm_device])

        assert stdout, "pvdisplay: Could not find device"

        for line in stdout.split('\n'):
            if line.find("VG Name") >= 0:
                line = line.strip()
                vg_name = line.split(' ', 2)[2].strip()

        assert vg_name, "Volume group not found"

        return vg_name

    def _checkConfigResign(self):
        """
        Checks if the caller wants to resign the SR first based on the
        args passed to sr-create next based on the host-config

        :return: True if resign is enabled, False otherwise
        """

        if 'resign' in self.dconf and self.dconf['resign'].lower() == 'true':
            return True

        # explicit false
        if 'resign' in self.dconf and self.dconf['resign'].lower() == 'false':
            return False

        assert self.host_ref, "Host reference not found"

        other_config = self.session.xenapi.host.get_other_config(self.host_ref)

        if 'resign' in other_config and other_config['resign'].lower() == 'true':
            return True

        return False

if __name__ == '__main__':
    SRCommand.run(ReLVHDoISCSISR, DRIVER_INFO)
else:
    SR.registerSR(ReLVHDoISCSISR)
