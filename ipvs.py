#! /usr/bin/python

################################################################
#
# Usage instructions:
#
# ./ipvs.py <Name of the neutron provider network to which IPVS
#            instances must be attached>
#
# Example:
#
# ./ipvs.py mc-vmtp-prov
#
# To see usage instructions:
#
# ./ipvs.py -h
#
################################################################

import argparse
import logging
import os
import subprocess
import sys
import time

logging.basicConfig()
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument('network_name', help='Name of the neutron provider \
                    network to which IPVS instances must be attached', \
                    type=str)
args = parser.parse_args()
network_name = args.network_name
subnet_id    = ""
subnet_mask  = ""
free_IP_list = []


def cleanup():
    LOG.info(" doing cleanup...")
    output = run_command("nova list | grep ipvs | awk '{print $4}'")

    for instance in output.splitlines():
        LOG.info(" deleting instance %s", instance)
        run_command("nova delete " + instance)
        time.sleep(2)

    output = run_command("neutron port-list | grep ipvs | awk {'print $4}'")

    for port in output.splitlines():
        LOG.info(" deleting port %s", port)
        run_command("neutron port-delete " + port)
        time.sleep(2)

    run_command("rm -rf large_file.txt large_file.md5 ipvs_master.sh " + \
                "ipvs_backup.sh ipvs_real_server.sh ~/.ssh/known_hosts.old")

    run_command("nova keypair-delete ipvs-key-pair &>/dev/null")


def run_command(command):
    try:
        p = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()

        if out == None or err != "":
            LOG.error(" command failed: %s", command)
            LOG.error(" output: %s", out)
            LOG.error(" error : %s", err)
            cleanup()
            LOG.error(" script ended")
            sys.exit(0)

        return out

    except Exception as e:
        LOG.error(" exception raised when running command: %s", command)
        LOG.exception(" exception: %s", e)
        cleanup()
        LOG.error(" script ended")
        sys.exit(0)


def test_curl_vip():
    global free_IP_list
    expected_server_list = ["ipvs-real-server-1", "ipvs-real-server-2", \
                            "ipvs-real-server-3"]
    actual_server_list = []

    for i in range(0,3):
        output = run_command("curl -s --max-time 60 " + free_IP_list[2])
        time.sleep(1)
        if output.splitlines() == []:
            LOG.error(" could not curl the VIP %s, waited for 60 seconds", \
                      free_IP_list[2])
            LOG.error(" \"curl %s\" failed", free_IP_list[2])
            cleanup()
            LOG.error(" script ended")
            sys.exit(0)
        else:
            actual_server_list.append(output.splitlines()[0])

    delta_list = list(set(expected_server_list) - set(actual_server_list))

    if delta_list != []:
        LOG.error(" ===============================")
        LOG.error(" IPVS load balancing test failed")
        LOG.error(" VIP is %s", free_IP_list[2])
        for failed_server in delta_list:
            LOG.error(" %s failed to respond to curl", failed_server)
        LOG.error(" ===============================")
        cleanup()
        LOG.error(" script ended")
        sys.exit(0)
    else:
        LOG.info(" ================================")
        LOG.info(" IPVS load balancing test passed!")
        LOG.info(" VIP is %s", free_IP_list[2])
        LOG.info(" ================================")


def get_next_ip(ip):
    ip_parts_list = ip.split(".")

    if int(ip_parts_list[3]) == 253:
        return ip_parts_list[0] + "." + \
               ip_parts_list[1] + "." + \
               str(int(ip_parts_list[2]) + 1) + "." + \
               "0"

    return ip_parts_list[0] + "." + \
           ip_parts_list[1] + "." + \
           ip_parts_list[2] + "." + \
           str(int(ip_parts_list[3]) + 1)


def get_subnet_info():
    global network_name
    global subnet_id
    global subnet_mask

    output = run_command("neutron net-list | grep " + network_name + " | \
                          awk '{print $6}'")

    if output.splitlines() == []:
        LOG.error(" could not find subnet id for network %s", network_name)
        cleanup()
        LOG.error(" script ended")
        sys.exit(0)

    subnet_id = output.splitlines()[0]

    output = run_command("neutron subnet-list | grep " + subnet_id + " | \
                          awk '{print $6}'")

    subnet_mask = output.splitlines()[0].split("/")[1]

    output = run_command("neutron subnet-list | grep " + subnet_id + " | \
                          awk '{print $9, $11}'")

    start_ip = output.splitlines()[0].split()[0]
    start_ip = start_ip[1:-2]

    end_ip = output.splitlines()[0].split()[1]
    end_ip = end_ip[1:-2]

    curr_ip = start_ip
    for i in range(0, 6):
        while True:
            next_free_ip = get_next_ip(curr_ip)

            output = run_command("neutron port-list | grep " + next_free_ip)
            time.sleep(1)
            if output.splitlines() == []:
                free_IP_list.append(next_free_ip)
                curr_ip = next_free_ip
                break

            curr_ip = next_free_ip

    if len(free_IP_list) < 6:
        LOG.error(" not enough free IP addresses in %s", network_name)
        LOG.error(" this script needs 6 free IP addresses in %s for IPVS", \
                  network_name)
        cleanup()
        LOG.error(" script ended")
        sys.exit(0)


