// Verified against linked official documentation on 2026-10-15. Editable examples,
// not a guarantee of account access or parsing capability; no preset sends a request.
export const MODEL_PRESETS = [
 {id:'deepseek',label:'DeepSeek',name:'DeepSeek Flash',base_url:'https://api.deepseek.com',model:'deepseek-flash',docs:'https://api-docs.deepseek.com/api/list-models/',console:'https://platform.deepseek.com',hint:'在 DeepSeek 开放平台创建 API Key。可读取当前账户可用模型，模型名也可手动修改。'},
 {id:'openai',label:'OpenAI',name:'GPT-4.1 mini',base_url:'https://api.openai.com/v1',model:'gpt-4.1-mini',docs:'https://developers.openai.com/api/reference/resources/models/methods/list',console:'https://platform.openai.com/api-keys',hint:'在 OpenAI API 平台创建 API Key。可读取当前账户可用模型，模型名也可手动修改。'},
 {id:'qwen',label:'通义千问',name:'Qwen Plus',base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus',docs:'https://help.aliyun.com/zh/model-studio/list-models',console:'https://bailian.console.aliyun.com',hint:'在百炼创建同地域 API Key。兼容模式下可读取模型列表，模型名也可手动修改。'},
];
