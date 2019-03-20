import time
import moo.fabric
from moo.logging import Logging

LOG = Logging(__name__)
log = LOG.getLogger()


class MaasUtils:
    """MAAS Utils Class"""

    def __init__(self, cfg):
        self.cfg = cfg
        LOG.SetLevel(self.cfg.log_level)

    def UpdateHost(self, instance_name, instance_id, mac, tag, host):
        ver = self.GetVersion(host)
        if int(ver[0]) == 1:
            self.UpdateHostV1(instance_name, instance_id, mac, tag, host)
        elif int(ver[0]) == 2:
            self.UpdateHostV2(instance_name, instance_id, mac, tag, host)
        else:
            log.error('ERROR: MAAS version %s is not supported' % ver)
            return

    def UpdateHostV1(self, instance_name, instance_id, mac, tag, host):
        cmd = "maas %s nodes list | \
               jq -r '.[] | select(.interface_set[].mac_address==\"%s\").system_id'" % (self.cfg.profile, mac)
        sys_id = None
        log.info('Waiting for instance to be ready for commision')
        while not sys_id:
            time.sleep(5)
            sys_id = moo.fabric.RunCommand(self.cfg, host, cmd)
        # need to modify /usr/lib/python3/dist-packages/provisioningserver/drivers/power/nova.py to support v3
        # make_setting_field('os_project_domain_name', "project_domain_name", required=True),
        # make_setting_field('os_user_domain_name', "user_domain_name", required=True),
        # ...
        # def power_control_nova(
        #    self, power_change, nova_id=None, os_tenantname=None,
        #    os_username=None, os_password=None, os_authurl=None,
        #    os_project_domain_name=None, os_user_domain_name,
        #    **extra):
        #     ...
        # nova = self.nova_api.Client(2, username=os_username,
        #                            password=os_password,
        #                            project_name=os_tenantname,
        #                            project_domain_name=os_project_domain_name,
        #                            user_domain_name=os_user_domain_name,
        #                            auth_url=os_authurl)
        cmd = "maas %s node update %s power_type=nova \
               power_parameters_nova_id=%s \
               power_parameters_os_tenantname=%s \
               power_parameters_os_username=%s \
               power_parameters_os_password=%s \
               power_parameters_os_authurl=%s \
               power_parameters_os_project_domain_name=%s \
               power_parameters_os_user_domain_name=%s" % (self.cfg.profile, sys_id, instance_id,
                                                  self.cfg.credentials['project_name'],
                                                  self.cfg.credentials['username'],
                                                  self.cfg.credentials['password'],
                                                  self.cfg.credentials['auth_url'],
                                                  self.cfg.credentials['project_domain_name'],
                                                  self.cfg.credentials['user_domain_name'])
        moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s node update %s hostname=%s" % (self.cfg.profile, sys_id, instance_name)
        moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s tag read %s" % (self.cfg.profile, tag)
        ret = moo.fabric.RunCommand(self.cfg, host, cmd)
        if ret == "Not Found":
            cmd = "maas %s tags new name=%s" % (self.cfg.profile, tag)
            moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s tag update-nodes %s add=%s" % (self.cfg.profile, tag, sys_id)
        moo.fabric.RunCommand(self.cfg, host, cmd)
        log.info('%s has been added to MAAS' % instance_name)

    def UpdateHostV2(self, instance_name, instance_id, mac, tag, host):
        cmd = "maas %s machines read | \
               jq -r '.[].interface_set[] | \
               select(.mac_address==\"%s\").system_id'" % (self.cfg.profile, mac)
        sys_id = None
        log.info('Waiting for instance to be ready for commision')
        while not sys_id:
            time.sleep(5)
            sys_id = moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s node update %s power_change=on power_type=nova \
               power_parameters_nova_id=%s \
               power_parameters_os_tenantname=%s \
               power_parameters_os_username=%s \
               power_parameters_os_password=%s \
               power_parameters_os_authurl=%s \
               power_parameters_os_project_domain_name=%s \
               power_parameters_os_user_domain_name=%s" % (self.cfg.profile, sys_id, instance_id,
                                                  self.cfg.credentials['project_name'],
                                                  self.cfg.credentials['username'],
                                                  self.cfg.credentials['password'],
                                                  self.cfg.credentials['auth_url'],
                                                  self.cfg.credentials['project_domain_name'],
                                                  self.cfg.credentials['user_domain_name'])
        print cmd
        moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s machine update %s hostname=%s" % (self.cfg.profile, sys_id, instance_name)
        moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s tag read %s" % (self.cfg.profile, tag)
        ret = moo.fabric.RunCommand(self.cfg, host, cmd)
        if ret == "Not Found":
            cmd = "maas %s tags create name=%s" % (self.cfg.profile, tag)
            log.debug('new tag created: %s' % tag)
            moo.fabric.RunCommand(self.cfg, host, cmd)
        cmd = "maas %s tag update-nodes %s add=%s" % (self.cfg.profile, tag, sys_id)
        moo.fabric.RunCommand(self.cfg, host, cmd)
        log.info('%s has been added to MAAS' % instance_name)

    def GetVersion(self, host):
        cmd = "maas %s version read | jq -r .version" % (self.cfg.profile)
        ret = moo.fabric.RunCommand(self.cfg, host, cmd)
        return ret
