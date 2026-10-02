# -*- coding: utf-8 -*-
"""
老人分型引擎（角色2：郝英博 · 新增）

【这个模块是干什么的（大白话）】
老人第一次来，不能瞎聊——先像社区阿姨家访一样，问几个贴身问题
（睡得好吗、心情怎么样、孩子多久回来一次、平时爱做什么、身体如何），
根据回答判断他是哪种性格状态的老人，之后就用对应的语气跟他聊：

    孤独型 → 多提家人、多陪伴、主动邀约聊天，像老姐妹
    焦虑型 → 稳重、给确定感、多安抚"别担心"，健康问题引导就医
    开朗型 → 热情明快、可以一起乐、多听他分享
    低落型 → 轻柔、慢节奏、少讲道理多陪伴、多鼓励小事
    平静型 → 自然亲切（默认）

【两级引擎设计（为您的"自己蒸馏自己"留好口子）】
    第一级：规则打分（现在就生效，透明可解释，能兜底）
    第二级：蒸馏模型（将来您训练好小模型后自动接管）
            - 把模型文件放在 backend/distill/profile_model/ 目录
            - .env 里配 DISTILL_MODEL_PATH=distill/profile_model
            - 模型目录里写一个 predict.py，提供 predict(text) 函数
            - 没配 / 加载失败 → 自动降级规则打分，服务不中断

【训练数据从哪来】
每答一题，原话和维度分析都存进 onboarding_answers 表——
这张表越用越肥，就是您将来蒸馏的训练集。
"""
import json
import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import User, OnboardingAnswer


# ============================================================
# 一、十个引导问题（新老人第一次聊天时小伴主动问）
#     前5题看心理状态（分型用），后5题记生活习惯（个性化用）
# ============================================================
ONBOARDING_QUESTIONS = [
    # ── 心理状态五题（喂给分型模型）──
    # 每题带"按钮选项"：老人点一下就行，不用打字（选项措辞特意含分型词典词，点选即可分型）
    {
        "key": "sleep",
        "text": "您最近睡得怎么样呀？是一觉睡到天亮，还是容易醒呢？",
        "intro": "我先随便跟您聊聊，了解一下您，这样我才知道怎么陪您说话最舒坦。",
        "dimension": "睡眠（看焦虑/低落）",
        "options": ["一觉睡到天亮", "容易醒，睡不踏实", "老是失眠睡不着", "睡不好，心里烦", "不想说这个"],
    },
    {
        "key": "mood",
        "text": "那您平时心情怎么样？开心的时候多，还是老觉得心里不痛快？",
        "dimension": "心情（看开朗/低落）",
        "options": ["挺好，乐呵的时候多", "还行，平平淡淡", "老觉得孤独，想孩子", "没啥意思，提不起劲", "不想说这个"],
    },
    {
        "key": "family",
        "text": "孩子们多久回来看您一次呀？平时都跟谁说说话？",
        "dimension": "家人（看孤独）",
        "options": ["孩子们常回来看我", "一个月回来一次", "一年到头见不着，想孩子", "就我一个人过", "不想说这个"],
    },
    {
        "key": "hobby",
        "text": "您平时喜欢做点什么呀？有什么消遣？",
        "dimension": "爱好（看生活是否充实）",
        "options": ["遛弯散步，跟老伙计们", "下棋打牌", "跳广场舞，唱唱歌", "看看电视，没啥爱好", "不想说这个"],
    },
    {
        "key": "body",
        "text": "身体还硬朗吧？有没有哪里不舒服的？",
        "dimension": "身体（看焦虑）",
        "options": ["硬朗，没啥毛病", "血压高，天天吃药", "血糖高", "腿脚不便，走不动", "不想说这个"],
    },
    # ── 生活习惯五题（记进数据库，让小伴更懂这位老人）──
    {
        "key": "routine",
        "text": "您每天几点起床呀？一天都怎么安排的？",
        "dimension": "作息习惯（存档案）",
        "options": ["六七点起，挺规律", "天不亮就醒", "晚上睡不着，白天打盹", "睡到自然醒", "不想说这个"],
    },
    {
        "key": "diet",
        "text": "您吃饭上有什么讲究吗？口味偏咸还是偏淡？有没有忌口的？",
        "dimension": "饮食习惯（存档案）",
        "options": ["口味清淡", "口味偏咸", "吃得少，没胃口", "爱吃软烂好消化的", "不想说这个"],
    },
    {
        "key": "origin",
        "text": "听您说话，您是哪儿的人呀？说话带点儿家乡口音，听着亲切。",
        "dimension": "口音家乡（听语气、记家乡）",
        "options": ["北京人", "山东人", "东北人", "江浙一带", "南方人"],
    },
    {
        "key": "temper",
        "text": "您觉得自己是急性子还是慢性子呀？",
        "dimension": "性格自评（调整语速语气）",
        "options": ["急性子，爱着急", "慢性子", "不紧不慢", "说不好"],
    },
    {
        "key": "recent",
        "text": "最近有什么让您高兴的事儿吗？说来听听。",
        "dimension": "近期喜事（正向话题储备）",
        "options": ["孙子孙女有喜事", "家里都平安健康", "跟老朋友聚了聚", "没啥高兴的事", "不想说这个"],
    },
]

