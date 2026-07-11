# WorkBrain RAG Test Data

- WorkBrain 的聊天和 Agent 使用 DeepSeek。
- WorkBrain 的文档向量使用 OpenAI 的 text-embedding-3-small。
- 文档初始切分大小为 500 个字符，重叠 100 个字符。
- 当前只支持 txt 和 md 文档提取。
- 删除待办属于危险操作，必须先请求用户确认。