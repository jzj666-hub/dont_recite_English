import json


def default_ai_prompts():
    """
    所有可配置 AI 提示词集中在这里，便于在设置中公开、编辑、恢复默认。
    约定：每个 key 对应一个“提示词对象”，包含它属于哪个 agent/用途，以及最终要发给模型的 text。
    为了兼容旧版本：代码会同时支持 value 为字符串的旧格式。
    """
    return {
        # 通用 system
        "chat_system": {
            "agent": "AIChatWindow",
            "purpose": "通用聊天 system，用于定义 AI 角色与回答风格",
            "text": "你是英语学习助手。回答需要准确、清晰、结合上下文。",
        },
        "json_system": {
            "agent": "JSON/Extractor",
            "purpose": "要求模型严格输出 JSON（给收藏夹推荐、关联词、考核评档等任务）",
            "text": "You are a strict JSON generator.",
        },
        "translator_system": {
            "agent": "LLMTranslationMixin",
            "purpose": "补充翻译/双语输出的 system",
            "text": "You are a precise bilingual translator.",
        },
        "note_ai_system": {
            "agent": "NoteAI/Helper",
            "purpose": "词条页 AI 服务、考核提示等通用辅助说明",
            "text": "You are a helpful English learning assistant for Chinese users.",
        },

        # 右键“语境提问”
        "selection_answer_rules": {
            "agent": "AIAssistantMixin.ask_ai_for_selected_text",
            "purpose": "右键框选语境提问的回答约束",
            "text": "回答要求：先解释含义，再说明在此语境下的作用，最后给1-2条学习建议。",
        },

        # 词条页 AI 服务（写入批注）
        "detail_ai_header": {
            "agent": "UserFeaturesMixin.build_ai_prompt",
            "purpose": "词条页 AI 服务开头要求（写入批注）",
            "text": (
                "你是英语学习助手。输出必须直接、准确、可执行，不要寒暄。\n"
                "总要求：中文说明为主；必要时给英文例子+中译；避免空泛描述。"
            ),
        },
        "detail_ai_tail": {
            "agent": "UserFeaturesMixin.build_ai_prompt",
            "purpose": "词条页 AI 服务结尾约束（写入批注）",
            "text": "输出约束：每段尽量短，信息完整，不重复。",
        },

        # AI 收藏夹推荐
        "smart_favorite_prompt": {
            "agent": "AIAssistantMixin.on_ai_smart_favorite_clicked",
            "purpose": "根据词条选择合适收藏夹（JSON 输出）",
            "text": (
                "你是英语学习助手。请根据给定词条，在候选收藏夹中选择最合适的 1-3 个。"
                "只输出 JSON，不要输出任何其他文本。"
                "格式：{{\"folders\":[\"收藏夹1\",\"收藏夹2\"]}}。\n"
                "词条：{query}\n"
                "候选收藏夹：{folders}"
            ),
        },

        # AI 推荐关联词
        "suggest_links_prompt": {
            "agent": "AIAssistantMixin.on_ai_suggest_links_clicked",
            "purpose": "为当前单词推荐关联词（JSON 输出）",
            "text": (
                "你是英语学习助手。请根据给定单词输出最相关的英文关联词。"
                "只输出 JSON，不要额外文本。"
                "JSON 格式：{{\"links\":[{{\"word\":\"word1\",\"tag\":\"近义词\"}},{{\"word\":\"word2\",\"tag\":\"反义词\"}}]}}"
                "tag 只能是：近义词、反义词、形近词。"
                "要求：6-12 个词，全部英文小写，不能包含原词，不能包含短语。\n"
                "原词：{word}"
            ),
        },

        # LLM 补充翻译
        "llm_translate_prompt": {
            "agent": "LLMTranslationMixin.build_llm_translate_prompt",
            "purpose": "LLM 补充翻译提示词（JSON 输出，含释义/例句/常见用法）",
            "text": (
                "你是英语学习翻译助手。任务是“补充与修正原始中文释义”，不是全盘重译。请严格只输出 JSON 对象，不要输出任何其他字符。\n"
                "JSON 必须包含三个键：释义、例句、常见用法。\n"
                "释义：{meaning_rule}\n"
                "例句：字符串数组，给2条英文例句，每条后面带中文翻译。\n"
                "常见用法：字符串数组，给3条高频用法，每条简短。\n"
                "如果输入是单词，先参考原始中文释义，再补充其遗漏点。\n"
                "硬性要求：释义字段只写“新增/修正点”，禁止复述原始中文释义已有内容；若没有新增点，返回 [\"无新增\"]。\n"
                "输入类型：{kind}\n"
                "输入内容：{text}\n"
                "原始中文释义：{original_meaning}"
            ),
        },

        # 随机考词：单词提示
        "quiz_hint_prompt": {
            "agent": "UserFeaturesMixin.on_quiz_hint_clicked",
            "purpose": "考核中给单词逐步提示（轻/中/强提示）",
            "text": (
                "你是英语学习助手。\n"
                "用户正在进行单词考核。请针对该单词给一个“循序渐进”的提示：\n"
                "1) 先给一句非常轻的提示（不直接给答案），例如词性/语境/同义词方向。\n"
                "2) 再给一句中等提示（可给1个英文例句，挖空关键词）。\n"
                "3) 最后给一句强提示（给出关键中文释义关键词，但不要完整照搬词典释义）。\n"
                "输出只用中文。\n"
                "单词：{word}\n"
                "用户当前作答：{answer}"
            ),
        },

        # 随机考词：最终评档（必须输出 JSON）
        "quiz_grade_prompt": {
            "agent": "UserFeaturesMixin.on_quiz_submit_clicked",
            "purpose": "考核结束统一评档（严格 JSON 输出 + 固定格式 final_lines）",
            "text": (
                "你是英语学习助手兼评测员。你需要根据用户对每个单词的中文释义回答，判断是否正确、是否依赖提示，并给出熟练度调整建议。\n"
                "熟练度档位（从低到高）：拉完了, NPC, 夯, 人上人, 顶级。\n"
                "规则：\n"
                "A) 如果依赖提示才答对：熟练度一般不变，或向第三档“夯”靠拢（根据释义全面程度决定）。\n"
                "B) 如果不依赖提示答对：一定不降档；根据最近查询时间（越久没搜代表印象越深）与释义全面程度决定是否升档。\n"
                "C) 如果答错：可适度降档（但不要一次降太多）。\n"
                "输出要求：严格只输出 JSON，不要输出其他文本。\n"
                "JSON 格式：\n"
                "{{\n"
                "  \"results\": [\n"
                "    {{\"word\":\"...\",\"before\":\"人上人\",\"hint_used\":false,\"last_at\":\"2026-01-01T10:00:00\",\"answer\":\"...\",\"correct\":true,\"final\":\"顶级\",\"comment\":\"...\"}}\n"
                "  ],\n"
                "  \"overall_comment\":\"...\",\n"
                "  \"final_lines\": [\"word1: 顶级\", \"word2: NPC\"]\n"
                "}}\n"
                "其中 final_lines 必须包含每个单词一行，格式严格为：<word>: <档位>\n"
                "输入数据：\n"
                "{items_json}"
            ),
        },

        # 文档解读：析文标签页（框选片段做划线注解）
        "wordcraft_generate_prompt": {
            "agent": "UserFeaturesMixin.build_wordcraft_prompt",
            "purpose": "选词成文生成（英文正文+中文译文+命中特殊词）",
            "text": (
                "你是英语学习助手。请用给定目标词写一段自然英文短文，并给出中文译文。\n"
                "输出要求：\n"
                "1) 严格只输出 JSON，不要输出任何额外文本。\n"
                "2) JSON 格式：{\"english\":\"...\",\"chinese\":\"...\",\"special_words\":[\"w1\",\"w2\"]}\n"
                "3) english 只保留英文正文；chinese 只保留中文译文。\n"
                "4) special_words 仅包含正文里实际出现、且来自目标词列表的英文单词（去重，按出现顺序）。\n\n"
                "目标难度：{difficulty}\n"
                "选词依据：{basis}\n"
                "目标词：{words}"
            ),
        },
        "doc_reader_explain_prompt": {
            "agent": "UserFeaturesMixin.on_doc_ai_explain_clicked",
            "purpose": "对框选片段输出纯文本注释（结合上下文）",
            "text": (
                "你是英语学习助手。请结合上下文解释用户选中的英文片段是什么意思。\n"
                "输出要求：\n"
                "1) 只输出纯文本，不要标题、序号、Markdown、代码块。\n"
                "2) 先给片段在此处的核心含义，再补充关键语境点或语法点。\n"
                "3) 内容务实、简短、易懂，中文为主。\n\n"
                "待解读上下文：\n{source_context}\n\n"
                "待解读内容：\n{selected_text}\n\n"
                "仅输出最终注释正文。"
            ),
        },
    }


def loads_prompts(text):
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def prompt_text(prompts_obj, key, fallback=""):
    """
    从 prompts 中取指定 key 的可用 text。
    兼容两种格式：
    - value 为字符串：直接返回
    - value 为对象：优先取 value['text']
    """
    if not isinstance(prompts_obj, dict):
        return fallback
    v = prompts_obj.get(key)
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        t = v.get("text")
        return t if isinstance(t, str) else fallback
    return fallback