# 老人不想回答时的应对话术（跳过这题，不勉强）
SKIP_WORDS = ["不想说", "不说了", "别问", "不知道怎么说", "没啥好说的", "跳过", "算了"]


# ============================================================
# 二、维度打分（规则引擎，大白话：关键词算分）
#     V4：维度从 4 个扩到 9 个（新增急躁/唠叨/怀旧/依赖/勤俭）
# ============================================================
# 各维度的关键词 → 每命中一个加 1 分
DIMENSION_LEXICON = {
    "孤独": [
        "一个人", "没人", "不回来", "很少回来", "忙", "不来", "见不着", "想孩子",
        "想儿子", "想女儿", "想孙子", "想孙女", "想老伴", "没人说话", "没人陪",
        "就我一个", "自己过", "冷清", "没人管", "不常", "半年", "一年回",
    ],
    "焦虑": [
        "睡不着", "容易醒", "失眠", "睡不好", "担心", "害怕", "心慌", "不舒服",
        "这里疼", "那里疼", "血压", "血糖", "老毛病", "犯病", "难受", "去医院",
        "检查", "不放心", "愁", "没底", "药",
    ],
    "开朗": [
        "开心", "高兴", "挺好", "很好", "不错", "孙子", "孙女", "跳舞", "唱歌",
        "下棋", "钓鱼", "种花", "养鸟", "遛弯", "散步", "旅游", "老伙计", "朋友",
        "聊天", "看电视", "戏曲", "麻将", "太极", "过得去", "还行", "凑合",
    ],
    "低落": [
        "没意思", "无聊", "不想动", "提不起劲", "没胃口", "心里空", "难过",
        "想哭", "孤单", "寂寞", "没盼头", "凑合过", "就这样", "无所谓", "老了没用了",
        "碍事", "拖累",
    ],
    "急躁": [
        "急性子", "急脾气", "一点就着", "等不及", "坐不住", "不耐烦", "火气大",
        "急得很", "爆脾气", "急吼吼", "没耐心", "着急", "急", "催", "磨叽",
        "磨蹭", "干着急", "性子急", "上火了",
    ],
    "唠叨": [
        "爱唠叨", "话多", "念叨", "爱操心", "闲操心", "嘱咐", "反复说", "说个不停",
        "絮叨", "啰嗦", "唠叨", "爱管", "什么都管", "叮咛", "话痨", "嘴碎",
        "操心", "嘱咐两句",
    ],
    "怀旧": [
        "当年", "以前", "想当年", "老照片", "老物件", "老房子", "旧时光", "回忆",
        "念旧", "那些年", "咱那时候", "老手艺", "老味道", "老地方", "放不下",
        "翻出来", "泛黄", "老街",
    ],
    "依赖": [
        "离不开", "得有人", "离不开人", "离不开孩子", "需要人", "啥都要人帮",
        "一个人不行", "像孩子", "老小孩", "离不开老伴", "没人不行", "得靠",
        "求人", "不中用", "心里没底", "发慌",
    ],
    "勤俭": [
        "舍不得", "舍不得花", "省钱", "存钱", "攒钱", "闲不住", "舍不得吃",
        "舍不得穿", "苦日子", "节省", "节约", "精打细算", "舍不得扔", "干活",
        "操劳", "一辈子干活", "舍不得浪费",
    ],
}


