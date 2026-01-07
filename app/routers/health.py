"""Health check router."""

from pathlib import Path
from typing import Optional

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()


def _load_alembic_head() -> Optional[str]:
    project_root = Path(__file__).resolve().parents[2]
    cfg_path = project_root / "alembic.ini"
    script_location = project_root / "alembic"
    if not cfg_path.exists() or not script_location.exists():
        return None

    config = Config(str(cfg_path))
    config.set_main_option("script_location", str(script_location))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Lightweight health endpoint with DB + alembic checks."""

    db_ok = False
    alembic_current: Optional[str] = None
    alembic_head: Optional[str] = None

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    if db_ok:
        try:
            version_result = await db.execute(text("SELECT version_num FROM alembic_version"))
            alembic_current = version_result.scalar_one_or_none()
        except Exception:
            alembic_current = None

    try:
        alembic_head = _load_alembic_head()
    except Exception:
        alembic_head = None

    alembic_head_ok = bool(alembic_current and alembic_head and alembic_current == alembic_head)

    return {
        "api_ok": True,
        "db_ok": db_ok,
        "alembic_head_ok": alembic_head_ok,
        "alembic_current": alembic_current,
        "alembic_head": alembic_head,
    }
