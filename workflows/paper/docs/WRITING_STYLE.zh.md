# 稿件写作规范与篇幅约束（2026-11-19）

## 1. 为什么改

产线稿件越改越长、越改越“防御”。例子是 V0651 Hya 单星测光论文（`papers/20261114-physics-photometry-v0651hya-tess-geometry`）：
送审版（统一评审 20261119T102636Z 的 `manuscript-expanded.tex`）正文约 1.18 万词、全文 44 页；摘要塞进似然阈值和逐扇区区间；
结论一句话带三层限定；审稿人指出“修订史式叙述”。根因是每轮评审和形式核查只会要求补限定、补说明，没有任何环节要求删减或限制篇幅；
可读性技能只是“参考”。

用户要求（2026-11-19）：

- 写稿仍由一个模型从头到尾写完，**不**拆成多个模型、多个阶段，不新增任务类型或调度环节（配置
  `[program.owner].writing_runner` 后，这个模型是写稿者，求解仍由原负责人做，见 `docs/operations.zh.md`“写稿者交接”）；
- 约束手段只有三种：技能文本、脚本检查、写稿者在同一会话里调用的“模拟读者”；
- 文风客观中立、平实、逻辑清楚、少 AI 味和防御性写作；正文是“问题—方案—实验—结果”的连贯叙事。

## 2. 写稿者读到什么

| 环节 | 读到的规则 | 位置 |
|---|---|---|
| 负责人坐席（`topic_owner`）每一份简报 | “Writing rules (binding, not optional)”一行：动笔前、每次改稿前读可读性技能，先写故事线，跑 `narrative-check` 和 `reader-check` | `orchestrator/src/openlabs/owner.py` 的 `WRITING_RULES`，由 `render_brief` 的 Tools 段输出 |
| 负责人收到重算式复审（minor/major）和统一评审意见时 | 改稿落点规则：补充的限定、检验、说明默认进附录和回复信，正文每项至多一句，正文不得净增 | `owner.py` 的 `REVISION_RULE`，附在 `_review_note` 与 `_after_recompute` 的回馈说明后 |
| 旧式 writer 任务与负责人都读的共享写稿技能 | “Write”节开头：可读性技能是约束不是参考；步骤里加故事线、`narrative-check`、`reader-check`、改稿落点 | `workflows/paper/skills/openlabs-paper-writing/SKILL.md` |
| 规则正文 | 故事线、正文/附录分工、摘要、限定语、修订史、自造标签、空转过渡（中英文对照表）、改稿规则、自查程序、审稿人读法 | `workflows/paper/skills/openlabs-paper-readability/SKILL.md` |

## 3. 规则要点（技能正文的摘要）

1. **先写故事线**：`papers/<paper_id>/writing/storyline.md`，一页：读者是谁、一个主结果（带关键数字）、三四个支撑点、一个主要局限、哪些内容进附录。
   正文按它逐节展开。该目录在稿件目录旁边，不进稿件快照指纹，也不进期刊源码包。
2. **正文与附录分工**：正文只放主线需要的方法、关键实验和主要结果；稳健性检验、收敛与数值分辨率、逐项敏感性、未采用的替代模型、
   次要对照、长推导、逐子样本表格、完整误差预算进附录或补充材料，正文用一句话加引用指过去。与主问题相关的负结果留在正文。
3. **摘要**：一个问题、一个主结果和表述它所需的数字（值与不确定度）、一两句平实的方法、对领域的意义。不放检验阈值、逐子样本区间、
   采样器/管线名（除非它就是贡献）、内部标签和括号里的限定。
4. **限定语**：结论句至多一层限定；局限集中写在一节，不在每句后重复；不写修订史；不用自造标签；不堆砌“值得注意的是/综上所述/此外”
   和 “It is worth noting / Notably / In summary” 一类空转过渡。技能里有中英文各六组“避免—改写”示例。
5. **改稿**：评审或形式核查要求补充的内容默认落到附录和回复信，正文每项至多改一句；正文篇幅不得净增，除非审稿人把该项明确放在正文
   （`placement: main_text`）；“结论过强”改结论本身，不加免责声明；审稿人的删减意见照做。