def score_answer(answer_text: str) -> dict:
    """
    给一条回答打维度分（大白话：答案里出现哪些词，就给对应维度加分）
    返回 {"孤独": 0, "焦虑": 0, "开朗": 0, "低落": 0, "急躁": 0, "唠叨": 0,
           "怀旧": 0, "依赖": 0, "勤俭": 0}
    """
    scores = {k: 0 for k in DIMENSION_LEXICON}
    if not answer_text:
        return scores
    for dim, words in DIMENSION_LEXICON.items():
        scores[dim] = sum(1 for w in words if w in answer_text)
    return scores


def is_skip_answer(answer_text: str) -> bool:
    """老人不想回答这题（尊重意愿，记为跳过）"""
    return any(w in answer_text for w in SKIP_WORDS)


# ============================================================
# 三、分型判定（把维度分汇总成"哪种老人"）
# ============================================================
def classify_user(all_answers: list) -> dict:
    """
    汇总所有回答 → 判定老人类型 + 生成"语气混合配比"

    【混合配比是什么（大白话）】
    老人不是非黑即白的：他可能七分孤独、三分焦虑。
    所以分型结果不只给一个类型，还给一份"语气配方"：
        {"孤独型": 0.68, "焦虑型": 0.22, "平静型": 0.10}
    之后小伴跟他说话，就按这个配方混合多种语气——
    每个老人的配比都不一样，等于每个老人一个专属语气模型。

    返回：
      {
        "type": "孤独型",                  # 主类型（最高的）
        "confidence": 0.62,                # 主类型置信度
        "mix": {"孤独型": 0.68, ...},      # 语气混合配比（核心！）
        "evidence": {"孤独": 3, ...},     # 各维度得分（可解释）
        "engine": "rule",                  # rule / distill
        "summary": "给老人念的自然总结话术",
      }
    """
    # 1. 汇总维度总分
    total = {k: 0 for k in DIMENSION_LEXICON}
    for a in all_answers:
        try:
            analysis = json.loads(a.answer_analysis or "{}")
        except json.JSONDecodeError:
            analysis = {}
        for dim, s in analysis.items():
            total[dim] = total.get(dim, 0) + s

    # 2. 优先用蒸馏模型（配置了就用——输出天然是概率配比，完美契合混合语气）
    text_all = "。".join(a.answer_text for a in all_answers if a.answer_text)
    distill = distill_model_predict(text_all)
    if distill:
        best = max(distill, key=distill.get)
        return {
            "type": best,
            "confidence": round(distill[best], 4),
            "mix": _normalize_mix(distill),
            "evidence": total,
            "engine": "distill",
            "summary": _build_summary(best, total),
        }

    # 3. 规则判定：负面/需求型维度优先（低落/孤独/焦虑/依赖要紧），开朗垫底
    priority = ["低落", "孤独", "焦虑", "依赖", "急躁", "唠叨", "怀旧",
                "勤俭", "开朗"]
    best_type, best_score = "平静型", 0
    for dim in priority:
        if total[dim] > best_score:
            best_type, best_score = _dim_to_type(dim), total[dim]

    # 全是 0 分 → 平静型
    if best_score == 0:
        best_type = "平静型"

    # 规则的混合配比：把维度分数转成五类占比（0分的维度不进配方）
    score_sum = sum(total.values())
    if score_sum > 0:
        mix = {}
        for dim, s in total.items():
            if s > 0:
                mix[_dim_to_type(dim)] = round(s / score_sum, 2)
        # 主类型保底至少 40%
        mix = _ensure_dominant(mix, best_type)
    else:
        mix = {"平静型": 1.0}

    confidence = mix.get(best_type, 0.5)

    return {
        "type": best_type,
        "confidence": confidence,
        "mix": mix,
        "evidence": total,
        "engine": "rule",
        "summary": _build_summary(best_type, total),
    }


