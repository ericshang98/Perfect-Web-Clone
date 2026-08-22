# Perfect Web Clone

**完美复刻任意网页。** 本仓是测量核心。产品是 [Skill](skill/SKILL.md)：一套 agent harness，一句话 `clone <url>` 走完整页、带分数的复刻。

把网页变成截图不算复刻。Skill 逼着 agent 走完：抓取 → 切 section → 干净 React → 构建 → 按测量结果修最差的一块。不许在第一屏停，也不许把长得像但不能点的控件当完成。

## 你拿到的是什么

- 整页抓取：DOM、计算样式、字体、图片、视频
- 干净的 Vite + React + Tailwind，不是源站框架的搬运
- 资源全部本地化，不再热链原站
- 门禁：源站指纹、代码体积、逐 section 视觉分数
- 修最差的一块，重建，再测

对你的 coding agent 说：

```text
clone https://example.com
```

## 安装

需要 Python 3.10+ 和 Node 20+。

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium
```

把 [`perfect-web-clone-skill`](https://github.com/ericshang98/perfect-web-clone-skill) 装进 Claude Code、Codex，或任何能跑 `pwc` 的 coding agent。

## 一次复刻怎么走

1. 抓取活页（完整性检查，资源本地化）
2. 按真实区块切 section
3. 每个 section 写成干净的 React
4. 拼装、构建
5. 打指纹、体积、视觉分
6. 修最差的一块，重建，再测
7. 给你本地预览：`ready_for_user_review` 或 `failed_with_residuals`

如果页面是 WebGL、运行时 canvas、或滚动编排，会先报 ceiling。内容仍能复刻，运行时画出来的观感不一定能。

## License

MIT
