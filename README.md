
# NOTE: For XenServer 7.1 look at the xs71 branch

# ReLVHDoISCSISR

This Xenserver supplemental pack allows the functionality to resignature a
given LVMoISCSI SR which allows the SR to be reattached to the pool. This pack
is targeted towards Xenserver 6.5


## Why? 

The primary objective of this project was to enable the ability to do QoS per
VM.  This leveraged the QoS capabilities provided by storages like
SolidFire/Equalogic etc.  This QoS capability can be achieved by assigning a
single LUN to a VDI. This LUN would be introduced to Xenserver as a single SR.
So essentially, we are doing a single VDI per LUN.

The main drawback of this approach is that users cannot leverage the
fast-snapshot/clone functionality offered by the backend storages as any
snapshot taken on the backend storage is unaware of the underlying VDI(s) and
metadata, and would copy the LUN block-by-block. Any attempt to attach this
cloned LUN onto Xenserver will result in an error as there will be metadata
conflicts.

## Overview of the resignature approach

The plugin provided here will resignature the UUIDs during a create of
the cloned SR so there are no UUID conflicts. The resignature process is
invoked when an `sr-create` is called on a LUN with a single VDI with the
`type=relvmoiscsi` flag . The following steps are involved:

1. **LVM Resign:** The first step is to resignature the LVM volumes, We generate
   unique ids for the LVM physical volume, volume group and logical volumes
   present in the LVM volume group.

1. **SR Metadata Resign:** Once the LVM resignature is complete, we activate
   the new volume group and resignature the SR metadata stored in the `MGT`
   logical volume of the volume group.

1. **VDI Resign:** Finally, we resignature the VDIs which are present in a
   logical volume. If the VDI has any parent locators, we make sure that they
   point to the correct ones since they will change during the resign process.  We
   also delete any snapshots if they are present on the SR as we want the clone
   to only contain the active VDI. 

1. **SR Creation:** Once all entities have been resignatured, we error out with 
   a _resign successful_ message (see example).

1. **SR Reattach** This new SR is ready to be attached back to the pool.We  use
   the standard commands with  `type=lvmoiscsi`, which is the default for ISCSI
   LUNs.

## Configuration 

We have added a new `type` of SR on Xenserver called `relvmoiscsi`. To make this 
avaliable, you have to restart xapi after installing this pack.

Restart by using:

```
# /etc/init.d/xapi restart
```

## Building 

Setup a DDK VM and clone this repo there ([Instructions for setting up a DDK VM.](http://support.citrix.com/servlet/KbServlet/download/38324-102-714674/XenServer-6.5.0_Supplemental%20Packs%20and%20the%20DDK%20Guide.pdf))

``` bash
# git clone https://github.com/cloudops/ReLVHDoISCSISR.git
# cd ReLVHDoISCSISR
# make
```

This will generate `ReLVHDoISCSISR.iso` which contains the supplemental pack.
Install it by attaching the ISO to Xenserver DOM0 and running the install
script present in it. 

# Installing
Copy the `ReLVHDoISCSISR.iso` from this repo to the XenServer host where you want to install the pack. 

```bash

# scp ReLVHDoISCSISR.iso root@172.31.0.33:

```

Mount the iso on the XenServer and run the install script. Restart XAPI after install. 

```bash

[root@coe-hq-xen03 ~]# mkdir /tmp/isomount
[root@coe-hq-xen03 ~]# mount ReLVHDoISCSISR.iso /tmp/isomount/ -o loop
mount: ReLVHDoISCSISR.iso is write-protected, mounting read-only
[root@coe-hq-xen03 ~]# cd /tmp/isomount/
[root@coe-hq-xen03 isomount]# ./install.sh 
Installing 'LVHDoISCSISR with SR resigning'...

Preparing...                ########################################### [100%]
   1:ReLVHDoISCSISR         ########################################### [100%]
Pack installation successful.
[root@coe-hq-xen03 isomount]# service xapi restart
Stopping xapi: ..                                          [  OK  ]
Starting xapi: OK                                          [  OK  ]
[root@coe-hq-xen03 isomount]# cd
[root@coe-hq-xen03 ~]# umount /tmp/isomount 
[root@coe-hq-xen03 ~]# rm ReLVHDoISCSISR.iso 
rm: remove regular file `ReLVHDoISCSISR.iso'? y
[root@coe-hq-xen03 ~]# 

```

## Testing

We have tested this on Xenserver 6.5 with Solidfire and Equalogic as the storage
backends. You can find the testing doc [Here.](docs/xenserver-testing.pdf)

## Example 

```bash
# xe sr-create name-label=syed-single-clone type=relvmoiscsi \
                device-config:target=172.31.255.200 \
                device-config:targetIQN=$IQN  \
                device-config:SCSIid=$SCSIid \
                device-config:resign=true \
                shared=true 
Error code: SR_BACKEND_FAILURE_1
Error parameters: , Error reporting error, unknown key The SR has been successfully resigned. Use the lvmoiscsi type to attach it,
#
```

## Notes
1. Since this plugin modifies the internal structure of SR, a failure during the operation might result in an un-recoverable SR. **Use this plugin only on 
SRs where you can afford data loss (eg clones). Do not use this on an SR which does not have a way to recover in case of failure**

1. As a part of the resignature approach, the plugin deletes all the snapshots that are present on the SR leaving just the VDI. This is expected behaviour 
and should not be considered as an error.
