import logging
import os
import unittest

from core.server.security.admin_password import (
    ADMIN_PASSWORD_HASH_ENV,
    ADMIN_PASSWORD_ITER_ENV,
    ADMIN_PASSWORD_SALT_ENV,
    clear_admin_password_state,
    get_admin_password_state,
    initialize_admin_password,
    load_admin_password_state_from_env,
    verify_admin_password,
)


class TestAdminPasswordRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = os.environ.copy()
        clear_admin_password_state()
        os.environ.pop("ADMIN_PW", None)
        return super().setUp()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)
        clear_admin_password_state()
        return super().tearDown()

    def test_initialize_from_plaintext_env_hashes_and_removes_plaintext(self) -> None:
        os.environ["ADMIN_PW"] = "env-secret-password"

        generated = initialize_admin_password(logger=logging.getLogger(__name__), allow_generate=False)

        self.assertIsNone(generated)
        self.assertNotIn("ADMIN_PW", os.environ)
        self.assertIn(ADMIN_PASSWORD_HASH_ENV, os.environ)
        self.assertIn(ADMIN_PASSWORD_SALT_ENV, os.environ)
        self.assertIn(ADMIN_PASSWORD_ITER_ENV, os.environ)
        self.assertTrue(verify_admin_password("env-secret-password"))
        self.assertFalse(verify_admin_password("wrong-password"))

    def test_generated_password_can_be_reloaded_from_hash_env(self) -> None:
        generated = initialize_admin_password(logger=logging.getLogger(__name__), allow_generate=True)
        self.assertIsInstance(generated, str)
        self.assertTrue(generated)
        self.assertTrue(verify_admin_password(generated or ""))

        clear_admin_password_state(clear_env=False)
        reloaded = load_admin_password_state_from_env()

        self.assertIsNotNone(reloaded)
        self.assertIsNotNone(get_admin_password_state())
        self.assertTrue(verify_admin_password(generated or ""))
