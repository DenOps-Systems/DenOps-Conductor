# SPDX-License-Identifier: AGPL-3.0-only
import unittest
from app.services.deployment import ApprovedRelease, DeploymentWorkflow, DeploymentBlocked

class FakePublisher:
    def __init__(self, healthy=True, stopped=True):
        self.actions=[]
        self.health=healthy
        self.stopped=stopped
    def event(self, action, detail=''):
        self.actions.append(action)
    def acquire_deployment_lock(self, release): self.actions.append('lock')
    def release_deployment_lock(self): self.actions.append('unlock')
    def verify_release(self, release): self.actions.append('verify')
    def migrate(self, release): self.actions.append('migrate'); return 5
    def activate(self, release): self.actions.append('activate')
    def restart(self, release): self.actions.append('restart')
    def healthy(self, release): return self.health
    def persist_success(self, release, version): self.actions.append('persist')
    def verify_persisted_success(self, release): return True
    def previous_release_compatible(self, release): return True
    def restore_previous_application(self, release): self.actions.append('restore')
    def graceful_shutdown(self, vm_id): self.actions.append('shutdown')
    def wait_until_stopped(self, vm_id): return self.stopped
    def complete_final_sync(self, release, version): self.actions.append('slot-released')

class DeploymentTests(unittest.TestCase):
    def test_final_sync_requires_verified_deployment(self):
        publisher=FakePublisher(healthy=False)
        with self.assertRaises(DeploymentBlocked):
            DeploymentWorkflow().run(ApprovedRelease(1,'a'*40,101,True),publisher)
        self.assertNotIn('shutdown',publisher.actions)
        self.assertNotIn('slot-released',publisher.actions)
        self.assertIn('restore',publisher.actions)
        self.assertEqual(publisher.actions[-1],'unlock')

    def test_shutdown_must_be_confirmed(self):
        publisher=FakePublisher(stopped=False)
        with self.assertRaises(DeploymentBlocked):
            DeploymentWorkflow().run(ApprovedRelease(1,'a'*40,101,True),publisher)
        self.assertNotIn('slot-released',publisher.actions)
        self.assertNotIn('restore',publisher.actions)
        self.assertLess(publisher.actions.index('persist'),publisher.actions.index('shutdown'))

    def test_normal_sync_keeps_vm_running(self):
        publisher=FakePublisher()
        self.assertEqual(DeploymentWorkflow().run(ApprovedRelease(1,'a'*40,101),publisher),5)
        self.assertNotIn('shutdown',publisher.actions)

    def test_successful_final_sync_releases_slot_last(self):
        publisher=FakePublisher()
        DeploymentWorkflow().run(ApprovedRelease(1,'a'*40,101,True),publisher)
        self.assertLess(publisher.actions.index('shutdown'),publisher.actions.index('slot-released'))
