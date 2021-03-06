import urllib.request
import time
import re
from moo.utils import CreateSSHKey
from moo.logging import Logging
from pathlib import Path
import novaclient.client as novaclient
from neutronclient.v2_0 import client as neutronclient
import neutronclient.neutron.v2_0 as neutronv2
import neutronclient.common.exceptions as neutronexceptions
from glanceclient import client as glanceclient
from keystoneauth1.identity import v3
from keystoneauth1 import session, exceptions

LOG = Logging(__name__)
log = LOG.getLogger()


class OpenstackUtils:
    """OpenStack Utils Class"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.credentials = self.cfg.credentials
        self.keystonecredentials = self.cfg.keystonecredentials
        LOG.SetLevel(self.cfg.log_level)

    def Init(self):
        self.auth = v3.Password(**self.keystonecredentials)
        if self.CheckAuth():
            self._initialize_clients()
            self.cfg.xenial_image = self.GetXenialImg()
            self.cfg.trusty_image = self.GetTrustyImg()
            return True
        return False

    def CheckAuth(self):
        """Check if credential info are correct"""
        try:
            urllib.request.urlopen(self.credentials["auth_url"])
        except urllib.request.HTTPError:
            log.error('Auth URL error: %s' %
                      self.credentials["auth_url"])
            return False
        try:
            sess = session.Session(auth=self.auth)
            sess.get(self.credentials['auth_url'])
        except exceptions.http.Unauthorized:
            print('Failed to authorized credentials')
            return False
        return True

    def _initialize_clients(self):
        sess = session.Session(auth=self.auth)
#         self.neutron = neutronclient.Client(**self.credentials)
        self.neutron = neutronclient.Client(session=sess)
        self.nova = novaclient.Client(2, session=sess)
        self.glance = glanceclient.Client(2, endpoint=sess.get_endpoint(service_type='image'), session=sess)

    def CheckDuplicateNetwork(self, cidr, name):
        """Check for possible duplicate network name and cidr"""
        subn = self.neutron.list_subnets()
        for i in range(len(subn['subnets'])):
            if cidr == subn['subnets'][i]['cidr']:
                log.warning('Duplicate subnet found: %s' % cidr)
                return True
        netw = self.neutron.list_networks()
        for i in range(len(netw['networks'])):
            if name == netw['networks'][i]['name']:
                log.warning('Duplicate network found: %s' % name)
                return True

    def CreateNetwork(self, cidr, name, port_security=False):
        """Create Network(network, subnet, router)"""
        if self.CheckDuplicateNetwork(cidr, name):
            return False
        ipv = 4
        # Create network
        try:
            body_netw = {'network': {'name': name,
                                     'port_security_enabled': port_security,
                                     'admin_state_up': True}}
            ret = self.neutron.create_network(body=body_netw)
        finally:
            log.debug('Create Network: %s' % name)
        try:
            # Create subnet
            network_id = ret['network']['id']
            subnet_name = name + "_subnet"
            body_subn = {'subnets': [{
                         'cidr': cidr,
                         'ip_version': ipv,
                         'name': subnet_name,
                         'enable_dhcp': False,
                         'network_id': network_id}]}
            ret = self.neutron.create_subnet(body=body_subn)
        finally:
            log.debug('Create subnet: %s' % subnet_name)
        try:
            subnet_id = ret['subnets'][0]['id']
            router_name = name + "_router"
            body_rt = {'router': {
                       'name': router_name,
                       'admin_state_up': True}}
            ret = self.neutron.create_router(body_rt)
        finally:
            log.debug('Create router: %s' % router_name)
        try:
            ext_net_id = self.GetNetID(self.cfg.ext_net)
            router_id = ret['router']['id']
            body_rt = {'network_id': ext_net_id}
            self.neutron.add_gateway_router(router_id, body_rt)
        finally:
            log.debug('Add external gateway to router')
        try:
            body_rt = {'subnet_id': subnet_id}
            ret = self.neutron.add_interface_router(router_id, body_rt)
        finally:
            log.debug('Add subnet interface to router')
        return True

    def GetNetID(self, network_name):
        try:
            detail = neutronv2.find_resource_by_name_or_id(self.neutron, 'network', network_name)
        except neutronexceptions.NotFound as e:
            log.error(e)
            return e
        return detail['id']

    def GetInstanceID(self, instance_name, disable_log=False):
        try:
            instance_id = self.nova.servers.find(name=instance_name).id
        except novaclient.exceptions.NotFound as e:
            if disable_log is False:
                log.error(e)
            return False
        return instance_id

    def GetIP(self, name, network_name):
        try:
            ips = self.nova.servers.ips(self.nova.servers.find(name=name))
        except novaclient.exceptions.NotFound as e:
            log.error(e)
            return False
        ip = ips[network_name][0]['addr']
        return ip

    def GetFlavor(self, flavor_name):
        try:
            flavor = self.nova.flavors.find(name=flavor_name)
        except novaclient.exceptions.NotFound as e:
            log.error(e)
            return False
        return flavor

    def GetImageID(self, image_name):
        try:
            image = self.nova.glance.find_image(name_or_id=image_name)
        except novaclient.exceptions.NotFound as e:
            log.error(e)
            return False
        return image.id

    def GetXenialImg(self):
        for image in self.glance.images.list():
            if 'daily' in image['name']:
                continue
            elif 'xenial' in image['name']:
                xenial_id = image['id']
                return xenial_id
            else:
                continue
        log.error("ERROR: Xenial image not found.")
        return False

    def GetTrustyImg(self):
        for image in self.glance.images.list():
            if 'daily' in image['name']:
                continue
            elif 'trusty' in image['name']:
                xenial_id = image['id']
                return xenial_id
            else:
                continue
        log.error("ERROR: Trusty image not found.")
        return False

    def GetMAC(self, instance_id):
        ports = self.neutron.list_ports()
        for port in ports['ports']:
            if port['device_id'] == instance_id:
                return port['mac_address']
        return False

    def KeyExist(self, keyname):
        try:
            self.nova.keypairs.find(name=keyname)
        except novaclient.exceptions.NotFound:
            return False
        return True

    def CreateKeyPair(self, keyname):
        log.debug('Create keypair as %s' % keyname)
        if self.KeyExist(keyname):
            keypath = Path(self.cfg.configpath).joinpath(self.cfg.keypath)
            keypath = Path(keypath).joinpath(self.cfg.keyname)
            if not keypath.is_file():
                log.error('ERROR: keypair in OpenStack exists, but key file not found.')
                log.error('%s' % keypath)
                return False
            log.debug('Keypair already exists ... skip creating')
            return True
        else:
            pubkey = CreateSSHKey(keyname, self.cfg.keypath)
            self.nova.keypairs.create(keyname, pubkey)
        return True

    def BootInstance(self, name, image, instance_nics, flavor='m1.small',
                     cloud_cfg_file=None, config_drive=None, src=None, dst=None):
        flavor = self.GetFlavor(flavor)
        key = self.cfg.keyname
        image_id = self.GetImageID(image)
        files = {}
        userdata = None
        if self.GetInstanceID(name, True):
            log.error('ERROR:Could not create instance. Instance already exist: %s' % name)
            return False
        if cloud_cfg_file:
            try:
                userdata = open(cloud_cfg_file)
            except IOError as e:
                log.error("Can't open '%s': %s" % cloud_cfg_file, e)
                return False
        if src or dst:
            try:
                files[dst] = open(src, 'rb')
            except IOError as e:
                log.error("Can't open '%s': %s" % src, e)
                return False
        try:
            instance = self.nova.servers.create(name, image_id, flavor,
                                                userdata=userdata,
                                                key_name=key,
                                                nics=instance_nics,
                                                files=files,
                                                config_drive=config_drive)
        finally:
            # Clean up open files - make sure they are not strings
            for f in files:
                if hasattr(f, 'close'):
                    f.close()
            if hasattr(userdata, 'close'):
                userdata.close()
        while instance.status == 'BUILD':
            log.info("Waiting for instance to be active.")
            time.sleep(10)
            instance = self.nova.servers.get(instance.id)
        return True

    def WaitCloudInit(self, instance_name):
        instance = self.GetInstanceID(instance_name)
        console_log = self.nova.servers.get_console_output(instance, 10)
        pattern = "Cloud-init v.* finished at"
        log.info("Waiting for cloud-init to finish. This will take a while...")
        while not re.search(pattern, console_log):
            time.sleep(10)
            console_log = self.nova.servers.get_console_output(instance, 10)

    def CreatePort(self, network_name, port_sec=False):
        net_id = self.GetNetID(network_name)
        # Create port
        try:
            body = {
                        'port': {
                                'admin_state_up': True,
                                'network_id': net_id,
                                'port_security_enabled': port_sec
                        }
                    }
            ret = self.neutron.create_port(body=body)
        finally:
            log.debug('Create port for network:%s' % network_name)
        return ret['port']['id']
