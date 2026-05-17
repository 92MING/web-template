"""SSH tunnel configuration, str coercion, SSH config resolution and
URL/endpoint rewriting tests.

Tests cover:
  • SSHTunnelConfig str coercion (string → SSHTunnelConfig)
  • ~/.ssh/config Host lookup via _find_ssh_config
  • URL rewriting (_rewrite_url_with_tunnel, _rewrite_endpoint_with_tunnel)
  • DB config classes accept ssh_tunnel as str, dict, or SSHTunnelConfig
  • Full tunnel→client-params pipeline (mocked tunnel)
  • get_remote_forward_tunnel skip for local IPs
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.utils.network_utils.ssh_tunnel import (
    SSHTunnelConfig,
    _build_openssh_forward_command,
    _find_ssh_config,
    _get_default_ssh_config,
    _build_proxyjump_proxy_command,
    _lookup_ssh_host_settings,
    _start_ssh_tunnel_server,
    get_remote_forward_tunnel,
)
from core.utils.network_utils.helper_funcs import is_own_ip
from core.storage.config import (
    _rewrite_url_with_tunnel,
    _rewrite_endpoint_with_tunnel,
    RedisKVDBConfig,
    EtcdKVDBConfig,
    SQL_ORM_DB_Config,
    MongoORM_DB_Config,
    PostgreSQL_ORM_DB_Config,
    MySQL_ORM_DB_Config,
    RedisORMDBConfig,
    MilvusVectorDBConfig,
    RedisVectorDBConfig,
    MongoVectorDBConfig,
    MinIO_ObjectDB_Config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SSHTunnelConfig str coercion
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHTunnelConfigStrCoercion(unittest.TestCase):

    def test_str_creates_config_with_ssh_host(self):
        cfg = SSHTunnelConfig.model_validate("my-remote-host")
        self.assertIsInstance(cfg, SSHTunnelConfig)
        self.assertEqual(cfg.ssh_host, "my-remote-host")
        self.assertIsNone(cfg.ssh_port)
        self.assertIsNone(cfg.ssh_user)

    def test_dict_still_works(self):
        cfg = SSHTunnelConfig.model_validate({"ssh_host": "box1", "ssh_port": 2222})
        self.assertEqual(cfg.ssh_host, "box1")
        self.assertEqual(cfg.ssh_port, 2222)

    def test_str_with_shorthand_user_host_port(self):
        """Shorthand is parsed by get_remote_forward_tunnel, not by the model
        itself – str coercion just sets ssh_host."""
        cfg = SSHTunnelConfig.model_validate("admin:secret@box:2222")
        self.assertEqual(cfg.ssh_host, "admin:secret@box:2222")

    def test_empty_str_creates_empty_host(self):
        """An empty string becomes ssh_host='', which will fail at tunnel time."""
        cfg = SSHTunnelConfig.model_validate("")
        self.assertEqual(cfg.ssh_host, "")

    def test_none_is_none(self):
        """When used in a Union[SSHTunnelConfig, None], None stays None."""
        from pydantic import TypeAdapter
        ta = TypeAdapter(SSHTunnelConfig | None)
        self.assertIsNone(ta.validate_python(None))

    def test_round_trip_serialization(self):
        cfg = SSHTunnelConfig.model_validate("myhost")
        d = cfg.model_dump(mode="json")
        self.assertEqual(d["ssh_host"], "myhost")
        restored = SSHTunnelConfig.model_validate(d)
        self.assertEqual(restored.ssh_host, "myhost")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SSH config file lookup
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSHConfigFileLookup(unittest.TestCase):

    def test_default_config_loads(self):
        """On this machine ~/.ssh/config should exist."""
        config = _get_default_ssh_config()
        # May be None on CI without SSH config, skip gracefully
        if config is None:
            self.skipTest("No ~/.ssh/config on this machine")
        self.assertIsNotNone(config)

    def test_find_known_host(self):
        """Look up a Host defined in ~/.ssh/config."""
        result = _find_ssh_config("tts-server1")
        if result is None:
            self.skipTest("tts-server1 not found in SSH config")
        port, user, key_path = result
        self.assertEqual(port, 25611)
        self.assertEqual(user, "server1")
        self.assertIn("max_key", key_path or "")

    def test_find_unknown_host_returns_none(self):
        """A nonexistent Host should return None (or a trivial fallback)."""
        result = _find_ssh_config("this-host-does-not-exist-999")
        # paramiko lookup returns a dict with only 'hostname' for unknown hosts
        # _find_ssh_config checks len==1 and returns None
        self.assertIsNone(result)

    def test_lookup_includes_hostname_and_proxyjump(self):
        settings = _lookup_ssh_host_settings("tts-server10")
        if settings is None:
            self.skipTest("tts-server10 not found in SSH config")
        self.assertEqual(settings["hostname"], "localhost")
        self.assertEqual(settings["proxyjump"], "tts-server12")


class TestProxyJumpSupport(unittest.TestCase):

    def test_proxyjump_command_uses_ssh_config_and_target(self):
        command = _build_proxyjump_proxy_command("localhost", 25620, "tts-server12")
        self.assertIn("ssh", command.lower())
        self.assertIn("-W", command)
        self.assertIn("localhost:25620", command)
        self.assertIn("tts-server12", command)

    def test_openssh_forward_command_disables_host_key_prompt(self):
        command_parts = _build_openssh_forward_command(
            ssh_host="tts-server10",
            ssh_remote_ip="127.0.0.1",
            ssh_remote_port=9198,
            local_port=40123,
        )
        self.assertIn("StrictHostKeyChecking=no", command_parts)

    def test_start_tunnel_uses_resolved_hostname_and_proxyjump(self):
        fake_tunnel = MagicMock()
        fake_tunnel.local_bind_port = 40123
        settings = {
            "hostname": "localhost",
            "port": 25620,
            "username": "server10",
            "key_path": "C:/Users/yashi/.ssh/max_key",
            "proxyjump": "tts-server12",
            "proxycommand": None,
        }

        with (
            patch("core.utils.network_utils.ssh_tunnel._lookup_ssh_host_settings", return_value=settings),
            patch("core.utils.network_utils.ssh_tunnel._start_openssh_forward_tunnel", return_value=fake_tunnel) as mock_start,
        ):
            local_port = _start_ssh_tunnel_server("tts-server10", 9198, local_port=40123)

        self.assertEqual(local_port, 40123)
        _, kwargs = mock_start.call_args
        self.assertEqual(kwargs["ssh_host"], "tts-server10")
        self.assertEqual(kwargs["ssh_remote_port"], 9198)
        self.assertEqual(kwargs["ssh_remote_ip"], "127.0.0.1")
        self.assertEqual(kwargs["local_port"], 40123)
        self.assertEqual(kwargs["ssh_port"], 25620)
        self.assertEqual(kwargs["ssh_user"], "server10")
        self.assertEqual(kwargs["ssh_key_path"], "C:/Users/yashi/.ssh/max_key")


class TestOwnIpDetection(unittest.TestCase):

    def test_hostname_alias_does_not_trigger_global_ip_lookup(self):
        with patch("core.utils.network_utils.helper_funcs.get_global_IP", side_effect=AssertionError("should not call")):
            self.assertFalse(is_own_ip("tts-server10"))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. URL / endpoint rewriting with mocked tunnel
# ═══════════════════════════════════════════════════════════════════════════════

def _patch_tunnel(local_port: int = 12345):
    """Patch get_remote_forward_tunnel to return a fixed local port."""
    return patch(
        "core.utils.network_utils.ssh_tunnel.get_remote_forward_tunnel",
        return_value=local_port,
    )


class TestURLRewriting(unittest.TestCase):

    def test_redis_url(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(19999):
            result = _rewrite_url_with_tunnel("redis://10.0.0.5:6379/0", cfg)
        self.assertIn("127.0.0.1:19999", result)
        self.assertTrue(result.endswith("/0"))
        self.assertTrue(result.startswith("redis://"))

    def test_mongo_url(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(20000):
            result = _rewrite_url_with_tunnel("mongodb://admin:pw@10.0.0.5:27017/mydb", cfg)
        self.assertIn("127.0.0.1:20000", result)
        self.assertIn("admin:pw@", result)

    def test_postgres_url(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(25000):
            result = _rewrite_url_with_tunnel("postgresql+asyncpg://user:pass@10.0.0.5:5432/db", cfg)
        self.assertIn("127.0.0.1:25000", result)
        self.assertIn("user:pass@", result)

    def test_mysql_url(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(26000):
            result = _rewrite_url_with_tunnel("mysql+aiomysql://root:pw@10.0.0.5:3306/db", cfg)
        self.assertIn("127.0.0.1:26000", result)

    def test_milvus_http_url(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(27000):
            result = _rewrite_url_with_tunnel("http://10.0.0.5:19530", cfg)
        self.assertIn("127.0.0.1:27000", result)

    def test_localhost_url_unchanged(self):
        """If already pointing to localhost with same port, URL stays."""
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(6379):
            result = _rewrite_url_with_tunnel("redis://127.0.0.1:6379/0", cfg)
        self.assertEqual(result, "redis://127.0.0.1:6379/0")

    def test_tunnel_failure_with_direct_reach(self):
        """When tunnel raises but service is directly reachable, returns original URL."""
        cfg = SSHTunnelConfig(ssh_host="fake")
        with patch(
            "core.utils.network_utils.ssh_tunnel.get_remote_forward_tunnel",
            side_effect=ConnectionRefusedError("tunnel fail"),
        ), patch("core.storage.config.can_reach", return_value=True):
            result = _rewrite_url_with_tunnel("redis://10.0.0.5:6379/0", cfg)
        self.assertEqual(result, "redis://10.0.0.5:6379/0")

    def test_tunnel_failure_without_direct_reach_raises(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with patch(
            "core.utils.network_utils.ssh_tunnel.get_remote_forward_tunnel",
            side_effect=ConnectionRefusedError("tunnel fail"),
        ), patch("core.storage.config.can_reach", return_value=False):
            with self.assertRaises(ConnectionRefusedError):
                _rewrite_url_with_tunnel("redis://10.0.0.5:6379/0", cfg)


class TestEndpointRewriting(unittest.TestCase):

    def test_etcd_endpoint(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(28000):
            result = _rewrite_endpoint_with_tunnel("10.0.0.5:2379", cfg)
        self.assertEqual(result, "127.0.0.1:28000")

    def test_minio_endpoint(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(29000):
            result = _rewrite_endpoint_with_tunnel("10.0.0.5:9000", cfg)
        self.assertEqual(result, "127.0.0.1:29000")

    def test_endpoint_no_port_defaults_9000(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(30000) as mock_fwd:
            result = _rewrite_endpoint_with_tunnel("10.0.0.5", cfg)
        self.assertEqual(result, "127.0.0.1:30000")

    def test_localhost_endpoint_unchanged(self):
        cfg = SSHTunnelConfig(ssh_host="fake")
        with _patch_tunnel(9000):
            result = _rewrite_endpoint_with_tunnel("127.0.0.1:9000", cfg)
        self.assertEqual(result, "127.0.0.1:9000")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DB config classes accept ssh_tunnel as str
# ═══════════════════════════════════════════════════════════════════════════════

class TestDBConfigStrTunnel(unittest.TestCase):
    """All DB config classes with ssh_tunnel field should accept a plain
    string and coerce it to SSHTunnelConfig(ssh_host=string)."""

    _CONFIG_CLASSES = [
        ("RedisKV", RedisKVDBConfig, {"ssh_tunnel": "box1"}),
        ("EtcdKV", EtcdKVDBConfig, {"ssh_tunnel": "box1"}),
        ("SQL_ORM", SQL_ORM_DB_Config, {"ssh_tunnel": "box1"}),
        ("MongoORM", MongoORM_DB_Config, {"ssh_tunnel": "box1"}),
        ("PostgreSQL_ORM", PostgreSQL_ORM_DB_Config, {"ssh_tunnel": "box1"}),
        ("MySQL_ORM", MySQL_ORM_DB_Config, {"ssh_tunnel": "box1"}),
        ("RedisORM", RedisORMDBConfig, {"ssh_tunnel": "box1"}),
        ("MilvusVector", MilvusVectorDBConfig, {"ssh_tunnel": "box1"}),
        ("RedisVector", RedisVectorDBConfig, {"ssh_tunnel": "box1"}),
        ("MongoVector", MongoVectorDBConfig, {"ssh_tunnel": "box1"}),
        ("MinIOObject", MinIO_ObjectDB_Config, {"ssh_tunnel": "box1"}),
    ]

    def test_str_tunnel_coerced_for_all_backends(self):
        for label, cls, kwargs in self._CONFIG_CLASSES:
            with self.subTest(backend=label):
                cfg = cls(**kwargs)
                self.assertIsInstance(cfg.ssh_tunnel, SSHTunnelConfig, f"{label} failed str coercion")
                self.assertEqual(cfg.ssh_tunnel.ssh_host, "box1")

    def test_dict_tunnel_still_works(self):
        cfg = RedisKVDBConfig(ssh_tunnel={"ssh_host": "box2", "ssh_port": 2222})
        self.assertIsInstance(cfg.ssh_tunnel, SSHTunnelConfig)
        self.assertEqual(cfg.ssh_tunnel.ssh_host, "box2")
        self.assertEqual(cfg.ssh_tunnel.ssh_port, 2222)

    def test_none_tunnel_no_error(self):
        cfg = RedisKVDBConfig()
        self.assertIsNone(cfg.ssh_tunnel)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. to_client_init_params rewrites URL via tunnel (mocked)
# ═══════════════════════════════════════════════════════════════════════════════

class TestClientInitParamsWithTunnel(unittest.TestCase):
    """Verify to_client_init_params() produces tunneled URLs/endpoints."""

    def test_redis_kv(self):
        cfg = RedisKVDBConfig(url="redis://10.0.0.5:6379/0", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["url"])

    def test_etcd_kv(self):
        cfg = EtcdKVDBConfig(host="10.0.0.5", port=2379, ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertEqual(params["host"], "127.0.0.1")
        self.assertEqual(params["port"], 44444)

    def test_mongo_orm(self):
        cfg = MongoORM_DB_Config(url="mongodb://10.0.0.5:27017", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["mongo_url"])

    def test_postgresql_orm(self):
        cfg = PostgreSQL_ORM_DB_Config(
            url="postgresql+asyncpg://user:pass@10.0.0.5:5432/db",
            ssh_tunnel="myhost",
        )
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["url"])

    def test_mysql_orm(self):
        cfg = MySQL_ORM_DB_Config(
            url="mysql+aiomysql://root:pass@10.0.0.5:3306/db",
            ssh_tunnel="myhost",
        )
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["url"])

    def test_redis_orm(self):
        cfg = RedisORMDBConfig(url="redis://10.0.0.5:6379/0", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["url"])

    def test_milvus_vector(self):
        cfg = MilvusVectorDBConfig(uri="http://10.0.0.5:19530", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["uri"])

    def test_redis_vector(self):
        cfg = RedisVectorDBConfig(url="redis://10.0.0.5:6379/0", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["url"])

    def test_mongo_vector(self):
        cfg = MongoVectorDBConfig(url="mongodb://10.0.0.5:27017", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:44444", params["mongo_url"])

    def test_minio_object(self):
        cfg = MinIO_ObjectDB_Config(endpoint="10.0.0.5:9000", ssh_tunnel="myhost")
        with _patch_tunnel(44444):
            params = cfg.to_client_init_params()
        self.assertEqual(params["endpoint"], "127.0.0.1:44444")

    def test_no_tunnel_url_unchanged(self):
        """Without ssh_tunnel the URL stays as-is."""
        cfg = RedisKVDBConfig(url="redis://10.0.0.5:6379/0")
        params = cfg.to_client_init_params()
        self.assertEqual(params["url"], "redis://10.0.0.5:6379/0")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. get_remote_forward_tunnel – local IP skip & shorthand parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRemoteForwardTunnel(unittest.TestCase):

    def test_skip_tunnel_for_localhost(self):
        """If ssh_host is 127.0.0.1, tunnel is skipped, remote_port returned."""
        port = get_remote_forward_tunnel("127.0.0.1", ssh_remote_port=6379)
        self.assertEqual(port, 6379)

    def test_skip_tunnel_for_loopback_ipv4(self):
        port = get_remote_forward_tunnel("127.0.1.1", ssh_remote_port=5432)
        self.assertEqual(port, 5432)

    def test_shorthand_parsing(self):
        """user:pw@host:port shorthand is parsed."""
        with patch(
            "core.utils.network_utils.ssh_tunnel._start_ssh_tunnel_server",
            return_value=55555,
        ) as mock_start:
            port = get_remote_forward_tunnel("admin:secret@10.0.0.99:2222", ssh_remote_port=6379)
        self.assertEqual(port, 55555)
        call_kw = mock_start.call_args
        self.assertEqual(call_kw.kwargs.get("ssh_ip") or call_kw[1].get("ssh_ip"), "10.0.0.99")

    def test_config_object_accepted(self):
        """SSHTunnelConfig instance is unpacked correctly."""
        cfg = SSHTunnelConfig(ssh_host="10.0.0.99", ssh_port=2222, remote_port=5432)
        with patch(
            "core.utils.network_utils.ssh_tunnel._start_ssh_tunnel_server",
            return_value=55555,
        ) as mock_start:
            port = get_remote_forward_tunnel(cfg)
        self.assertEqual(port, 55555)
        _, kwargs = mock_start.call_args
        self.assertEqual(kwargs["ssh_ip"], "10.0.0.99")
        self.assertEqual(kwargs["ssh_port"], 2222)
        self.assertEqual(kwargs["ssh_remote_port"], 5432)

    def test_str_coerced_config_accepted(self):
        """A string-coerced SSHTunnelConfig works end-to-end."""
        cfg = SSHTunnelConfig.model_validate("10.0.0.99")
        cfg.remote_port = 5432
        with patch(
            "core.utils.network_utils.ssh_tunnel._start_ssh_tunnel_server",
            return_value=55555,
        ):
            port = get_remote_forward_tunnel(cfg)
        self.assertEqual(port, 55555)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Real SSH config → SSHTunnelConfig → tunnel resolution (mocked tunnel)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealSSHConfigIntegration(unittest.TestCase):
    """Use a real Host from ~/.ssh/config to verify the full chain:
    str → SSHTunnelConfig → _find_ssh_config → _start_ssh_tunnel_server.
    The actual SSH connection is mocked.
    """

    def test_str_host_resolved_via_ssh_config(self):
        """ssh_tunnel='tts-server1' → config resolves port/user/key from ~/.ssh/config."""
        result = _find_ssh_config("tts-server1")
        if result is None:
            self.skipTest("tts-server1 not in SSH config")
        port, user, key_path = result

        cfg = SSHTunnelConfig.model_validate("tts-server1")
        self.assertEqual(cfg.ssh_host, "tts-server1")

        with patch(
            "core.utils.network_utils.ssh_tunnel._start_ssh_tunnel_server",
            return_value=55555,
        ) as mock_start:
            local_port = get_remote_forward_tunnel(cfg, ssh_remote_port=6379)

        self.assertEqual(local_port, 55555)
        _, kwargs = mock_start.call_args
        # _start_ssh_tunnel_server receives "tts-server1" (the Host alias)
        # the SSH config lookup happens inside _start_ssh_tunnel_server
        self.assertEqual(kwargs["ssh_ip"], "tts-server1")
        self.assertEqual(kwargs["ssh_remote_port"], 6379)

    def test_db_config_with_real_host(self):
        """RedisKVDBConfig(ssh_tunnel='tts-server1') produces tunneled URL."""
        cfg = RedisKVDBConfig(url="redis://10.0.0.5:6379/0", ssh_tunnel="tts-server1")
        self.assertIsInstance(cfg.ssh_tunnel, SSHTunnelConfig)
        self.assertEqual(cfg.ssh_tunnel.ssh_host, "tts-server1")

        with _patch_tunnel(55555):
            params = cfg.to_client_init_params()
        self.assertIn("127.0.0.1:55555", params["url"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. AI services _resolve_ssh_tunnel_config str support
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIServicesSSHTunnelResolve(unittest.TestCase):

    def test_str_input(self):
        from core.ai.base import _resolve_ssh_tunnel_config
        result = _resolve_ssh_tunnel_config("my-remote-host")
        self.assertIsInstance(result, SSHTunnelConfig)
        self.assertEqual(result.ssh_host, "my-remote-host")

    def test_dict_input(self):
        from core.ai.base import _resolve_ssh_tunnel_config
        result = _resolve_ssh_tunnel_config({"ssh_host": "host2", "ssh_port": 2222})
        self.assertIsInstance(result, SSHTunnelConfig)
        self.assertEqual(result.ssh_host, "host2")

    def test_none_input(self):
        from core.ai.base import _resolve_ssh_tunnel_config
        self.assertIsNone(_resolve_ssh_tunnel_config(None))

    def test_config_passthrough(self):
        from core.ai.base import _resolve_ssh_tunnel_config
        original = SSHTunnelConfig(ssh_host="host3")
        result = _resolve_ssh_tunnel_config(original)
        self.assertIs(result, original)


if __name__ == "__main__":
    unittest.main()
