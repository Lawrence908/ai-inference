# Open WebUI Configuration for Local/Cloud Toggle

## How It Works

Open WebUI has built-in support for filtering models by source using the model dropdown in the top-left of the chat interface.

### Model Sources

1. **Local Models (Ollama)**
   - Configured via `OLLAMA_BASE_URL=http://ollama:11434`
   - Models appear in the "All" filter when downloaded
   - Shows models directly from Ollama

2. **Cloud Models (Unified Proxy)**
   - Configured via `OPENAI_API_BASE_URL=http://ai-inference-proxy:8192`
   - Models appear in the "External" filter
   - Also appear in "All" filter
   - Routes through unified proxy to OpenRouter

### Using the Toggle

1. **Open the model dropdown** (top-left of chat interface)
2. **Use the filter buttons:**
   - **"All"** - Shows both local (Ollama) and external (cloud) models
   - **"External"** - Shows only cloud models from OpenRouter

3. **Local models automatically appear** when you download them via Ollama:
   ```bash
   docker exec ai-ollama ollama pull llama3
   docker exec ai-ollama ollama pull mistral
   ```

### Model Selection Behavior

- **Local models** (from Ollama): 
  - Direct connection to Ollama
  - Fast, no API costs
  - Requires GPU for best performance
  
- **Cloud models** (from OpenRouter):
  - Routes through unified proxy
  - Auto-detects backend or uses `?backend=cloud` parameter
  - May incur API costs

### Configuration

The `compose.yaml` is configured with:
- `OLLAMA_BASE_URL` - Direct Ollama connection for local models
- `OPENAI_API_BASE_URL` - Unified proxy for cloud models

Both are available simultaneously, and Open WebUI automatically distinguishes between them in the UI.

## Adding Context Pack as External Tool

To add the context pack service as an external tool in Open WebUI:

1. **Go to Settings** → **External Tools** → **Manage Tool Servers**
2. **Click the "+" button** to add a new tool server
3. **Enter the OpenAPI specification URL:**
   ```
   http://context-pack:8000/openapi.json
   ```
   Or use the docs endpoint:
   ```
   http://context-pack:8000/docs
   ```
4. **Configure CORS** - The context pack service already has CORS enabled for all origins
5. **Save** the configuration

### Available Context Pack Tools

Once added, the following tools will be available:
- `search` - Search context database
- `generate` - Generate responses with RAG
- `generate_with_skills` - Generate with skills context
- `list_skills` - List available skills
- `get_skill` - Get specific skill content
- `list_bundles` - List skill bundles

### Using Context Pack Tools

After adding the tool server, you can:
1. Select a model (local or cloud)
2. The context pack tools will be available in the chat interface
3. The AI can call these tools automatically when needed
4. Or you can manually invoke them in your prompts

## Troubleshooting

### Local models not showing
- Check Ollama is running: `docker ps | grep ollama`
- Check models are downloaded: `docker exec ai-ollama ollama list`
- Refresh Open WebUI or restart the container

### Cloud models not showing
- Check unified proxy is running: `docker ps | grep ai-inference-proxy`
- Check OpenRouter API key is set: `echo $OPENROUTER_API_KEY`
- Check proxy health: `curl http://localhost:8192/health`

### Context pack not working
- Check service is running: `docker ps | grep context-pack`
- Check OpenAPI endpoint: `curl http://context-pack:8000/openapi.json`
- Verify CORS is enabled in context pack service
- Check Open WebUI logs for tool server connection errors

