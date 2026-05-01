import os
import subprocess
import sys
import textwrap

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_concurrent_first_writes_bootstrap_schema_without_race() -> None:
    code = textwrap.dedent(
        """
        import asyncio
        import shutil
        import sys
        import tempfile
        from pathlib import Path

        sys.path.insert(0, '""" + str(_PROJECT_ROOT / 'app').replace('\\', '/') + """')
        sys.path.insert(0, '""" + str(_PROJECT_ROOT).replace('\\', '/') + """')

        from core.storage.orm import ORMModel, ORM_ClientBase, SQL_ORM_Client, SQLiteORMClient

        class ConcurrentBootstrapNote(ORMModel, collection_name='concurrent_bootstrap_notes_subprocess'):
            title: str

        def close_client(client: object) -> None:
            close = getattr(client, 'close', None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        async def exercise(client: ORM_ClientBase) -> None:
            object_ids = await asyncio.gather(*[
                client.set(ConcurrentBootstrapNote(title=f'note-{index}'))
                for index in range(8)
            ])
            assert len(set(object_ids)) == 8
            rows = [item async for item in client.search(ConcurrentBootstrapNote, limit=20, as_model=False)]
            assert len(rows) == 8
            assert ConcurrentBootstrapNote.CollectionName in client._bootstrapped_collections

        async def main() -> None:
            tmp_dir = tempfile.mkdtemp()
            sqlite_path = Path(tmp_dir) / 'concurrent_sqlite.sqlite3'
            sqlalchemy_path = Path(tmp_dir) / 'concurrent_sqlalchemy.sqlite3'
            sqlite_client = SQLiteORMClient(db_path=sqlite_path, cleanup_interval=1)
            sqlalchemy_client = SQL_ORM_Client(url=f'sqlite:///{sqlalchemy_path.as_posix()}', cleanup_interval=1)
            sqlite_client.start()
            sqlalchemy_client.start()
            try:
                await exercise(sqlite_client)
                await exercise(sqlalchemy_client)
                print('concurrency probe passed')
            finally:
                close_client(sqlite_client)
                close_client(sqlalchemy_client)
                await asyncio.sleep(0.05)
                shutil.rmtree(tmp_dir, ignore_errors=True)

        asyncio.run(main())
        """
    )
    env = os.environ.copy()
    env.setdefault("KONGPAPER_CORE_EAGER_IMPORTS", "0")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "concurrency regression subprocess failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "concurrency probe passed" in result.stdout


def test_sqlite_orm_client_survives_background_loop_then_main_loop_reuse() -> None:
    code = textwrap.dedent(
        """
        import asyncio
        import shutil
        import sys
        import tempfile
        from pathlib import Path

        sys.path.insert(0, '""" + str(_PROJECT_ROOT / 'app').replace('\\', '/') + """')
        sys.path.insert(0, '""" + str(_PROJECT_ROOT).replace('\\', '/') + """')

        from core.storage.orm import ORMModel, SQLiteORMClient
        from core.utils.concurrent_utils import run_any_func

        class LoopOwnerNote(ORMModel, collection_name='loop_owner_notes_subprocess'):
            title: str

        async def seed_in_background(client: SQLiteORMClient) -> None:
            await client.set(LoopOwnerNote(title='alpha'))
            row = await client.search_one(LoopOwnerNote, {'title': 'alpha'}, as_model=False)
            assert row is not None

        async def main() -> None:
            tmp_dir = tempfile.mkdtemp()
            db_path = Path(tmp_dir) / 'loop_owner.sqlite3'
            client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
            client.start()
            try:
                run_any_func(seed_in_background, client)
                row = await asyncio.wait_for(client.search_one(LoopOwnerNote, {'title': 'alpha'}, as_model=False), timeout=10)
                assert row is not None
                await asyncio.wait_for(client.set(LoopOwnerNote(title='beta')), timeout=10)
                rows = [item async for item in client.search(LoopOwnerNote, limit=10, as_model=False)]
                assert len(rows) == 2
                print('loop owner probe passed')
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                await asyncio.sleep(0.05)
                shutil.rmtree(tmp_dir, ignore_errors=True)

        asyncio.run(main())
        """
    )
    env = os.environ.copy()
    env.setdefault("KONGPAPER_CORE_EAGER_IMPORTS", "0")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "loop owner regression subprocess failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "loop owner probe passed" in result.stdout