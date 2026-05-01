import os
import re
import atexit
import logging

from pathlib import Path
from functools import cache
from typing import overload
from paramiko import SSHConfig
from pydantic import model_validator
from sshtunnel import SSHTunnelForwarder

from .helper_funcs import get_available_port, is_own_ip

from ..type_utils.base_clses import AdvancedBaseModel

def _get_env(key, default=None)->str|None:
    return os.environ.get(key, default)

_logger = logging.getLogger(__name__)

_remote_tunnels: dict[tuple[str, str, int, int|None], SSHTunnelForwarder] = {}   # {(ssh_ip, remote_ip, remote_port, target_local_port): SSHTunnelForwarder}
_LOCALHOST = '127.0.0.1'
try:
    _DEFAULT_SSH_PORT = _get_env('SSH_PORT', '22')  # type: ignore
    _DEFAULT_SSH_PORT = int(_DEFAULT_SSH_PORT)  # type: ignore  
except ValueError:
    _DEFAULT_SSH_PORT: int = 22
_DEFAULT_SSH_USERNAME = _get_env('SSH_USERNAME') or 'root'

_ssh_full_pattern = re.compile(r'^(?:(?P<user>[^:@]+)(?::(?P<pw>[^@]+))?@)?(?P<ip>[^:]+)(?::(?P<port>\d+))?$')

def _get_default_ssh_key_path() -> str|None:
    if keypath:= _get_env('SSH_KEY_PATH'):
        if os.path.exists(keypath):
            return keypath
    if key:= _get_env('SSH_KEY'):
        count = 0
        while os.path.exists(os.path.join(os.path.expanduser("~"), ".ssh", f".proj_temp_ssh_key_{count}")):
            count += 1
        temp_key_path = os.path.join(os.path.expanduser("~"), ".ssh", f".proj_temp_ssh_key_{count}")
        with open(temp_key_path, 'w') as f:
            f.write(key)
        os.chmod(temp_key_path, 0o600)
        return temp_key_path
    home = os.path.expanduser("~")
    default_key = os.path.join(home, ".ssh", "id_rsa")
    if os.path.exists(default_key):
        return default_key
    default_key = os.path.join(home, ".ssh", "id_ed25519")
    if os.path.exists(default_key):
        return default_key
    return None

@cache
def _get_default_ssh_config():
    ssh_config_path = os.path.expanduser("~/.ssh/config")
    if not os.path.exists(ssh_config_path):
        return None
    with open(ssh_config_path) as f:
        config = SSHConfig()
        try:
            config.parse(f)
            return config
        except Exception as e:
            _logger.warning(f'Failed to parse SSH config file. {type(e).__name__}: {e}')
            return None

def _find_ssh_config(ssh_ip: str)->tuple[int, str, str|None]|None:    # (port, username, key_path)
    # find ssh config from .ssh/config file
    config = _get_default_ssh_config()
    if not config:
        return None
    host_config = config.lookup(ssh_ip)
    if not host_config:
        return None
    if len(host_config) ==1 and 'hostname' in host_config:
        return None
    try:
        port = int(host_config.get('port', _DEFAULT_SSH_PORT))  # type: ignore
    except:
        port = _DEFAULT_SSH_PORT
    username = host_config.get('user', _DEFAULT_SSH_USERNAME)
    key_path = host_config.get('identityfile', [None])[0]
    if not key_path:
        key_path = _get_default_ssh_key_path()
    return port, username, key_path

