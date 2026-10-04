# SPDX-License-Identifier: AGPL-3.0-only
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from app.services.watchdog import ProbeRegistry, ProbeKind, ResourceKind, HealthStatus, ProxmoxVMProbe, observation_view
from app.services.providers import CachePolicy, EdgeRolloutPlan, TemplateProvisioningPlan, ExposurePolicy, NetworkProfile, RecoveryPolicy
from pydantic import ValidationError

class WatchdogTests(unittest.TestCase):
    def test_expected_state_never_powers_vm(self):
        client=Mock()
        client.status.return_value={'status':'stopped'}
        registry=ProbeRegistry()
        registry.register(ProbeKind.PROXMOX_VM,ProxmoxVMProbe(lambda:client))
        resource=SimpleNamespace(kind=ResourceKind.PROXMOX_VM,node='builder',vm_id=115,expected_state='on-demand')
        self.assertEqual(registry.observe(ProbeKind.PROXMOX_VM,resource).status,HealthStatus.UNKNOWN)
        resource.expected_state='running'
        self.assertEqual(registry.observe(ProbeKind.PROXMOX_VM,resource).status,HealthStatus.UNHEALTHY)
        resource.expected_state='stopped'
        self.assertEqual(registry.observe(ProbeKind.PROXMOX_VM,resource).status,HealthStatus.HEALTHY)
        client.start.assert_not_called()
        client.shutdown.assert_not_called()
        self.assertEqual(client.close.call_count,3)

    def test_missing_failed_and_stale_observations_are_unknown(self):
        registry=ProbeRegistry()
        resource=SimpleNamespace(kind='proxmox-vm',node='builder',vm_id=115,expected_state='running')
        self.assertEqual(registry.observe(ProbeKind.TLS,resource).status,HealthStatus.UNKNOWN)
        client=Mock()
        client.status.side_effect=RuntimeError('secret credential in provider error')
        registry.register(ProbeKind.PROXMOX_VM,ProxmoxVMProbe(lambda:client))
        result=registry.observe(ProbeKind.PROXMOX_VM,resource)
        self.assertEqual(result.status,HealthStatus.UNKNOWN)
        self.assertNotIn('secret',result.summary)
        stamp=datetime.now(timezone.utc)
        old=SimpleNamespace(status='healthy',summary='healthy',observed_at=stamp-timedelta(seconds=301))
        self.assertEqual(observation_view(old,300,stamp)['status'],'unknown')
        self.assertTrue(observation_view(None,300)['stale'])

    def test_future_contracts_keep_safe_defaults(self):
        self.assertFalse(CachePolicy().enabled)
        self.assertEqual(ExposurePolicy().mode,'lan-only')
        self.assertFalse(RecoveryPolicy(action='start-vm').enabled)
        self.assertEqual(NetworkProfile(name='default').wireguard_cidr,'10.20.0.0/24')
        with self.assertRaises(ValidationError):
            CachePolicy(enabled=True,public_path_allowlist=('/*',),ttl_seconds=60)
        with self.assertRaises(ValidationError):
            CachePolicy(enabled=True,public_path_allowlist=('/assets/',),ttl_seconds=60,bypass_authenticated=False)
        with self.assertRaises(ValidationError):
            TemplateProvisioningPlan(node='builder',template_vm_id=115,target_vm_id=115,hostname='test',network_profile='private',client_enrollment_ref='enroll')
        configuration={'version':'1','sha256':'a'*64,'artifact_ref':'edge/config/1'}
        plan=EdgeRolloutPlan(configuration=configuration,validation_node_id='custom-region',promotion_node_ids=('other-region',))
        self.assertEqual(plan.configuration.sha256,'a'*64)
        with self.assertRaises(ValidationError):
            EdgeRolloutPlan(configuration=configuration,validation_node_id='same',promotion_node_ids=('same',))