def check_if_instance_is_active(instance):
    poll_time = 300
    time_waited = 0

    while True:
        output = run_command("nova list | grep " + instance + \
                             " | grep ACTIVE | grep Running")
        if output.splitlines() == []:
            LOG.info(" waiting for instance %s to reach active running"\
                     " state...", instance)
            time.sleep(5)
            time_waited = time_waited + 5
            if time_waited > poll_time:
                LOG.error(" instance %s did not reach active running state,"\
                          " waited for %s seconds", instance, poll_time)
                cleanup()
                LOG.error(" script ended")
                sys.exit(0)
        else:
            LOG.info(" instance %s reached active running state", instance)
            break


def test_large_file_transfer():
    global free_IP_list
    run_command("rm -rf large_file.txt")
    run_command("rm -rf large_file.md5")
    run_command("curl -s " + free_IP_list[2] + \
                ":80/large_file.txt > large_file.txt")

    # Since, the keepalived algorithm is round-robbin, do curl two more times
    # to cycle through the next two real servers to make sure that
    # large_file.md5 is curled from the same real server as the large file.
    # This makes sure that both the large file and its md5sum are served from
    # the same real server.
    run_command("curl -s " + free_IP_list[2])
    run_command("curl -s " + free_IP_list[2])

    run_command("curl -s " + free_IP_list[2] + \
                ":80/large_file.md5 > large_file.md5")
    output = run_command("md5sum -c large_file.md5")

    if "large_file.txt: OK" not in output.splitlines()[0]:
        LOG.error(" =====================================")
        LOG.error(" IPVS large file transfer test failed")
        LOG.error(" md5sum check on large_file.txt failed")
        LOG.error(" VIP is %s", free_IP_list[2])
        LOG.error(" =====================================")
        cleanup()
        run_command("rm -rf large_file.txt large_file.md5")
        LOG.error(" script ended")
        sys.exit(0)
    else:
        LOG.info(" ======================================")
        LOG.info(" IPVS large file transfer test passed!")
        LOG.info(" md5sum check on large_file.txt passed!")
        LOG.info(" VIP is %s", free_IP_list[2])
        LOG.info(" ======================================")
        run_command("rm -rf large_file.txt large_file.md5")


def check_create_centos6_image():
    output = run_command("glance image-list | grep centos6.img")
    if output.splitlines() == []:
        LOG.info(" centos6.img not found. This script needs" + \
                 " centos6.img glance image.")
        LOG.info(" downloading centos6.img from http://cloud.centos.org...")
        LOG.info(" please wait... This may take several minutes...")
        run_command("curl -s http://cloud.centos.org/centos/6/images/" + \
                    "CentOS-6-x86_64-GenericCloud.qcow2 -o centos6.img")
        LOG.info(" centos6.img successfully downloaded from" + \
                 " http://cloud.centos.org")
        LOG.info(" creating centos6.img image in glance...")
        run_command("glance image-create --name centos6.img \
                    --disk-format=qcow2 --container-format=bare \
                    --file centos6.img")
        LOG.info(" centos6.img successfully created in glance")
        run_command("rm -rf centos6.img")
    else:
        LOG.info(" centos6.img found in glance")


