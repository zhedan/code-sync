#!/bin/python

import os
import sys
import yaml
import logging
import paramiko
import subprocess
import argparse

logging.basicConfig(format='%(asctime)s %(levelname)-6s'
                           '%(name)-8s %(message)s',
                    datefmt='%m-%d %H:%M:%S')
LOG = logging.getLogger('code-sync')
LOG.setLevel(logging.DEBUG)

INVENTORY_MGR = None


def get_hosts(patterns, hosts_file='/etc/ansible/hosts'):
    from ansible.parsing.dataloader import DataLoader
    from ansible.inventory.manager import InventoryManager

    global INVENTORY_MGR

    hosts = []

    if not patterns:
        return hosts

    loader = DataLoader()

    if INVENTORY_MGR is None:
        INVENTORY_MGR = InventoryManager(loader=loader, sources=[hosts_file])


    for p in patterns:
        host_objs = INVENTORY_MGR.list_hosts(p)
        hosts.extend([x.address for x in host_objs])

    return hosts


def find_conf_file(work_dir):
    work_dir = os.path.abspath(work_dir) 

    conf_file = ''

    while True:
        tmp_conf_file = os.path.join(work_dir, 'config.yml')
        if os.path.isfile(tmp_conf_file):
            conf_file = tmp_conf_file
            break

        work_dir = os.path.abspath('%s/..' % work_dir)
        if work_dir == '/':
            break
    
    return conf_file


def parse_conf(conf_file):
    conf = None

    with open(conf_file) as fp:
        conf = yaml.load(fp)

    return conf


def get_ssh_client(host):
    if not hasattr(get_ssh_client, 'clients'):
        get_ssh_client.clients = {}

    clients = get_ssh_client.clients

    if host not in clients:
        new_client = paramiko.SSHClient()
        new_client.load_system_host_keys()
        new_client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy())
        new_client.connect(host)
        clients[host] = new_client

    return clients[host]


def scp(host, src, dest, recursion=False, src_depth=1):
    client = get_ssh_client(host)
    sftp = client.open_sftp()

    LOG.debug('%s:', host)
    if recursion:
        src_pdir = '/'.join(src.strip('/').split('/')[:src_depth])

        if os.path.abspath(src):
            src_pdir = '/' + src_pdir

        for pdir, dirs, files in os.walk(src):
            for fname in files:
                fpath = os.path.join(pdir, fname)

                if os.path.isabs(pdir):
                    if src_pdir:
                        sub_dir = pdir.split(src_pdir)[1]
                    else:
                        sub_dir = pdir
                else:
                    sub_dir = pdir

                sub_dir = sub_dir.strip('/')

                dest_path = os.path.join(dest, sub_dir, fname)

                LOG.debug('    %s -> %s', fpath, dest_path)
                sftp.put(fpath, dest_path, confirm=True)
    else:
        LOG.debug('    %s -> %s', src, dest)
        sftp.put(src, dest, confirm=True)


def ssh(host, cmd, only_output=True):
    client = get_ssh_client(host)

    stdin, stdout, stderr = client.exec_command(cmd)

    if only_output:
        return stdout.read()

    else:
        return stdout.read(), stderr.read()


def get_files_from_src(src):
    fpaths = []

    if os.path.isdir(src):
        for pdir, dirs, files in os.walk(src):
            for fname in files:
                if fname.startswith('.'):
                    continue
                fpath = os.path.join(pdir, fname)
                fpaths.append(fpath)
    else:
        fpaths.append(src)

    return fpaths


def dos2unix(src):
    files_to_convert = get_files_from_src(src)
    for fpath in files_to_convert:
        with open(fpath) as f:
            first_line = f.readline()
            if '\r\n' not in first_line:
                continue
                
            subprocess.check_call(['dos2unix', fpath])

    LOG.debug('dos2unix successfully: %s', src)


def check_flake8(src):
    files_to_check = get_files_from_src(src)

    if files_to_check:
        cmd = ['/bin/oflake8'] + files_to_check
        LOG.debug('checked cmd: %s' % ' '.join(cmd))
        process = subprocess.Popen(cmd, stderr=subprocess.STDOUT)
        process.wait()
        if process.returncode:
            LOG.error('flake8 check failed: %s' % src)
            sys.exit(1)

    LOG.debug('flake8 checked successully: %s' % src)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", help='work dir')

    return parser.parse_args()


def main():
    args = parse_args()

    conf_file = find_conf_file(args.work_dir)

    if not conf_file:
        LOG.error("config file not exist in work dir: %s", args.work_dir)
        sys.exit(1)

    conf = parse_conf(conf_file)

    projects = conf['projects']
    work_dir = conf['work_dir']

    if os.path.exists(work_dir):
        if not os.path.isdir(work_dir):
            LOG.error("work dir exist, but not a dir: %s", work_dir)
    else:
        os.makedirs(work_dir) 

    for proj, proj_conf in projects.items():
        if proj not in conf['enabled']:
            continue

        conf_dirs = proj_conf.get('conf_dirs', [])
        code_dirs = proj_conf.get('code_dirs', [])

        src_dirs = conf_dirs + code_dirs

        # mkdir
        for d in src_dirs:
            src_dir_path = os.path.join(work_dir, d)
            if not os.path.exists(src_dir_path):
                os.makedirs(src_dir_path) 
            dos2unix(src_dir_path)

        for d in code_dirs:
            code_dir_path = os.path.join(work_dir, d)
            check_flake8(code_dir_path)

        host_conf = proj_conf.get('hosts', {})
        enabled_host_patterns = host_conf.get('enabled')
        disabled_host_patterns = host_conf.get('disabled')

        hosts = get_hosts(enabled_host_patterns)
        disabled_hosts = get_hosts(disabled_host_patterns)

        # convert code and conf file
        for host in hosts:
            LOG.debug("%s: ", host)
            for d in code_dirs:
                code_dir = os.path.join(work_dir, d)
                scp(host, code_dir, conf['site_pkgs_dir'], recursion=True,
                    src_depth=2)

            for d in conf_dirs:
                conf_dir = os.path.join(work_dir, d)
                scp(host, conf_dir, '/', recursion=True, src_depth=2)


        # restart relative services
        for host in hosts:
            LOG.debug("%s: ", host)
            if host in disabled_hosts: 
                LOG.debug("    host disabled, skip restart services")
                continue

            services = proj_conf.get('services', [])
            for s in services:
                LOG.debug("    restart service %s", s)
                ssh(host, conf['service_restart_cmd'] % {'serv_name': s})


if __name__ == "__main__":
    sys.exit(main())
