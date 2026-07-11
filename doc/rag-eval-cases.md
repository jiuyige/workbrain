# RAG Evaluation Cases

| ID | 类型 | 问题 | 预期结果 |
| --- | --- | --- | --- |
| K1 | 可回答 | WorkBrain 的聊天和 Agent 使用什么服务？ | DeepSeek，且有引用 |  
| K2 | 可回答 | 文档向量用什么模型生成？ | OpenAI、text-embedding-3-small，且有引用 |
| K3 | 可回答 | 文档切分大小和重叠大小分别是多少？ | 500、100，且有引用 |
| K4 | 可回答 | 当前支持哪些文档格式？ | txt、md，且有引用 |
| K5 | 可回答 | 删除待办前需要做什么？ | 请求用户确认，且有引用 |
| U1 | 应拒答 | 上海明天天气怎么样？ | 无法回答，sources 为空 |
| U2 | 应拒答 | WorkBrain 的月费是多少钱？ | 无法回答，sources 为空 |
| U3 | 应拒答 | 项目使用 LangChain 吗？ | 无法回答，sources 为空 |


## 测试结果

| ID | 答案正确 | 来源正确 | top_score | 是否正确拒答 | 备注 |
| --- | --- | --- | --- | --- | --- |
| K1 | 是 | 是 | 1.0000 | - | DeepSeek；[S1] 指向评测资料 |
| K2 | 是 | 是 | 0.6317 | - | OpenAI、text-embedding-3-small；[S1] 指向评测资料 |
| K3 | 是 | 是 | 0.7610 | - | 500 个字符、重叠 100 个字符；[S1] 指向评测资料 |
| K4 | 是 | 是 | 0.6849 | - | txt、md；[S1] 指向评测资料 |
| K5 | 是 | 是 | 0.5926 | - | 删除前请求用户确认；[S1] 指向评测资料 |
| U1 | - | - | - | 是 | 正确拒答，sources 为空，used_llm=false |
| U2 | - | - | - | 是 | 正确拒答，sources 为空，used_llm=false |
| U3 | - | - | - | 是 | 正确拒答，sources 为空，used_llm=false |