## 4. 脚本检查：`paper-writing narrative-check`

代码：`workflows/paper/paper_writing/narrative_check.py`；测试：`workflows/paper/tests/test_narrative_check.py`。

```bash
PYTHONPATH=workflows/paper python3 -m paper_writing narrative-check --paper-id PID --root DATA_ROOT [--json] [--out REPORT.md]
PYTHONPATH=workflows/paper python3 -m paper_writing narrative-check --tex path/to/main.tex     # 不经登记文件
```

它也在 `style-check` 里运行（结果在 `narrative`、`narrative_warnings` 字段）。

**正文的界定**：摘要结束（或 `\maketitle`）之后，到第一个 `\appendix`、`\begin{appendices}`、`\backmatter`、致谢/声明/数据可用性等
后置章节或参考文献为止。图表标题计词；表格内容、展示公式、正文中的 AI 使用声明小节不计。中文按 `cjk_chars_per_word`（默认 1.7 字折 1 词）折算。

| 代码 | 级别 | 含义 |
|---|---|---|
| `NARRATIVE-BODY-LENGTH` | 失败 | 正文词数超过 `max_body_words`；报告最大的几节并提示把什么移到附录 |
| `NARRATIVE-BODY-PAGES` | 失败 | 设置了 `max_body_pages` 时，估算页数（词数/550 + 图表数×0.35）超限 |
| `NARRATIVE-REVISION-HISTORY` | 失败 | 摘要、正文、附录里的修订史用语（“in the previous version”“had previously been excluded”“as requested by the referee”“上一版”“经复核后”“根据审稿意见”等），逐条给行号 |
| `NARRATIVE-ABSTRACT-WORDS / -NUMBERS / -TEST-STATISTICS / -PARENTHETICALS` | 警告 | 摘要词数、数字个数（展开数值宏后计数）、检验量与推断术语（ΔlnL、χ²、p<、似然、后验、MCMC 等）、括号限定 |
| `NARRATIVE-HEDGE-DENSITY` | 警告 | 英文/中文 hedging 词表的千词密度，列出最常见的几个 |
| `NARRATIVE-STACKED-QUALIFIERS` | 警告 | 单句限定标记（hedge、范围限定、让步、括号旁白）≥ 4 的句子过多，逐句给行号；图表标题不计 |
| `NARRATIVE-CONCLUSION-QUALIFIERS` | 警告 | 结论类句子（摘要、结论节、“we find/表明”等）出现两种以上限定，逐句给行号 |
| `NARRATIVE-FILLER-TRANSITIONS` | 警告 | 空转过渡词的密度，并逐条给行号 |
| `NARRATIVE-BODY-GROWTH` | 警告 | 与最近一次统一评审快照（`reviews/unified/<pid>/<run>/manuscript-expanded.tex`）相比正文净增超过 2%，且上一轮没有 `placement: main_text` 的要求 |

**失败的后果**：两类失败进入 `style-check` 的 `errors`，在统一评审投前检查阶段就拦下（`preflight_failed`，不消耗科学轮次，回写稿者），
交付出口（handoff、`zenodo release`）同样拦截。警告作为 `narrative` 类的 `preparation_advisories` 记进决定记录。

**阈值**（从弱到强逐层覆盖，键名与 `DEFAULT_LIMITS` 相同）：

1. 代码默认按稿件类型（`ARTICLE_TYPE_LIMITS`）：普通论文 7000 词，letter/短文 3500，会议 6500，综述 12000，数学 14000；
   摘要 250 词、10 个数字、0 个检验量、3 个括号限定；hedge 4/千词；空转过渡 1.5/千词。类型由 `narrative_article_type`、`venue_type`、
   `target_journal_article_type`/`article_type`、`domain` 推断。
2. `registry/settings.yaml#quality_gate.narrative`（可带 `article_types.<类型>`）。
3. 研究线：`registry/research-lines.yaml` 的 `lines[].paper_narrative`，论文登记文件写了 `research_line` 时生效（或命令行 `--line`）。
4. 论文登记文件的 `narrative_limits`——目标期刊自己的篇幅上限写在这里。
5. `warnings_blocking: true` 把所有警告升为失败。

