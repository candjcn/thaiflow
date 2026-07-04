import os
import json
import requests


def translate_segments(segments, source_lang="泰语"):
    """
    调用 DeepSeek API 将句子列表翻译为中文。
    segments: [{"index": 0, "text": "..."}, ...]
    返回: [{"index": 0, "text": "...", "translation": "..."}, ...]
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未配置 DEEPSEEK_API_KEY")

    # 构建翻译 prompt
    lines = []
    for seg in segments:
        lines.append(f'{seg["index"]}. {seg["text"]}')
    text_block = "\n".join(lines)

    prompt = (
        f"请将以下{source_lang}句子逐句翻译为中文。\n"
        f"严格按照 JSON 数组格式返回，每个元素包含 index 和 translation 字段。\n"
        f"只返回 JSON，不要任何其他文字。\n\n"
        f"示例返回格式：\n"
        f'[{{"index": 0, "translation": "你好"}}, {{"index": 1, "translation": "谢谢"}}]\n\n'
        f"待翻译内容：\n{text_block}"
    )

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=30,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]

    # 解析 JSON（处理可能的 markdown 代码块包裹）
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
    translations = json.loads(content)

    # 合并翻译结果到原始 segments
    trans_map = {t["index"]: t["translation"] for t in translations}
    result = []
    for seg in segments:
        result.append(
            {
                "index": seg["index"],
                "text": seg["text"],
                "translation": trans_map.get(seg["index"], ""),
            }
        )
    return result
