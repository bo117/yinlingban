"""Validated MCP access to the same persisted memory used by dialogue."""
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from app.db.database import SessionLocal
from app.db.models import User, MemoryFact, ChatSession
from app.core.memory import save_facts


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    user_id: int = Field(gt=0)
    session_id: int | None = Field(None, gt=0, description="指定会话以读写其独立记忆；省略仅访问旧版用户记忆，不注入会话。")


class WriteArgs(MemoryArgs):
    fact_type: str = Field(min_length=1, max_length=30, pattern=r"^[a-z][a-z0-9_]*$")
    value: str = Field(min_length=1, max_length=200)


MEMORY_TOOLS = [
    {"name": "memory_read", "description": "读取会话独立长期记忆，请指定 user_id 和 session_id。省略 session_id 仅访问旧用户记忆，不注入聊天。",
     "inputSchema": MemoryArgs.model_json_schema()},
    {"name": "memory_write", "description": "保存用户明确提供的事实，请指定 user_id 和 session_id。仅同一会话同类型覆盖，重启后保留。省略 session_id 仅写旧用户记忆。",
     "inputSchema": WriteArgs.model_json_schema()},
]


def call_memory(name, arguments):
    import json
    def result(data, error=False):
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": error}
    try:
        args = (WriteArgs if name == "memory_write" else MemoryArgs).model_validate(arguments)
    except ValidationError:
        return result({"message": "参数无效：请提供正整数 user_id；写入需 fact_type 和非空 value（最多200字）。"}, True)
    with SessionLocal() as db:
        if db.get(User, args.user_id) is None:
            return result({"message": "用户不存在，请先创建用户。"}, True)
        if args.session_id is not None and not db.query(ChatSession).filter_by(id=args.session_id, user_id=args.user_id).first():
            return result({"message": "会话不存在或不属于该用户。"}, True)
        if name == "memory_write":
            save_facts(db, args.user_id, [(args.fact_type, args.value)], args.session_id)
        facts = db.query(MemoryFact).filter(MemoryFact.user_id == args.user_id, MemoryFact.session_id == args.session_id).order_by(MemoryFact.id).all()
        return result({"user_id": args.user_id, "persistent": True, "facts": [
            {"id": f.id, "fact_type": f.fact_type, "value": f.fact_value} for f in facts
        ]})
