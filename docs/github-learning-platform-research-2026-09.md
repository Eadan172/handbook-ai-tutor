# GitHub 同类学习平台近期调研（2026-09）

## 1. 调研范围与方法

- 调研时间：2026-09-20。
- “近一个月”口径：GitHub 仓库的 `pushed_at` 位于 **2026-08-20 至 2026-09-20**。
- 目标能力：PDF/PPT/视频课程导入、语音转录、视觉内容理解、基于课程内容的 Quiz、带来源的 Q&A，以及中文/多语言支持。
- 日期证据：以 GitHub REST API 仓库元数据中的 `pushed_at` 为准；`updated_at` 可能只表示收藏、Issue 等活动，不单独作为代码更新证据。
- 功能证据：以项目 README、Release 和 Changelog 为准。以下结论仅说明可借鉴方向，不代表项目已经过完整安全或质量审计。

## 2. 符合时间范围的项目

### 2.1 THU-MAIC/OpenMAIC

- 仓库：https://github.com/THU-MAIC/OpenMAIC
- 最近推送：**2026-09-20 13:14:20 UTC**
- 日期证据：https://api.github.com/repos/THU-MAIC/OpenMAIC
- 定位：多智能体互动课堂，可从主题或资料生成幻灯片、Quiz、互动模拟和项目式学习内容。
- 相关能力：
  - 支持多格式课程资料与 `.pptx` 导入。
  - 支持音视频内容提取、教师讲解、白板和公式。
  - Quiz 支持单选、多选、简答、实时评分和反馈。
  - Release 中包含 MP4 课程渲染、字幕、公式与 Quiz 状态持久化。
- 对本项目的借鉴：
  1. 将课程资料解析为统一的“场景/页面/时间段”中间表示，而不是只把语音转录全文直接交给 Quiz 模型。
  2. 视频帧/PPT/板书与转录文本分别提取，再通过时间戳对齐，形成多模态课程证据。
  3. Quiz 生成只消费课程知识证据；课程安排、寒暄、教师口头禅等应在进入生成阶段前过滤。

### 2.2 abinthomas9322/study-rag-tutor

- 仓库：https://github.com/abinthomas9322/study-rag-tutor
- 最近推送：**2026-09-16 15:08:15 UTC**
- 日期证据：https://api.github.com/repos/abinthomas9322/study-rag-tutor
- 定位：面向班级共享课程空间的 PDF RAG Tutor，提供课程问答、引用和评分 Quiz。
- 相关能力：
  - PDF 按课程切分、嵌入并建立独立向量索引。
  - 回答限定为课程材料内容，并返回原文引用。
  - Quiz 从相同课程材料生成，提交后服务端评分并给出逐题解释。
- 对本项目的借鉴：
  1. Q&A 与 Quiz 应共享同一份规范化、UTF-8 的课程知识库，避免两条链路产生不同文本质量。
  2. Prompt 明确要求“只能依据材料”；材料没有答案时应说明证据不足，降低非课程问题和幻觉。
  3. Quiz 应保留证据片段或来源位置，便于检查题目是否真正来自课程知识。

### 2.3 tridpt/LectureDigest

- 仓库：https://github.com/tridpt/LectureDigest
- 最近推送：**2026-09-10 08:04:33 UTC**
- 日期证据：https://api.github.com/repos/tridpt/LectureDigest
- 定位：把 YouTube 或上传的音视频课程转成摘要、Quiz、闪卡、思维导图和学习计划。
- 相关能力：
  - 生成 8–12 道带解释和视频时间戳的选择题。
  - 提供章节时间线、关键时刻、同步转录搜索和基于整节课上下文的问答。
  - 输出支持中文等 7 种语言。
- 对本项目的借鉴：
  1. 每道题绑定时间戳和解释，可让系统自动回查对应画面与转录证据。
  2. 先生成章节、关键概念和学习目标，再从这些结构化结果生成题目，比直接从原始转录出题更稳定。
  3. 输出语言应由课程语言或用户设置显式控制，避免模型自动切换语言或产生乱码样式的异常文本。

### 2.4 tekdi/shiksha-mfe

