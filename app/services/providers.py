# SPDX-License-Identifier: AGPL-3.0-only
"""Provider contracts for future modules. No provisioning or Edge execution here."""
from typing import Protocol, Literal
from ipaddress import ip_network
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

class TemplateProvisioningPlan(Contract):
    node: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    template_vm_id: int = Field(gt=0)
    target_vm_id: int = Field(gt=0)
    hostname: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$')
    network_profile: str = Field(min_length=1, max_length=120)
    authorized_ssh_key_refs: tuple[str, ...] = ()
    require_guest_agent: bool = True
    client_enrollment_ref: str = Field(min_length=1, max_length=120)

    @model_validator(mode='after')
    def distinct_vm_ids(self):
        if self.template_vm_id == self.target_vm_id:
            raise ValueError('Template and target VM must differ')
        return self

class VMProvider(Protocol):
    def status(self, node: str, vm_id: int) -> dict: ...
    def start(self, node: str, vm_id: int) -> str: ...
    def shutdown(self, node: str, vm_id: int) -> str: ...
    def guest_status(self, node: str, vm_id: int): ...

class ProvisioningProvider(Protocol):
    def clone_template(self, plan: TemplateProvisioningPlan) -> str: ...
    def configure_cloud_init(self, plan: TemplateProvisioningPlan) -> str: ...
    def task_status(self, node: str, task_id: str) -> dict: ...

class ExposurePolicy(Contract):
    mode: Literal['lan-only', 'wireguard-only', 'cloudflare-tunnel', 'cloudflare-proxied', 'denops-edge', 'direct-proxy', 'custom'] = 'lan-only'
    provider_ref: str | None = None
    hostname: str | None = None
    edge_node_ids: tuple[str, ...] = ()

class CachePolicy(Contract):
    enabled: bool = False
    public_path_allowlist: tuple[str, ...] = ()
    bypass_authenticated: Literal[True] = True
    bypass_personalized: Literal[True] = True
    bypass_sensitive: Literal[True] = True
    ttl_seconds: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def explicit_public_paths(self):
        if self.enabled and (not self.public_path_allowlist or self.ttl_seconds == 0):
            raise ValueError('Enabled caching requires explicit public paths and a TTL')
        if any(not path.startswith('/') or path in {'/', '/*', '/**'} for path in self.public_path_allowlist):
            raise ValueError('Cache paths must be explicit; cache-everything is prohibited')
        return self

class EdgeNodeSpec(Contract):
    node_id: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    provider_ref: str = Field(min_length=1, max_length=120)
    location: str | None = None
    serves_production: bool = True
    maintenance: bool = False

class EdgeConfigurationRef(Contract):
    version: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    artifact_ref: str = Field(min_length=1, max_length=500)

class EdgeRolloutPlan(Contract):
    configuration: EdgeConfigurationRef
    validation_node_id: str
    promotion_node_ids: tuple[str, ...]

    @model_validator(mode='after')
    def unique_targets(self):
        nodes = (self.validation_node_id, *self.promotion_node_ids)
        if any(not node for node in nodes) or len(set(nodes)) != len(nodes):
            raise ValueError('Rollout node identities must be nonempty and unique')
        return self

class NetworkProfile(Contract):
    name: str
    wireguard_cidr: str = '10.20.0.0/24'
    lan_cidr: str = '192.168.0.0/16'

    @model_validator(mode='after')
    def valid_networks(self):
        ip_network(self.wireguard_cidr)
        ip_network(self.lan_cidr)
        return self

class DNSProvider(Protocol):
    def validate(self, policy: ExposurePolicy) -> bool: ...
    def apply(self, policy: ExposurePolicy, approved_change_id: str) -> str: ...

class EdgeProvider(Protocol):
    def validate(self, node_id: str, configuration: EdgeConfigurationRef) -> bool: ...
    def apply(self, node_id: str, configuration: EdgeConfigurationRef, approved_change_id: str) -> str: ...
    def health(self, node_id: str) -> dict: ...
    def invalidate(self, release_id: int, public_paths: tuple[str, ...], approved_change_id: str) -> str: ...

class RecoveryPolicy(Contract):
    enabled: bool = False
    action: Literal['restart-service', 'start-vm', 'verify-recovery', 'create-repair', 'notify-admin']
    requires_approval: bool = True
    max_attempts: int = Field(default=1, ge=1, le=10)
    cooldown_seconds: int = Field(default=300, ge=30)