def main():
    global network_name
    global subnet_id
    global subnet_mask
    global free_IP_list
    flavor   = "m1.medium"
    image    = "centos6.img"
    key_name = "ipvs-key-pair"

    cleanup()

    # Checking default nova security group rules
    LOG.info(" checking nova default security group rules")
    output = run_command("nova secgroup-list-rules default | grep -i tcp")
    if output.splitlines() == []:
        LOG.error(" tcp ports not allowed in default security group")
        LOG.error(" this script needs tcp port 22 to be allowed in" + \
                  " default security group for SSH access to IPVS" + \
                  " instances")
        LOG.error(" please allow tcp port 22 in default security group")
        LOG.error(" script ended")
        sys.exit(0)

    # Create ipvs-key-pair
    if 'HOME' not in os.environ:
        LOG.error(" HOME directory not found. Cannot run ssh-keygen")
        LOG.error(" HOME directory needed to run ssh-keygen")
        LOG.error(" script ended")
        sys.exit(0)
    else:
        home_dir = os.environ['HOME']
        if not os.path.exists(home_dir + "/.ssh/id_rsa.pub"):
            LOG.info(" ~/.ssh/id_rsa.pub does not exist. Running" + \
                     " ssh-keygen to create ~/.ssh/id_rsa.pub")
            run_command("ssh-keygen -q -t rsa -f " + home_dir + \
                        "/.ssh/id_rsa -N ''")
            LOG.info("~/.ssh/id_rsa.pub created")

    run_command("nova keypair-add --pub-key ~/.ssh/id_rsa.pub " + key_name)
    LOG.info(" nova key-pair %s created", key_name)

    # Get subnet id and port info
    LOG.info(" getting network and subnet info...")
    get_subnet_info()

    check_create_centos6_image()

    # Boot ipvs-master instance
    output = run_command("neutron port-create " + network_name + \
                         " --port-security-enabled=False --fixed-ip \
                         subnet_id=" + subnet_id + ",ip_address=" + \
                         free_IP_list[0] + " --name=port-ipvs-master | \
                         awk '/ id / {print $4}'")
    port_id = output.splitlines()[0]
    LOG.info(" port-ipvs-master created")
    run_command("rm -rf ipvs_master.sh")
    run_command("cp ipvs_master.sh.template ipvs_master.sh")
    run_command('sed -i "s/VIP_IP\/VIP_SUBNET_MASK/' + free_IP_list[2] + \
                '\/' + subnet_mask + '/g" ipvs_master.sh')
    run_command('sed -i "s/VIP_IP/' + free_IP_list[2] + '/g" ipvs_master.sh')
    run_command('sed -i "s/REAL_SERVER1_IP/' + free_IP_list[3] + \
                 '/g" ipvs_master.sh')
    run_command('sed -i "s/REAL_SERVER2_IP/' + free_IP_list[4] + \
                 '/g" ipvs_master.sh')
    run_command('sed -i "s/REAL_SERVER3_IP/' + free_IP_list[5] + \
                 '/g" ipvs_master.sh')
    run_command("nova boot --flavor " + flavor + " --image " + image + \
                " --nic port-id=" + port_id + " --key-name " + key_name + \
                " --user-data ipvs_master.sh ipvs-master")
    check_if_instance_is_active("ipvs-master")
    run_command("rm -rf ipvs_master.sh")

    # Boot ipvs-backup instance
    output = run_command("neutron port-create " + network_name + \
                         " --port-security-enabled=False --fixed-ip \
                         subnet_id=" + subnet_id + ",ip_address=" + \
                         free_IP_list[1] + " --name=port-ipvs-backup | \
                         awk '/ id / {print $4}'")
    port_id = output.splitlines()[0]
    LOG.info(" port-ipvs-backup created")
    run_command("rm -rf ipvs_backup.sh")
    run_command("cp ipvs_backup.sh.template ipvs_backup.sh")
    run_command('sed -i "s/VIP_IP\/VIP_SUBNET_MASK/' + free_IP_list[2] + \
                '\/' + subnet_mask + '/g" ipvs_backup.sh')
    run_command('sed -i "s/VIP_IP/' + free_IP_list[2] + '/g" ipvs_backup.sh')
    run_command('sed -i "s/REAL_SERVER1_IP/' + free_IP_list[3] + \
                 '/g" ipvs_backup.sh')
    run_command('sed -i "s/REAL_SERVER2_IP/' + free_IP_list[4] + \
                 '/g" ipvs_backup.sh')
    run_command('sed -i "s/REAL_SERVER3_IP/' + free_IP_list[5] + \
                 '/g" ipvs_backup.sh')
    run_command("nova boot --flavor " + flavor + " --image " + image + \
                " --nic port-id=" + port_id + " --key-name " + key_name + \
                " --user-data ipvs_backup.sh ipvs-backup")
    check_if_instance_is_active("ipvs-backup")
    run_command("rm -rf ipvs_backup.sh")

    # Boot ipvs-real-server-1 instance
    output = run_command("neutron port-create " + network_name + \
                         " --port-security-enabled=False --fixed-ip \
                         subnet_id=" + subnet_id + ",ip_address=" + \
                         free_IP_list[3] + " --name=port-ipvs-real-server-1 | \
                         awk '/ id / {print $4}'")
    port_id = output.splitlines()[0]
    LOG.info(" port-ipvs-real-server-1 created")
    run_command("rm -rf ipvs_real_server.sh")
    run_command("cp ipvs_real_server.sh.template ipvs_real_server.sh")
    run_command('sed -i "s/VIP_IP/' + free_IP_list[2] + \
                '/g" ipvs_real_server.sh')
    run_command("nova boot --flavor " + flavor + " --image " + image + \
                " --nic port-id=" + port_id + " --key-name " + key_name + \
                " --user-data ipvs_real_server.sh ipvs-real-server-1")
    check_if_instance_is_active("ipvs-real-server-1")

    # Boot ipvs-real-server-2 instance
    output = run_command("neutron port-create " + network_name + \
                         " --port-security-enabled=False --fixed-ip \
                         subnet_id=" + subnet_id + ",ip_address=" + \
                         free_IP_list[4] + \
                         " --name=port-ipvs-real-server-2 | \
                         awk '/ id / {print $4}'")
    port_id = output.splitlines()[0]
    LOG.info(" port-ipvs-real-server-2 created")
    run_command("nova boot --flavor " + flavor + " --image " + image + \
                " --nic port-id=" + port_id + " --key-name " + key_name + \
                " --user-data ipvs_real_server.sh ipvs-real-server-2")
    check_if_instance_is_active("ipvs-real-server-2")

    # Boot ipvs-real-server-3 instance
    output = run_command("neutron port-create " + network_name + \
                         " --port-security-enabled=False --fixed-ip \
                         subnet_id=" + subnet_id + ",ip_address=" + \
                         free_IP_list[5] + \
                         " --name=port-ipvs-real-server-3 | \
                         awk '/ id / {print $4}'")
    port_id = output.splitlines()[0]
    LOG.info(" port-ipvs-real-server-3 created")
    run_command("nova boot --flavor " + flavor + " --image " + image + \
                " --nic port-id=" + port_id + " --key-name " + key_name + \
                " --user-data ipvs_real_server.sh ipvs-real-server-3")
    check_if_instance_is_active("ipvs-real-server-3")
    run_command("rm -rf ipvs_real_server.sh")

    # Wait for all instances to boot and keepalived is setup
    LOG.info(" waiting for 180 seconds for all the instances to boot...")
    time.sleep(60)
    run_command('ssh-keygen -R ' + free_IP_list[0] + ' &>/dev/null')
    run_command('ssh -t -t -o "StrictHostKeyChecking no" centos@' + \
                free_IP_list[0] + \
                '  "sudo service keepalived restart" &>/dev/null')
    run_command('ssh-keygen -R ' + free_IP_list[1] + ' &>/dev/null')
    run_command('ssh -t -t -o "StrictHostKeyChecking no" centos@' + \
                free_IP_list[1] + \
                '  "sudo service keepalived restart" &>/dev/null')
    run_command("rm -rf ~/.ssh/known_hosts.old")
    time.sleep(120)

    # curl VIP thru ipvs-master
    LOG.info(" VIP is %s, testing \"curl %s\" thru ipvs-master", \
             free_IP_list[2], free_IP_list[2])
    test_curl_vip()

    # curl VIP thru ipvs-backup
    LOG.info(" shutting down port-ipvs-master to trigger failover")
    run_command("neutron port-update port-ipvs-master --admin-state-up False")
    LOG.info(" waiting for 60 seconds for ipvs-backup to takeover")
    time.sleep(60)
    LOG.info(" VIP is %s, testing \"curl %s\" thru ipvs-backup", \
             free_IP_list[2], free_IP_list[2])
    test_curl_vip()

    LOG.info(" turning port-ipvs-master back on")
    run_command("neutron port-update port-ipvs-master --admin-state-up True")
    LOG.info(" waiting for 60 seconds")
    time.sleep(20)
    run_command('ssh-keygen -R ' + free_IP_list[0] + ' &>/dev/null')
    run_command('ssh -t -t -o "StrictHostKeyChecking no" centos@' + \
                free_IP_list[0] + \
                '  "sudo service keepalived restart" &>/dev/null')
    run_command('ssh-keygen -R ' + free_IP_list[1] + ' &>/dev/null')
    run_command('ssh -t -t -o "StrictHostKeyChecking no" centos@' + \
                free_IP_list[1] + \
                '  "sudo service keepalived restart" &>/dev/null')
    run_command("rm -rf ~/.ssh/known_hosts.old")
    time.sleep(40)
    LOG.info(" VIP is %s, testing \"curl %s\"", \
             free_IP_list[2], free_IP_list[2])
    test_curl_vip()

    # Test IPVS large file transfer
    LOG.info(" testing large file transfer using IPVS")
    test_large_file_transfer()

    # Cleaup IPVS instances and ports
    cleanup()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        LOG.error(" exception raised in main()")
        LOG.exception(" exception: %s", e)
        cleanup()
        LOG.error(" script ended")