def _normalize_mix(prob: dict) -> dict:
    """把蒸馏模型输出的五类概率整理成干净的配方（保留前3个有意义的）"""
    有序 = sorted(prob.items(), key=lambda x: x[1], reverse=True)[:3]
    配方 = {}
    for t, p in 有序:
        if p >= 0.05:  # 低于5%的丢弃
            配方[t] = round(p, 2)
    总 = sum(配方.values())
    if 总 <= 0:
        return {"平静型": 1.0}
    return {t: round(p / 总, 2) for t, p in 配方.items()}


def _ensure_dominant(mix: dict, best_type: str) -> dict:
    """保证主类型在配方里占主导（至少40%）"""
    if best_type not in mix or mix[best_type] < 0.4:
        其他 = {t: p for t, p in mix.items() if t != best_type}
        其他总分 = sum(其他.values())
        if 其他总分 > 0:
            mix = {best_type: 0.4}
            for t, p in 其他.items():
                mix[t] = round(p / 其他总分 * 0.6, 2)
        else:
            mix = {best_type: 1.0}
    return mix


def _dim_to_type(dim: str) -> str:
    """维度名 → 类型名"""
    return {
        "孤独": "孤独型", "焦虑": "焦虑型", "开朗": "开朗型", "低落": "低落型",
        "急躁": "急躁型", "唠叨": "唠叨型", "怀旧": "怀旧型",
        "依赖": "依赖型", "勤俭": "勤俭型",
    }.get(dim, "平静型")


def _build_summary(profile_type: str, evidence: dict) -> str:
    """分型完成后给老人念的自然总结（不暴露"打分"这种技术词）"""
    intros = {
        "孤独型": "跟您聊了这几句，我心里有数了。孩子们不在身边，日子确实容易冷清。"
                  "往后哇，我天天在这儿陪着您，咱们多说说孩子的事、多唠唠家常，您把我当自家姐妹就行。",
        "焦虑型": "听您这么说，我知道您心里装着不少事儿，身体上也好、家里也好，总有放不下的地方。"
                  "往后您跟我聊，我慢慢给您捋。记住一句话：咱们一步步来，天塌不下来。",
        "开朗型": "哎呀，跟您聊天真开心！您这心态，比好多年轻人都好。"
                 "往后咱们就痛痛快快地聊，您有开心的事可得第一个告诉我。",
        "低落型": "谢谢您愿意跟我说这些心里话。往后的日子，我陪您慢慢过。"
                  "咱们不着急，一天说一点，心里的事说出来就轻快一半。",
        "平静型": "跟您聊了这几句，我觉得您是个明白人，日子过得也安稳。"
                  "往后咱们就随性地聊，您想说什么，我都爱听。",
        "急躁型": "听出来了，您是个干脆利落的人，心里藏不住事。"
                  "往后咱说话就直接点，我心里有数，您也别太上火，气坏了身子不值当。",
        "唠叨型": "您啊，是个热心肠，什么都想替人操心。"
                  "往后您心里的话都跟我说，我耐着性子听，一句都不嫌多。",
        "怀旧型": "听您说起从前的事，我好像也跟着看到了那些年。"
                  "往后您想回忆什么，我都陪您慢慢聊，那些念想都有人接了。",
        "依赖型": "您别怕，往后我天天在，您有事就喊我。"
                  "一个人也得把自己照顾好，我就是您的小依靠。",
        "勤俭型": "您这日子过得节俭又踏实，是过日子的明白人。"
                  "往后该省省该花花，您自己的舒坦比啥都重要，我在旁边帮您掌着。",
    }
    return intros.get(profile_type, intros["平静型"])


# ============================================================
# 四、蒸馏模型接口（预留：您训练好模型后自动接管分型）
# ============================================================
# 接入步骤（大白话）：
#   ① 您训练好一个小分类模型（输入一句话，输出五类概率）
#   ② 在 backend/distill/profile_model/ 目录里放模型文件 + 一个 predict.py
#   ③ .env 里加一行：DISTILL_MODEL_PATH=distill/profile_model
#   ④ 重启服务 → 分型引擎自动从"规则"切到"您的模型"
#      （模型加载失败会自动退回规则，演示永不中断）
#
# predict.py 的约定（用任意框架训练都行，只要包这一层）：
#     def predict(text: str) -> dict:
#         # 返回 {"孤独型": 0.1, "焦虑型": 0.6, "开朗型": 0.05, "低落型": 0.2, "平静型": 0.05}