- 仓库：https://github.com/tekdi/shiksha-mfe
- 最近推送：**2026-08-31 04:04:48 UTC**
- 日期证据：https://api.github.com/repos/tekdi/shiksha-mfe
- 定位：面向 LMS 的 AI 内容、测评和微学习平台。
- 相关能力：
  - PDF、PPT、视频、音频导入。
  - PyMuPDF/python-pptx 结构化解析，Whisper 转录、说话人分离和自动章节。
  - 生成 MCQ、配对题、填空题，并可输出 H5P/SCORM。
  - 支持人工审核流程。
- 对本项目的借鉴：
  1. 把“语音转录”“说话人信息”“PPT/文档结构”“视频章节”保留为独立字段，避免把元信息混入课程正文。
  2. 题目生成前增加结构化内容与人工可审核的中间结果。
  3. 异步处理适合较大的 MP4；解析完成后再开放 Quiz，避免只取得部分内容时提前出题。

## 3. 因时间不符而未纳入主清单的项目

以下项目功能相关，但 GitHub API 的 `pushed_at` 不在近一个月范围内，因此不能作为“近一个月更新项目”：

- `Ahmonemb/QuizStream`：上传 MP4 并使用 Gemini 生成 Quiz；`pushed_at` 为 2026-04-07。
- `mohammaditabassumkhatib-oss/ilm-study-assistant`：多模态 PDF RAG、图表/扫描页理解、引用式 Quiz；`pushed_at` 为 2026-05-30。
- `JayeshMargi/AI-COURSE-GENERATOR`：课程、Quiz 与 RAG Tutor；`pushed_at` 为 2026-08-09。其 `updated_at` 虽为 2026-09-12，但不能证明近一个月有代码推送。

## 4. 对当前三个问题的落地建议

### 4.1 统一编码边界

- `.env`、Prompt 模板、转录结果和 API JSON 全链路统一使用 UTF-8。
- Python 文件读取显式指定 `encoding="utf-8"`；HTTP JSON 显式使用 UTF-8，并避免对已经解码的字符串再次 `encode/decode`。
- 数据库连接、表字段及容器 locale 也需检查，不能只修改前端显示。

### 4.2 视频 Quiz 改为“课程知识证据驱动”

推荐处理链路：

1. 对音轨做转录并保留时间戳。
2. 按场景变化或固定间隔抽取关键帧，对 PPT、板书、公式和图表做视觉识别。
3. 按时间戳融合语音与画面，生成章节、知识点、定义、例子和学习目标。
4. 过滤课程安排、课堂管理、寒暄、教师自述、口头禅等非知识内容。
5. Quiz 仅基于结构化知识点生成，并要求题目、答案、解释均能关联证据片段。
6. 若画面与讲解冲突，标记为低置信度，避免强行出题。

### 4.3 Q&A 使用同一份规范化课程语料

- Q&A 检索与 Quiz 生成使用同一份清洗后的课程语料及字符编码。
- 响应返回前做 Unicode 合法性和替换字符（`�`）检查。
- 增加中文问答与中英混合内容的回归测试，覆盖上传、入库、检索、模型响应和前端渲染。

## 5. 本次修改的优先级

1. 检查并修复 `.env` 的实际字节编码，同时确认加载方式。
2. 定位视频解析与 Quiz Prompt，确认当前是否仅使用语音转录。
3. 定位 Q&A 的乱码产生层（模型响应、SSE/JSON、数据库或前端渲染）。
4. 实施统一 UTF-8 与课程知识过滤；在当前技术栈允许时加入视频视觉内容。
5. 增加针对中文 Q&A 和“非课程内容不得出题”的自动化测试。

## 6. 主要资料链接

- OpenMAIC README：https://github.com/THU-MAIC/OpenMAIC
- OpenMAIC Releases：https://github.com/THU-MAIC/OpenMAIC/releases
- OpenMAIC Changelog：https://github.com/THU-MAIC/OpenMAIC/blob/main/CHANGELOG.md
- Study RAG Tutor：https://github.com/abinthomas9322/study-rag-tutor
- LectureDigest：https://github.com/tridpt/LectureDigest
- Shiksha MFE：https://github.com/tekdi/shiksha-mfe

