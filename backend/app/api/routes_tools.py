# -*- coding: utf-8 -*-
"""
生活服务与知识库 REST API（角色2：郝英博）

接口清单：
  GET  /api/weather                 天气查询（含穿衣/出行建议）
  GET  /api/community               社区信息查询
  POST /api/knowledge/import        知识库导入（重新导入 data/health_knowledge）
  POST /api/knowledge/search        知识检索测试（RAG 效果验证）
  GET  /api/knowledge/stats         知识库统计
"""
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.tools.weather_tool import get_weather
from app.tools.community_tool import search_community_info
from app.rag.knowledge_base import import_knowledge, knowledge_stats
from app.rag.retriever import retrieve, format_context, extract_sources

router = APIRouter(prefix="/api", tags=["生活服务与知识库"])


@router.get("/weather", summary="天气查询", description="查询实时天气与未来三天预报，附穿衣、出行建议")
async def weather(
    city: str = Query("", description="城市名，如：北京。不传则用用户默认城市"),
    user_id: int = Query(None, description="用户 ID（取其所在城市作默认）"),
    db: Session = Depends(get_db),
):
    user_city = ""
    if user_id:
        u = db.query(User).filter(User.id == user_id).first()
        user_city = u.city if u else ""
    return await get_weather(city=city, user_city=user_city)


@router.get("/community", summary="社区信息查询", description="查询社区活动、养老服务、便民电话")
async def community(q: str = Query("", description="关键词，如：活动、食堂、电话")):
    return search_community_info(q)


class KnowledgeSearchRequest(BaseModel):
    question: str = Field(..., description="要检索的问题", examples=["高血压老人能吃咸菜吗"])
    top_k: int = Field(3, ge=1, le=10, description="返回条数")


@router.post("/knowledge/search", summary="知识检索测试", description="RAG 检索效果验证：返回最相关的知识片段与分数")
async def knowledge_search(req: KnowledgeSearchRequest):
    chunks = await retrieve(req.question, top_k=req.top_k)
    return {
        "question": req.question,
        "count": len(chunks),
        "context": format_context(chunks),
        "sources": extract_sources(chunks),
        "chunks": chunks,
    }


class KnowledgeImportRequest(BaseModel):
    reset: bool = Field(True, description="是否清空旧库后重新导入")


@router.post("/knowledge/import", summary="知识库导入", description="重新导入 data/health_knowledge 目录下的全部知识文档")
async def knowledge_import(req: KnowledgeImportRequest):
    stats = await import_knowledge(reset=req.reset)
    return {"success": True, "stats": stats,
            "hint": "导入完成。角色3后续把更多权威健康素材放入 data/health_knowledge/ 后，重新执行本接口即可"}


@router.get("/knowledge/stats", summary="知识库统计")
async def knowledge_statistics():
    return knowledge_stats()