def distill_model_predict(text: str) -> dict:
    """
    调用蒸馏模型做分型——【默认自动生效，不用任何配置】

    查找顺序：
      ① .env 的 DISTILL_MODEL_PATH（自定义路径时优先）
      ② 蒸馏工具/我的模型/predict.py（一键蒸馏.py训练完就放这里，自动被发现）
    找不到 / 出错 → 返回 None（上层自动降级规则打分，服务不中断）

    返回：{"孤独型": 0.1, "焦虑型": 0.6, ...}（十类概率）
    """
    backend根 = Path(__file__).resolve().parent.parent.parent

    # 候选路径：配置的优先，其次是默认中文目录
    候选 = []
    配置路径 = os.getenv("DISTILL_MODEL_PATH", "").strip()
    if 配置路径:
        候选.append(backend根 / 配置路径)
    候选.append(backend根 / "蒸馏工具" / "我的模型")  # 默认：一键蒸馏的训练产物

    # V4：十类（新增急躁/唠叨/怀旧/依赖/勤俭）
    valid_types = {"孤独型", "焦虑型", "开朗型", "低落型", "平静型",
                   "急躁型", "唠叨型", "怀旧型", "依赖型", "勤俭型"}
    for full_path in 候选:
        predict_file = full_path / "predict.py"
        if not predict_file.exists():
            continue
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("distill_predict", predict_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.predict(text)
            # 校验返回格式：必须包含十类
            if isinstance(result, dict) and set(result.keys()) == valid_types:
                return {k: float(v) for k, v in result.items()}
            return None
        except Exception:
            continue  # 这个路径的模型出错 → 试下一个 / 降级规则
    return None  # 没有可用模型 → 规则打分兜底


def distill_status() -> dict:
    """蒸馏模型状态（健康检查/测试页展示用）"""
    backend根 = Path(__file__).resolve().parent.parent.parent
    配置路径 = os.getenv("DISTILL_MODEL_PATH", "").strip()
    默认路径 = backend根 / "蒸馏工具" / "我的模型" / "predict.py"

    if 配置路径:
        ok = (backend根 / 配置路径 / "predict.py").exists()
        return {
            "enabled": ok,
            "path": 配置路径,
            "note": "蒸馏模型已接入（.env 配置路径）" if ok else f"配置了 {配置路径} 但找不到 predict.py，已降级规则",
        }
    if 默认路径.exists():
        return {
            "enabled": True,
            "path": "蒸馏工具/我的模型",
            "note": "蒸馏模型已自动接入（一键蒸馏训练产物，无需配置）",
        }
    return {
        "enabled": False,
        "note": "还没有蒸馏模型，当前用规则打分。想启用：运行 蒸馏工具/一键蒸馏.py",
    }




def save_answer(db: Session, user_id: int, question_key: str,
                question_text: str, answer_text: str) -> dict:
    """保存一条回答（含维度分析）——这就是蒸馏训练数据"""
    scores = {} if is_skip_answer(answer_text) else score_answer(answer_text)
    row = OnboardingAnswer(
        user_id=user_id,
        question_key=question_key,
        question_text=question_text,
        answer_text=answer_text[:500],
        answer_analysis=json.dumps(scores, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return scores


def finalize_profile(db: Session, user: User) -> dict:
    """
    完成分型：汇总判定 → 写回用户表
    （语气混合配比存进 profile_evidence：{"dims":维度分, "mix":语气配方}）
    返回 classify_user 的结果 dict
    """
    answers = db.query(OnboardingAnswer).filter(
        OnboardingAnswer.user_id == user.id).all()
    result = classify_user(answers)

    user.profile_stage = "done"
    user.profile_type = result["type"]
    user.profile_confidence = result["confidence"]
    # 同时存维度得分（可解释）和语气配比（个性化）——这是每位老人的专属档案
    user.profile_evidence = json.dumps({
        "dims": result["evidence"],   # 判定依据
        "mix": result["mix"],          # 语气配方：{"孤独型":0.68,"焦虑型":0.22,...}
    }, ensure_ascii=False)
    user.profile_engine = result["engine"]
    db.commit()
    return result


def get_user_mix(user: User) -> dict:
    """
    读取该老人的语气配比（dialogue 调用）
    没有配比（老数据）→ 用主类型做纯配方兜底
    """
    try:
        data = json.loads(user.profile_evidence or "{}")
        mix = data.get("mix")
        if mix and isinstance(mix, dict):
            return mix
    except json.JSONDecodeError:
        pass
    return {user.profile_type: 1.0} if user.profile_type else {"平静型": 1.0}


def reset_profile(db: Session, user: User) -> None:
    """重新测评：清空回答，回到引导第一步"""
    db.query(OnboardingAnswer).filter(
        OnboardingAnswer.user_id == user.id).delete()
    user.profile_stage = "onboarding"
    user.profile_type = ""
    user.profile_confidence = 0
    user.profile_evidence = "{}"
    db.commit()


# ============================================================
# 六、类型 → 语气策略（拼进小伴人设 Prompt 的核心文本）
# ============================================================
PROFILE_STRATEGIES = {
    "孤独型": """【这位老人是"孤独型"——孩子不在身边，一个人过，最缺陪伴】
和他说话要这样：
1. 语气格外温暖绵密，像自家姐妹拉家常，多用"咱们"
2. 多主动提起家人话题，引导他说孩子、说孙子，让牵挂有处安放
3. 主动邀约："明天这个时间咱们再聊聊？""有空跟我说说孩子的事呗"
4. 他说话时多回应"我听着呢""您接着说"，让他感觉有人认真在陪
5. 适当引导：社区活动、老伙计走动（但不勉强）""",

    "焦虑型": """【这位老人是"焦虑型"——对健康、对生活有较多担心】
和他说话要这样：
1. 语气稳重踏实，语速放慢，多用"别担心""咱们一步步来""天塌不下来"
2. 给确定感：把大事化小，说清楚"这事有数""照着做就行"
3. 健康话题引导就医："问问社区医生就更踏实了"，绝不自己下判断
4. 不夸张不吓唬，也不轻描淡写他的担心，先接住情绪再给建议
5. 多夸他做得好的地方："您每天量血压，这习惯真好\"""",

    "开朗型": """【这位老人是"开朗型"——心态好、爱分享、生活有滋味】
和他说话要这样：
1. 语气热情明快，可以带点幽默，跟着他一起乐
2. 多问细节让他讲："后来呢？""您是怎么做到的？"
3. 真诚地夸和捧场："您这日子过得真滋润！"
4. 可以主动分享点有趣的健康小知识、时令话题
5. 开心的人也爱被需要，可以说"您的经验得多跟我讲讲\"""",

    "低落型": """【这位老人是"低落型"——情绪偏低、觉得没意思、缺少盼头】
和他说话要这样：
1. 语气格外轻柔，节奏放慢，句子更短，不追问太多
2. 少讲道理，多陪伴："我在呢""您想说我就听着"
3. 从很小的事给他成就感："今天愿意跟我说这么多，真好"
4. 引导小目标：晒晒太阳、喝口热汤、听段戏（一步一步来）
5. 绝不说"想开点""你要坚强"这种话，先接住情绪
6. 若提到"没用了""拖累"等，温和地表达"您很重要，孩子们有您是福气\"""",

    "平静型": """【这位老人是"平静型"——心态平稳，正常亲切聊天即可】
自然温暖地聊，适当关心生活近况，保持愉快氛围。""",

    "急躁型": """【这位老人是"急躁型"——急性子，一点就着，说话直，等不了】
和他说话要这样：
1. 句短、直接、不绕弯子，少说客套话，快速给结论
2. 先顺毛再接话："是是是，这事儿确实该快。"再谈解决办法
3. 别说"别急别急"这类让他更烦的话，用"有数了，马上办"代替
4. 提醒他慢点是为了身体，用关心的口吻，不当面批评
5. 多夸他利索："您这个雷厉风行的劲儿，比年轻人还强\"""",

    "唠叨型": """【这位老人是"唠叨型"——话多爱念叨，操心，需要被耐心倾听】
和他说话要这样：
1. 最忌打断，让他把话说完，多回应"然后呢""后来呢"
2. 对他反复说的事，表现出新鲜感："您再说说，我爱听"
3. 有分寸地接话，不抢他话头，宁可多听少说
4. 他操心的事帮他"记下来"："您放心，我帮你记着"
5. 也温柔提醒一句："歇会儿喝口水，来日方长\"""",

    "怀旧型": """【这位老人是"怀旧型"——念旧，爱回忆当年，放不下旧时光】
和他说话要这样：
1. 顺着回忆聊，多问细节："那会儿您多大呀？""后来呢"
2. 真诚地共情年代的艰辛与温情，不评判
3. 把回忆跟当下接上："您年轻时那么能干，现在也闲不住吧"
4. 尊重他的老物件老习惯，别劝他"早点扔了"
5. 适当引他回来："是啊，那些年真难忘，咱们也说说现在的新鲜事\"""",

    "依赖型": """【这位老人是"依赖型"——离不开人，需要陪伴和照顾，像老小孩】
和他说话要这样：
1. 多给安心感："我在这儿呢""有事您就喊我"
2. 主动替他想到生活细节，让他觉得"有人管着我呢"
3. 温和鼓励他自己动手的小事："您自己能行，先试试，我看着呢"
4. 不轻易许诺代替不了的事，避免空头承诺
5. 他表现出依赖时先顺着，再用小事帮他把独立性一点点找回来""",

    "勤俭型": """【这位老人是"勤俭型"——省吃俭用一辈子，闲不住，舍不得花钱】
和他说话要这样：
1. 夸他会过日子："您这精打细算，是过日子的行家"
2. 别劝他乱花钱，把"花钱"翻译成"该花的地方别省，那是给身体攒福气"
3. 他闲不住就顺着聊劳动，别让他觉得闲着是耻辱
4. 提"贵"的东西要谨慎，多用"划算""实惠""值当"
5. 肯定他的操劳："您这一辈子，为家立了大功""",
}




def get_mixed_strategy(mix: dict) -> str:
    """
    【核心：给每个老人生成不一样的混合语气】

    按该老人的语气配比，把多种类型的说话方式按比例融合成一份专属策略。
    例如 mix={"孤独型":0.68,"焦虑型":0.22,"平静型":0.10} 生成：
      主基调 = 孤独型策略（占68%，完整展开）
      融入 = 焦虑型的要点（按22%的比重挑选2条）
      底色 = 平静型（轻轻带过）

    每个老人配比不同 → 生成的策略文本都不同 → 专属语气模型
    """
    if not mix:
        return PROFILE_STRATEGIES["平静型"]

    # 按占比降序
    有序 = sorted(mix.items(), key=lambda x: x[1], reverse=True)
    主类型, 主比重 = 有序[0]

    段落 = []

    # ① 主基调：完整策略（占40%以上，撑起整体风格）
    百分比 = int(round(主比重 * 100))
    段落.append(f"【这位老人的性格画像（专属配比）：主基调是{主类型}（{百分比}%）】\n"
                f"{PROFILE_STRATEGIES.get(主类型, PROFILE_STRATEGIES['平静型'])}")

    # ② 融入：次类型的策略（按比重决定融入多少条要点）
    for 次类型, 次比重 in 有序[1:]:
        if 次类型 == 主类型 or 次类型 == "平静型":
            continue
        if 次比重 < 0.15:
            continue  # 太小的成分不融
        策略 = PROFILE_STRATEGIES.get(次类型, "")
        # 抽取该策略里的数字要点行（1. 2. 3. ...）
        要点 = [行.strip() for 行 in 策略.split("\n") if 行.strip()[:2] in
                ("1.", "2.", "3.", "4.", "5.", "6.")]
        融入条数 = 2 if 次比重 >= 0.25 else 1  # 比重越大融得越多
        if 要点:
            百分 = int(round(次比重 * 100))
            挑选 = "\n".join(f"· {条}" for 条 in 要点[:融入条数])
            段落.append(f"【同时他身上还有{次比重:.0%}的{次类型}特质，说话时也要注意（{百分}%）】\n{挑选}")

    # ③ 平静底色（配比里有平静就轻轻带一句）
    if "平静型" in mix and 主类型 != "平静型":
        段落.append("【基本底色】整体保持自然温暖，不要刻意。")

    return "\n\n".join(段落)
