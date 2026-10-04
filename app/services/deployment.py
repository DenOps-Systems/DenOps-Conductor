# SPDX-License-Identifier: AGPL-3.0-only
"""Fail-closed release sequencing over publisher-owned infrastructure adapters."""
from typing import Protocol
from dataclasses import dataclass
import re

class DeploymentBlocked(RuntimeError):
    pass

@dataclass(frozen=True)
class ApprovedRelease:
    project_id: int
    commit: str
    vm_id: int
    final_sync: bool = False

class Publisher(Protocol):
    def event(self, action: str, detail: str = '') -> None: ...
    def acquire_deployment_lock(self, release: ApprovedRelease) -> None: ...
    def release_deployment_lock(self) -> None: ...
    def verify_release(self, release: ApprovedRelease) -> None: ...
    def migrate(self, release: ApprovedRelease) -> int: ...
    def activate(self, release: ApprovedRelease) -> None: ...
    def restart(self, release: ApprovedRelease) -> None: ...
    def healthy(self, release: ApprovedRelease) -> bool: ...
    def persist_success(self, release: ApprovedRelease, migration_version: int) -> None: ...
    def verify_persisted_success(self, release: ApprovedRelease) -> bool: ...
    def previous_release_compatible(self, release: ApprovedRelease) -> bool: ...
    def restore_previous_application(self, release: ApprovedRelease) -> None: ...
    def graceful_shutdown(self, vm_id: int) -> None: ...
    def wait_until_stopped(self, vm_id: int) -> bool: ...
    def complete_final_sync(self, release: ApprovedRelease, migration_version: int) -> None: ...

class DeploymentWorkflow:
    """No direct API exposure until concrete adapters and approval records exist."""
    def run(self, release: ApprovedRelease, publisher: Publisher):
        if not re.fullmatch('[a-f0-9]{40}', release.commit) or release.vm_id <= 0:
            raise DeploymentBlocked('Exact release commit and builder identity required')
        locked = False
        activated = False
        application_verified = False
        try:
            publisher.acquire_deployment_lock(release)
            locked = True
            publisher.event('deployment-started', release.commit)
            publisher.verify_release(release)
            publisher.event('release-verified')
            version = publisher.migrate(release)
            publisher.event('migrations-completed', str(version))
            # Activation can fail after partially switching the current link.
            activated = True
            publisher.activate(release)
            publisher.restart(release)
            if publisher.healthy(release) is not True:
                raise DeploymentBlocked('Release health check failed')
            publisher.persist_success(release, version)
            if publisher.verify_persisted_success(release) is not True:
                raise DeploymentBlocked('Persisted release success could not be verified')
            application_verified = True
            publisher.event('deployment-verified', release.commit)
            if release.final_sync:
                publisher.graceful_shutdown(release.vm_id)
                if publisher.wait_until_stopped(release.vm_id) is not True:
                    raise DeploymentBlocked('VM shutdown unconfirmed; Alpha slot remains reserved')
                # Atomically records commit, version and VM, completes repair and
                # releases Alpha. Only reached after observed stopped power state.
                publisher.complete_final_sync(release, version)
                publisher.event('final-sync-completed')
            return version
        except Exception as error:
            publisher.event('deployment-failed', str(error))
            if activated and not application_verified:
                if publisher.previous_release_compatible(release) is True:
                    publisher.restore_previous_application(release)
                    publisher.event('previous-application-restored')
                else:
                    publisher.event('restoration-needs-review')
            raise
        finally:
            if locked:
                publisher.release_deployment_lock()
