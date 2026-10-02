# -*- coding: utf-8 -*-
"""
数据库连接管理（角色2：郝英博）

- 默认使用 SQLite（本地开发零安装）
- DATABASE_URL 指向 PostgreSQL 时自动切换（Docker 生产部署）
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app import config

# SQLite 需要关闭同线程检查（FastAPI 多协程访问）
_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    config.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,   # 连接前探活，避免数据库重启后报错
    echo=False,           # 生产环境关闭 SQL 打印
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """ORM 模型基类"""
    pass


def init_db() -> None:
    """初始化数据库：创建所有表（已存在则跳过）+ 轻量迁移（给老库补新列）"""
    from app.db import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate() -> None:
    """
    轻量数据库迁移（SQLite 加列迁移）

    目的：老版本数据库升级到新版（users 表新增分型字段）时不丢数据。
    注意：老用户 profile_stage 默认填 'done'（已经聊过天了，不再打扰重新答题）；
          新建用户由 ORM 默认值 'new' 控制（会走引导流程）。
    """
    if not config.DATABASE_URL.startswith("sqlite"):
        return  # PostgreSQL 用正式迁移工具，此处跳过
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
            # (列名, 列定义) —— 老用户默认 done，避免升级后突然被问一堆问题
            migrations = [
                ("profile_stage", "TEXT DEFAULT 'done'"),
                ("profile_type", "TEXT DEFAULT ''"),
                ("profile_confidence", "REAL DEFAULT 0"),
                ("profile_evidence", "TEXT DEFAULT '{}'"),
                ("profile_engine", "TEXT DEFAULT 'rule'"),
                ("emergency_phone", "TEXT DEFAULT ''"),
                ("height_weight", "TEXT DEFAULT ''"),
                ("chat_mode", "TEXT DEFAULT 'elderly'"),
            ]
            changed = False
            memory_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(memories)"))]
            if "session_id" not in memory_cols:
                conn.execute(text("ALTER TABLE memories ADD COLUMN session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE"))
                changed = True
            session_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))]
            for col, ddl in [("title", "TEXT DEFAULT ''"), ("pinned", "BOOLEAN DEFAULT 0")]:
                if col not in session_cols:
                    conn.execute(text(f"ALTER TABLE sessions ADD COLUMN {col} {ddl}"))
                    changed = True
            for col, ddl in migrations:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                    changed = True
            if changed:
                conn.execute(text("""UPDATE sessions SET title = COALESCE(
                    (SELECT substr(content, 1, 100) FROM messages
                     WHERE messages.session_id = sessions.id AND role = 'user'
                     ORDER BY id LIMIT 1), '') WHERE title IS NULL OR title = ''"""))
                conn.commit()
    except Exception:
        import logging
        logging.getLogger("yinlingban.db").exception("数据库升级失败")
        raise


def get_db():
    """FastAPI 依赖注入：获取数据库会话，请求结束自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