这些计数是启发式的，只用来给行号、提示问题，不是文风打分；警告要读，但不要为了压数字去改写成别扭的句子。

## 5. 模拟读者：`paper-writing reader-check`

代码：`workflows/paper/paper_writing/reader_check.py`。

```bash
PYTHONPATH=workflows/paper python3 -m paper_writing reader-check --paper-id PID --root DATA_ROOT
#   [--provider anthropic --tool "Claude Code" --model MODEL]   指定读者模型
#   --prompt-only                                                只写出读者材料，交给写稿者自己开的子 agent
#   --record ANSWER.json                                         登记子 agent 按 schema 给出的答案
```

- 读者只拿到标题、摘要和正文（不含附录、补充材料、故事线和任何作者笔记），在新进程里、工具关闭，以“目标期刊的一位同行读者、只读一遍”
  回答固定问题：一句话说出这篇论文做了什么、主结果是什么、读到哪里想放弃、哪些段落是在自我辩护而非陈述、哪些可以删或移到附录，
  并给出 `would_read_to_the_end | would_skim | would_stop_early`。
- 结果存到 `papers/<paper_id>/writing/reader-check.md` 和 `.json`（含正文的 sha256、稿件版本、读者模型），运行记录在
  `writing/reader-check-runs/<时间>/`（提示词、输出、回执）。写稿者把读者的一句话概括和主结果与故事线对照，不一致就说明故事还没讲清。
- 统一评审写决定信时，编辑收到 `author_reader_check`（标明是作者侧自查、是否与当前正文一致）。初审和审稿人看不到它，避免被作者侧材料带偏。
- **为什么用独立模型而不是写稿者自己重读**：写稿者知道故事线，判断不出外人在哪里迷路；只读过正文的读者才能。它仍是写稿者会话里的一次工具调用，
  不新增调度任务、不消耗评审轮次，结论只作建议。读者模型取 `quality_gate.reader_check.role`，未配置时用评审的工作档
  `review.roles.formal_verifier`（再退到 editor）；调用前与其他模型调用一样看 `dispatch_allowed`。调不了模型时用 `--prompt-only` / `--record`。

## 6. 评审侧规则

不新增角色或环节，只改提示词与 schema：

- **审稿人**（`references/unified/referee.md`）：每个 `required_changes` 必须带 `placement`：`appendix_or_response`（默认）、`main_text`（只在主线
  离不开时，并说明理由）、`cut`（删除或移出正文）。审稿人可以并应当提出删减意见；局限说过一次就算说过，不要求每个结果旁边重复。
  schema 里 `placement` 为必填（`review_flow.REFEREE_SCHEMA`）。
- **编辑初审**（`editor.md`）：评审包里附正文词数与上限（`## Main-text length`）；正文逐项罗列检验与限定、或逐轮因补限定而变长，属于表达问题，要指出移到附录或删除什么。
- **决定信**（`decision.md`）：收到 `main_text_length`（当前正文词数、上限、上一轮评审版本的词数与增幅）和 `author_reader_check`；正文超限或在没有正文要求时变长，
  要在信里写明并要求删减；每个必改项保留落点。
- **形式核查**（`formal.md`）：按正文加附录、补充材料整体判断；附录里写了的限定、条件、步骤算已写，不得因为正文没有重复而判缺口或错误；需要补的步骤默认放附录。
- **重算式复审**（`openlabs-recompute-review/SKILL.md`）：每个 `required`/`optional` 条目以 `[main text]`、`[appendix/response]` 或 `[cut]` 开头，默认后者；
  不因正文没重复附录里的条件而判不通过。
- 决定记录新增 `body_length` 字段，留存当轮的正文词数与增幅。

## 7. 对现有稿件的影响

- 已在评审中的稿件，下一次 `style-check` 或统一评审投前检查会按新规则计数；正文超限或含修订史用语的稿件在投前检查被退回写稿者，
  不消耗轮次。目标期刊上限更宽（如长文期刊）的，在论文登记文件写 `narrative_limits` 并注明来源。
- `REFEREE_SCHEMA` 新增必填字段 `placement`；旧决定记录里没有该字段的条目按原逻辑处理（缺字段视为非正文要求）。
