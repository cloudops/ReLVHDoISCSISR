#!/bin/bash
# Usage: install_iso.sh <xenserver_ip> <root password>

sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 mkdir -p /tmp/test
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 rm -f *.iso
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 wget -c 'https://github.com/cloudops/ReLVHDoISCSISR/raw/master/ReLVHDoISCSISR.iso'  --no-check-certificate
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 mount ReLVHDoISCSISR.iso /tmp/test -o loop
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 rpm -ivh /tmp/test/ReLVHDoISCSISR-1.0-1.x86_64.rpm --force
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 umount /tmp/test
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 rmdir /tmp/test
sshpass -p$2 ssh -o StrictHostKeyChecking=no root@$1 service xapi restart

