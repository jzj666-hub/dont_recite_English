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
            "text": (
                "你是资深英语老师型助手。回答风格要求：\n"
                "1) 以连贯自然的段落叙述为主，默认不要分点、不要编号、不要模板化小标题。\n"
                "2) 避免空话、套话与泛泛建议；直接围绕用户问题给出可落地、可理解的分析。\n"
                "3) 逻辑必须自洽，先讲核心判断，再讲原因与语境，必要时补一个精炼例子。\n"
                "4) 语气沉稳、有见识，像博学且耐心的老师，不说教、不居高临下。\n"
                "5) 除非用户明确要求列表或步骤，否则不要输出列表结构。"
            ),
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
                "要求：6-12 个词，全部英文小写，不能包含原词，不能包含短语。"
                "仅允许输出标签为“{link_type}”的候选词，不要混入其他标签。\n"
                "原词：{word}\n"
                "目标标签：{link_type}"
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
                "硬性要求：释义字段只写“新增/修正点”，禁止复述原始中文释义已有内容。\n"
                "只有当例句与常见用法也都无法体现新增语义时，才允许返回 [\"无新增\"]。\n"
                "若例句或常见用法出现了新的语义/语境差异，释义必须明确写出对应新增点，禁止写“无新增”。\n"
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
        "quiz_context_rewrite_prompt": {
            "agent": "UserFeaturesMixin.build_quiz_questions_with_ai_batch",
            "purpose": "随机考词题型3批量改写语境（严格 JSON 输出）",
            "text": (
                "你是英语命题助手。请一次性完成多题改写，输出严格 JSON，不要 markdown。\n"
                "仅处理题型3（英文语境猜义），题型1/2不需要处理。\n"
                "每题要求：\n"
                "1) 只改写题干与英文语境，不改选项文本。\n"
                "2) 选项必须全部保留，顺序可变。\n"
                "3) 必须保留且仅保留一个正确答案。\n"
                "4) 输出格式：{\"items\":[{\"index\":0,\"question\":\"...\",\"context\":\"...\",\"choices\":[{\"text\":\"...\",\"is_correct\":true}],\"answer_index\":1}]}\n\n"
                "语境难度：{difficulty}\n"
                "题目列表：{tasks_json}"
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
        "quiz_summary_system": {
            "agent": "UserFeaturesMixin._quiz_summary_worker",
            "purpose": "随机考词 AI 小结 system",
            "text": "你是英语学习助手。",
        },
        "quiz_summary_prompt": {
            "agent": "UserFeaturesMixin.build_quiz_summary_prompt",
            "purpose": "随机考词结果总结（总评/用法/易混词/错题分析）",
            "text": (
                "你是英语学习教练。请根据随机考词结果给出学习反馈。\n"
                "要求：\n"
                "1) 先给总评（学习状态、薄弱点）。\n"
                "2) 给出常见用法（短语、固定搭配、例句要点）。\n"
                "3) 给出易混词辨析（至少 2 组，说明区别和记忆点）。\n"
                "4) 如果有错题，逐题解释为什么错、正确思路、如何避免再错。\n"
                "5) 纯文本输出，中文为主，英文词汇保留原文。\n\n"
                "{wrong_tip}\n\n"
                "答题明细：\n"
                "{details}"
            ),
        },

        # 文档解读：析文标签页（框选片段做划线注解）
        "wordcraft_generate_prompt": {
            "agent": "UserFeaturesMixin.build_wordcraft_prompt",
            "purpose": "选词成文生成（英文正文+中文译文+命中特殊词）",
            "text": (
                "你是英语学习助手。请先完成“阶段1：生成草稿”。\n"
                "请用给定目标词写一篇连贯、自然、细节完整的英文文章，并给出中文译文。\n"
                "输出要求：\n"
                "1) 严格只输出 JSON，不要输出任何额外文本。\n"
                "2) JSON 格式：{\"english\":\"...\",\"chinese\":\"...\",\"special_words\":[\"w1\",\"w2\"]}\n"
                "3) english 只保留英文正文；chinese 只保留中文译文。\n"
                "4) special_words 仅包含正文里实际出现、且来自目标词列表的英文单词（去重，按出现顺序）。\n\n"
                "质量要求：\n"
                "- 文章要上下文连贯，避免跳句、断裂表达。\n"
                "- 尽量不要引入语法错误、搭配错误与时态错误。\n"
                "- 英文正文字数不设上限，不要为了控制长度而牺牲完整性。\n\n"
                "目标难度：{difficulty}\n"
                "选词依据：{basis}\n"
                "目标词：{words}"
            ),
        },
        "wordcraft_generation_system": {
            "agent": "UserFeaturesMixin._wordcraft_worker",
            "purpose": "选词成文双阶段（生成+审查）system",
            "text": "你是英语学习助手。请严格按用户要求输出。",
        },
        "wordcraft_review_prompt": {
            "agent": "UserFeaturesMixin.build_wordcraft_review_prompt",
            "purpose": "选词成文审查与润色（二阶段：修正语法与连贯性）",
            "text": (
                "你是英语学习助手。请完成“阶段2：审查错误并润色”。\n"
                "你会收到阶段1产出的 JSON 草稿，请你只做质量修正：\n"
                "1) 修正英文中的语法、拼写、标点、搭配、时态与指代问题。\n"
                "2) 提升连贯性，消除断裂感，让段落自然衔接。\n"
                "3) 修正中文译文中的明显错误，使其与英文一致。\n"
                "4) 不要删除核心信息，不要改写成完全不同的内容。\n"
                "5) 英文正文字数不设上限，不要强行压缩长度。\n\n"
                "输出要求：\n"
                "- 严格只输出 JSON，不要输出任何额外文本。\n"
                "- JSON 格式：{\"english\":\"...\",\"chinese\":\"...\",\"special_words\":[\"w1\",\"w2\"]}\n"
                "- special_words 仅包含最终英文正文里实际出现、且来自目标词列表的英文单词（去重，按出现顺序）。\n\n"
                "目标难度：{difficulty}\n"
                "选词依据：{basis}\n"
                "目标词：{words}\n\n"
                "阶段1草稿 JSON：\n{draft_json}"
            ),
        },
        "wordcraft_explain_system": {
            "agent": "UserFeaturesMixin._wordcraft_explain_worker",
            "purpose": "选词成文逐段讲解 system",
            "text": "你是英语学习助手。",
        },
        "wordcraft_explain_prompt": {
            "agent": "UserFeaturesMixin.build_wordcraft_explain_prompt",
            "purpose": "选词成文逐段讲解与降档建议",
            "text": (
                "你是英语学习助手。请逐一讲解用户看不懂的英文片段。\n"
                "原始目标词：{words}\n"
                "目标难度：{difficulty}\n"
                "待讲解片段：\n{segments}\n\n"
                "输出要求：\n"
                "1) 按片段编号逐一解释，包含词义、语法或语境难点。\n"
                "2) 最后单独一行输出：DOWNGRADE_WORDS: w1, w2\n"
                "3) DOWNGRADE_WORDS 只从原始目标词中选 0-5 个，不要输出其它格式。"
            ),
        },
        "wordcraft_annotation_prompt": {
            "agent": "UserFeaturesMixin.on_wordcraft_ai_annotate_selected",
            "purpose": "选词成文框选片段注释（结合上下文）",
            "text": (
                "你是英语学习助手。请结合上下文解释用户选中的英文片段。\n"
                "输出要求：\n"
                "1) 只输出纯文本，不要标题、序号、Markdown、代码块。\n"
                "2) 第一行必须先用中文引号输出该片段在当前语境下的直接意思，例如： “……” 。\n"
                "3) 引号句后，再补充关键语境点或语法点，内容务实、简短、易懂，中文为主。\n\n"
                "待解读上下文：\n{source_context}\n\n"
                "待解读内容：\n{selected_text}\n\n"
                "仅输出最终注释正文。"
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
        "ai_import_extract_system": {
            "agent": "UserFeaturesMixin._ai_import_worker",
            "purpose": "AI 智能导入（文件结构解析）system",
            "text": "你是一个精通文件格式解析的 Python 编程助手。只用代码块回答，不要多余解释。",
        },
        "ai_import_extract_prompt": {
            "agent": "UserFeaturesMixin._ai_import_worker",
            "purpose": "AI 智能导入（从样本生成 extract_words 函数代码）",
            "text": (
                "你是一个文件解析助手。用户给你一个文件的前 500 字符样本，你需要分析这个文件的存储结构，"
                "然后写出一段 Python 代码来提取其中所有的英语单词或短语。\n\n"
                "**要求：**\n"
                "1. 你的回复中必须包含且仅包含一个 Python 代码块（用 ```python ... ``` 包裹）\n"
                "2. 代码必须定义一个函数 `extract_words(file_path: str) -> list[str]`\n"
                "3. 该函数接收完整的文件路径，返回一个字符串列表，每个元素是一个英语单词或短语\n"
                "4. 不要导入任何第三方库，只用 Python 标准库（如 re, csv, json, xml 等）\n"
                "5. 尽可能智能地识别文件结构，提取出所有英语词汇/短语，去除重复\n"
                "6. 如果文件中有中文释义、音标等附加信息，只提取英文单词部分\n\n"
                "**文件名：** {file_name}\n\n"
                "**文件样本（前 500 字符）：**\n```\n{sample}\n```"
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