def _start_ssh_tunnel_server(
    ssh_ip:str,
    ssh_remote_port:int,
    ssh_remote_ip:str=_LOCALHOST,
    ssh_port:int|None=None,
    ssh_user:str|None=None,
    ssh_pw: str|None=None,
    ssh_key_path: str|Path|None=None,
    local_port:int|None=None
):  # type: ignore
    if not ssh_port or not ssh_user or (not ssh_key_path or not ssh_pw):
        if config:=_find_ssh_config(ssh_ip):
            ssh_port_config, ssh_user_config, ssh_key_path_config = config
            if not ssh_port:
                ssh_port = ssh_port_config
            if not ssh_user:
                ssh_user = ssh_user_config
            if not ssh_key_path and not ssh_pw:
                ssh_key_path = ssh_key_path_config
        else:
            ssh_port = ssh_port or _DEFAULT_SSH_PORT
            ssh_user = ssh_user or _DEFAULT_SSH_USERNAME
            if not ssh_key_path and not ssh_pw:
                ssh_key_path = _get_default_ssh_key_path()
    
    if not ssh_key_path and not ssh_pw:
        if env_pw:= _get_env('SSH_PW'):
            ssh_pw = env_pw
        else:
            raise ValueError('No SSH key path or password provided, and none found in SSH config or environment variables.')
    
    if tunnel:=_remote_tunnels.get((ssh_ip, ssh_remote_ip, ssh_remote_port, local_port)):
        return tunnel.local_bind_port
    
    target_port = local_port if local_port is not None else get_available_port()
    t = SSHTunnelForwarder(
        ssh_address_or_host=(ssh_ip, ssh_port),
        ssh_username=ssh_user,
        ssh_password=ssh_pw,
        ssh_pkey=ssh_key_path,
        remote_bind_address=(ssh_remote_ip, ssh_remote_port),
        local_bind_address=(_LOCALHOST, target_port),
    )
    _remote_tunnels[(ssh_ip, ssh_remote_ip, ssh_remote_port, local_port)] = t
    t.start()
    return target_port

def stop_remote_clients():
    for client in tuple(_remote_tunnels.values()):
        client.stop()

atexit.register(stop_remote_clients)


# ---------------------------------------------------------------------------
# SSHTunnelConfig
# ---------------------------------------------------------------------------

