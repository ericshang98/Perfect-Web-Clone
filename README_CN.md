# Perfect Web Clone

**跑在 DeepSeek Harness 上的像素级克隆 agent。丢一个 URL。过不过看门禁，不看模型自夸。**

- 对话循环、模型、session：DeepSeek Harness
- 抽页、切 section、拼壳、打分：本仓 `pwc` 核心（不调 LLM）
- 剧本：`skill/SKILL.md`（和 [skill 仓](https://github.com/ericshang98/perfect-web-clone-skill) 同一份）

旧的 Claude Agent SDK + FastAPI + Next.js IDE 在 `v2-archive` 标签。不要在那套循环上继续改。

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium
npx @deepseek-ai/dsh web
dsh plugin --profile web add github:ericshang98/Perfect-Web-Clone
```

然后说：`clone https://example.com`
