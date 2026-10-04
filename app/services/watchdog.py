# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only probes. Recovery and provisioning cannot execute through this service."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

class ResourceKind(StrEnum):
    PROXMOX_NODE = 'proxmox-node'
    PROXMOX_VM = 'proxmox-vm'
    APPLICATION = 'application'
    DATABASE = 'database'
    HOST = 'host'
    DNS = 'dns'
    MAIL = 'mail'
    BACKUP = 'backup'
    WIREGUARD = 'wireguard'
    EDGE = 'edge'
    NETWORK = 'network'

class ExpectedState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    ON_DEMAND = "on-demand"
    POLICY_CONTROLLED = "policy-controlled"

class ProbeKind(StrEnum):
    PROXMOX_NODE = 'proxmox-node'
    PROXMOX_VM = 'proxmox-vm'
    SERVICE = 'service'
    HTTP = 'http-health'
    DATABASE = 'database-reachability'
    DISK = 'disk-usage'
    CPU = 'cpu-pressure'
    MEMORY = 'memory-pressure'
    TLS = 'tls-certificate'
    DNS = 'dns'
    MAIL = 'mail'
    BACKUP = 'postgres-backup-wal'
    WIREGUARD = 'wireguard'
    EDGE = 'edge'
    NETWORK = 'network-reachability'

class HealthStatus(StrEnum):
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'
    UNKNOWN = 'unknown'

@dataclass(frozen=True)
class ProbeResult:
    status: HealthStatus
    summary: str

class Probe(Protocol):
    supported_resources: frozenset[ResourceKind]
    def observe(self, resource) -> ProbeResult: ...

class ProbeRegistry:
    def __init__(self):
        self._probes: dict[ProbeKind, Probe] = {}

    def register(self, kind: ProbeKind, probe: Probe):
        if kind in self._probes:
            raise ValueError('Probe already registered')
        self._probes[kind] = probe

    def observe(self, kind: ProbeKind, resource) -> ProbeResult:
        probe = self._probes.get(kind)
        if not probe:
            return ProbeResult(HealthStatus.UNKNOWN, 'Monitoring adapter is not configured')
        if resource.kind not in probe.supported_resources:
            return ProbeResult(HealthStatus.UNKNOWN, 'Probe does not support this resource kind')
        try:
            result = probe.observe(resource)
            if not isinstance(result, ProbeResult) or not isinstance(result.status, HealthStatus):
                raise ValueError('Invalid probe result')
            return result
        except Exception:
            # Provider errors can contain credential-bearing URLs or headers.
            return ProbeResult(HealthStatus.UNKNOWN, 'Monitoring adapter could not verify resource health')

class ProxmoxVMProbe:
    supported_resources = frozenset({ResourceKind.PROXMOX_VM})
    def __init__(self, client_factory):
        self.client_factory = client_factory

    def observe(self, resource):
        if not resource.node or not resource.vm_id:
            return ProbeResult(HealthStatus.UNKNOWN, 'VM identity is not configured')
        client = self.client_factory()
        try:
            state = client.status(resource.node, resource.vm_id).get('status')
            if state not in {'running', 'stopped', 'paused'}:
                return ProbeResult(HealthStatus.UNKNOWN, 'Proxmox returned an unknown power state')
            expected = resource.expected_state
            if expected in {ExpectedState.ON_DEMAND, ExpectedState.POLICY_CONTROLLED}:
                status = HealthStatus.UNKNOWN
            else:
                status = HealthStatus.HEALTHY if state == expected else HealthStatus.UNHEALTHY
            return ProbeResult(status, "VM power state: " + state + "; expected state: " + expected + "; guest readiness is unverified")
        finally:
            client.close()

def observation_view(observation, freshness_seconds, current_time=None):
    if observation is None:
        return {'status': 'unknown', 'summary': 'No observation yet', 'observed_at': None, 'stale': True}
    current_time = current_time or datetime.now(timezone.utc)
    timestamp = observation.observed_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    stale = (current_time - timestamp).total_seconds() > freshness_seconds
    return {'status': 'unknown' if stale else observation.status, 'summary': 'Observation expired; run a fresh check' if stale else observation.summary, 'observed_at': timestamp, 'stale': stale}