class SSHTunnelConfig(AdvancedBaseModel):
    """SSH tunnel configuration.

    Field defaults are ``None`` so that values from ``~/.ssh/config`` and
    environment variables are not accidentally overridden (e.g. a hard-coded
    ``ssh_port=22`` would shadow the port in the user's SSH config).

    When attached to a remote-service config the connection URL / endpoint is
    rewritten to point at the locally-forwarded port **before** the client is
    created.  Tunnel state is managed by :func:`get_remote_forward_tunnel`
    which reuses existing tunnels automatically.

    Accepts a plain ``str`` as input — it is interpreted as the ``ssh_host``
    (i.e. a Host entry in ``~/.ssh/config`` or hostname/IP).
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data):
        if isinstance(data, str):
            return {"ssh_host": data}
        return data

    ssh_host: str
    """SSH server hostname or IP (also accepts ``user[:pw]@host[:port]`` shorthand)."""
    ssh_port: int | None = None
    """SSH server port.  ``None`` → resolved from ``~/.ssh/config`` or ``SSH_PORT`` env-var."""
    ssh_user: str | None = None
    """SSH login username.  ``None`` → resolved from ``~/.ssh/config`` or ``SSH_USERNAME`` env-var."""
    ssh_pw: str | None = None
    """SSH password.  ``None`` → resolved from ``SSH_PW`` env-var."""
    ssh_key_path: str | None = None
    """Path to the SSH private key.  ``None`` → resolved from env-vars / ``~/.ssh/id_*``."""
    remote_ip: str = _LOCALHOST
    """IP of the target service *as seen from the SSH server*.  Default: loopback."""
    remote_port: int | None = None
    """Port of the target service *as seen from the SSH server*.  ``None`` → must be supplied to :meth:`open_tunnel`."""
    local_port: int | None = None
    """Fixed local port to bind.  ``None`` → auto-picks an available port."""

    def open_tunnel(self, remote_port: int | None = None) -> int:
        """Ensure an SSH tunnel to *remote_port* is running and return the local port.

        Args:
            remote_port: Override ``self.remote_port`` if given.
        """
        port = remote_port if remote_port is not None else self.remote_port
        if port is None:
            raise ValueError('remote_port is required: not set on SSHTunnelConfig and not passed to open_tunnel()')
        self.remote_port = port
        return get_remote_forward_tunnel(self)


@overload
def get_remote_forward_tunnel(
    ssh_ip_or_host: str,
    ssh_remote_port: int,
    ssh_remote_ip: str = ...,
    ssh_port: int | None = ...,
    ssh_user: str | None = ...,
    ssh_pw: str | None = ...,
    ssh_key_path: str | Path | None = ...,
    local_port: int | None = ...,
) -> int: ...

@overload
def get_remote_forward_tunnel(
    ssh_ip_or_host: SSHTunnelConfig,
) -> int: ...

def get_remote_forward_tunnel(
    ssh_ip_or_host: str | SSHTunnelConfig,
    ssh_remote_port: int | None = None,
    ssh_remote_ip: str = _LOCALHOST,
    ssh_port: int | None = None,
    ssh_user: str | None = None,
    ssh_pw: str | None = None,
    ssh_key_path: str | Path | None = None,
    local_port: int | None = None,
) -> int:
    '''
    Create or get a port forwarding to the given remote ip and remote port.

    If *ssh_ip_or_host* is an :class:`SSHTunnelConfig` instance, all SSH
    parameters are extracted from it (remaining keyword arguments are ignored).

    When the resolved SSH host turns out to be this machine's own local or
    public IP, the tunnel is skipped entirely and *ssh_remote_port* is returned
    as-is.

    Args:
        ssh_ip_or_host: ssh ip / host to connect to **or** an ``SSHTunnelConfig``.
                    If a string, ``user[:pw]@host[:port]`` shorthand is supported.
                    If it can be found in ssh config file(~/.ssh/config), the port, username and key path will also be parsed out.
        ssh_remote_port: remote port to forward to.
        ssh_remote_ip: remote ip to forward to. Default to `localhost` of the remote server.
        ssh_port: ssh port to connect to.
        ssh_user: ssh username to connect to the remote server.
        ssh_pw: ssh password to connect to the remote server.
        ssh_key_path: ssh private key path to connect to the remote server.
        local_port: if given, will try to forward to this port, if not given, will find an available port to forward to.

    Available env variables:
        SSH_PORT: default ssh port to connect to.
        SSH_USERNAME: default ssh username to connect to.
        SSH_KEY_PATH: default ssh private key path to connect to.
        SSH_KEY: default ssh private key content to connect to.
        SSH_PW: default ssh password to connect to.

    Returns:
        The final local port used for forwarding.
    '''
    # ── unpack SSHTunnelConfig ────────────────────────────────────────────
    ssh_host: str
    if isinstance(ssh_ip_or_host, SSHTunnelConfig):
        cfg = ssh_ip_or_host
        ssh_host = cfg.ssh_host
        if cfg.remote_port is not None and ssh_remote_port is None:
            ssh_remote_port = cfg.remote_port
        ssh_remote_ip = cfg.remote_ip
        ssh_port = cfg.ssh_port
        ssh_user = cfg.ssh_user
        ssh_pw = cfg.ssh_pw
        ssh_key_path = cfg.ssh_key_path
        local_port = cfg.local_port
    else:
        ssh_host = ssh_ip_or_host

    if ssh_remote_port is None:
        raise ValueError('ssh_remote_port is required')
    if not ssh_host:
        raise ValueError(f'Invalid remote ip or host: `{ssh_host}`')

    if m := _ssh_full_pattern.match(ssh_host):
        user = m.group('user')
        pw = m.group('pw')
        ip = m.group('ip')
        port_str = m.group('port')
        if user and not ssh_user:
            ssh_user = user
        if pw and not ssh_pw:
            ssh_pw = pw
        ssh_host = ip
        if port_str and not ssh_port:
            try:
                ssh_port = int(port_str)
            except Exception:
                pass
    if not ssh_host:
        raise ValueError(f'Invalid remote ip: {ssh_host}')

    # ── skip tunnel when the SSH target is ourselves ──────────────────────
    if is_own_ip(ssh_host):
        _logger.debug(
            "SSH host %s is a local address — skipping tunnel, using port %d directly.",
            ssh_host, ssh_remote_port,
        )
        return ssh_remote_port

    local_port_used = _start_ssh_tunnel_server(
        ssh_ip=ssh_host,
        ssh_remote_port=ssh_remote_port,
        ssh_remote_ip=ssh_remote_ip,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_pw=ssh_pw,
        ssh_key_path=ssh_key_path,
        local_port=local_port,
    )
    return local_port_used


__all__ = ['SSHTunnelConfig', 'get_remote_forward_tunnel', 'stop_remote_clients']